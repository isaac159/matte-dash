"""Lê a planilha de agendamentos dos closers e cruza cada reunião com o contato do GHL.

A planilha é a fonte oficial das reuniões. Só entram reuniões agendadas a partir do primeiro
dia de conversas analisadas, para os números baterem com o resto do dashboard.

  python -m coletor.reunioes            # lê (Google Sheets ou arquivo), cruza e salva no banco
  python -m coletor.reunioes --seco     # só mostra o resumo, não salva

Fonte da planilha (no .env):
  PLANILHA_ID + GOOGLE_CREDENCIAIS (arquivo .json) ou GOOGLE_CREDENCIAIS_JSON (conteúdo, no GitHub)
  PLANILHA_ARQUIVO=caminho.xlsx   (alternativa para testes)

Nome, telefone e e-mail da planilha só são usados aqui para o cruzamento: no banco ficam hashes.
"""

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta

from coletor import banco, config
from coletor.contatos import chave_email, chave_telefone, hash_chave

DIA_MS = 86_400_000
FUSO_MS = -3 * 3_600_000
EPOCA = date(1970, 1, 1)
EPOCA_PLANILHA = date(1899, 12, 30)  # data "zero" do Google Sheets/Excel

# Colunas fixas (iguais em todas as abas): 0 agendado no dia, 1 para o dia, 5 telefone,
# 6 closer, 7 e-mail, 8 SDR, 10 qualificação SDR, 11 qualificação closer, 12 status.
# As demais (motivo de perda, valores) mudam de posição e são achadas pelo título.
COL = {"agendado": 0, "reuniao": 1, "telefone": 5, "closer": 6, "email": 7, "sdr": 8}
COL.update({"qualif_sdr": 10, "qualif_closer": 11, "status": 12})

STATUS = {"comparecido": "Comparecido", "no show": "No show", "reagendamento": "Reagendamento"}
STATUS["cancelamento"] = "Cancelamento"
QUALIF_CLOSER = {"mql": "MQL", "desq": "DESQ", "no show": "No show", "com potencial": "Com potencial"}
QUALIF_CLOSER["reagendamento"] = "Reagendamento"


def sem_acento(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.lower().split())


def para_data(valor) -> date | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)):  # número de série do Sheets/Excel
        return EPOCA_PLANILHA + timedelta(days=int(valor)) if 20000 < valor < 80000 else None
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", str(valor))
    if m:
        d, mes, a = (int(x) for x in m.groups())
        try:
            return date(a + 2000 if a < 100 else a, mes, d)
        except ValueError:
            return None
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(valor))
    if m:
        return date(*(int(x) for x in m.groups()))
    return None


def dia(d: date | None) -> int | None:
    """Dias desde 1970 (mesma contagem do dashboard)."""
    return (d - EPOCA).days if d else None


def para_valor(texto) -> float | None:
    """'25k', 'Matte IA - 19k', 11000.0, 'R$ 19.164,00' -> número em reais."""
    if texto in (None, ""):
        return None
    if isinstance(texto, (int, float)):
        return float(texto) if texto > 0 else None
    t = str(texto).lower().replace("r$", "")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*k\b", t)
    if m:
        return float(m.group(1).replace(",", ".")) * 1000
    m = re.search(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?", t)
    if m:
        numero = float(m.group(0).replace(".", "").replace(",", "."))
        return numero if numero >= 100 else None
    return None


def _valor(linha, i):
    return linha[i] if i is not None and i < len(linha) else None


def interpretar(abas: dict[str, list[list]], dia_inicio: int | None) -> list[dict]:
    """Linhas das abas mensais -> reuniões (só agendadas a partir de dia_inicio)."""
    reunioes = []
    for aba, linhas in abas.items():
        cabecalho = col_motivo = col_vendido = None
        for n, linha in enumerate(linhas, 1):
            textos = [sem_acento(v) for v in linha]
            if "status" in textos and "telefone" in textos:
                cabecalho = textos
                col_motivo = next((i for i, t in enumerate(textos) if t.startswith("motivo de per")), None)
                col_vendido = next((i for i, t in enumerate(textos) if t.startswith("produto vendido")), None)
                continue
            if not cabecalho or len(linha) <= COL["status"]:
                continue
            telefone = _valor(linha, COL["telefone"])
            email = _valor(linha, COL["email"])
            status_bruto = sem_acento(_valor(linha, COL["status"]))
            agendado = para_data(_valor(linha, COL["agendado"]))
            reuniao = para_data(_valor(linha, COL["reuniao"]))
            if not (telefone or email) or not (agendado or reuniao):
                continue
            dia_ag = dia(agendado or reuniao)
            if dia_inicio is not None and dia_ag < dia_inicio:
                continue
            vendido_bruto = _valor(linha, col_vendido)
            vendido = vendido_bruto not in (None, "") and str(vendido_bruto).strip() != "0"
            qualif_closer = sem_acento(_valor(linha, COL["qualif_closer"]))
            dia_reun = dia(reuniao or agendado)
            if status_bruto:
                status = STATUS.get(status_bruto, "Outro")
            else:  # sem status: reunião futura ainda não aconteceu; passada ficou sem preencher
                status = "A realizar" if dia_reun >= dia(date.today()) else "Sem status"
            reunioes.append(
                {
                    "id": hashlib.sha256(f"{aba}:{n}".encode()).hexdigest()[:24],
                    "dia_agendamento": dia_ag,
                    "dia_reuniao": dia_reun,
                    "closer": str(_valor(linha, COL["closer"]) or "").strip().title() or "Sem closer",
                    "sdr": str(_valor(linha, COL["sdr"]) or "").strip().title() or "Sem SDR",
                    "qualificacao_sdr": str(_valor(linha, COL["qualif_sdr"]) or "").strip().upper() or None,
                    "qualificacao_closer": QUALIF_CLOSER.get(qualif_closer, "Sem qualificação"),
                    "status": status,
                    "motivo_perda": str(_valor(linha, col_motivo) or "").strip() or None,
                    "vendido": int(vendido),
                    "valor_vendido": para_valor(vendido_bruto),
                    "tel_hash": hash_chave(chave_telefone(telefone)),
                    "email_hash": hash_chave(chave_email(email)),
                }
            )
    return reunioes


def ler_google_sheets() -> dict[str, list[list]]:
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    escopos = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    if config.GOOGLE_CREDENCIAIS_JSON:
        info = json.loads(config.GOOGLE_CREDENCIAIS_JSON)
        credenciais = service_account.Credentials.from_service_account_info(info, scopes=escopos)
    else:
        caminho = config.RAIZ / config.GOOGLE_CREDENCIAIS
        credenciais = service_account.Credentials.from_service_account_file(str(caminho), scopes=escopos)
    sessao = AuthorizedSession(credenciais)
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{config.PLANILHA_ID}"
    meta = sessao.get(base, params={"fields": "sheets.properties.title"}, timeout=60)
    meta.raise_for_status()
    titulos = [s["properties"]["title"] for s in meta.json()["sheets"]]
    resp = sessao.get(
        f"{base}/values:batchGet",
        params={
            "ranges": [f"'{t}'" for t in titulos],
            "valueRenderOption": "UNFORMATTED_VALUE",
            "dateTimeRenderOption": "SERIAL_NUMBER",
        },
        timeout=120,
    )
    resp.raise_for_status()
    return {t: r.get("values", []) for t, r in zip(titulos, resp.json()["valueRanges"], strict=True)}


def ler_arquivo(caminho: str) -> dict[str, list[list]]:
    from openpyxl import load_workbook

    livro = load_workbook(caminho, read_only=True, data_only=True)
    return {aba.title: [list(linha) for linha in aba.iter_rows(values_only=True)] for aba in livro.worksheets}


def ler_planilha() -> tuple[dict[str, list[list]], str] | None:
    tem_credencial = config.GOOGLE_CREDENCIAIS_JSON or (config.RAIZ / config.GOOGLE_CREDENCIAIS).exists()
    if config.PLANILHA_ID and tem_credencial:
        return ler_google_sheets(), "Google Sheets"
    if config.PLANILHA_ARQUIVO:
        return ler_arquivo(config.PLANILHA_ARQUIVO), f"arquivo {config.PLANILHA_ARQUIVO}"
    return None


def cruzar(reunioes: list[dict], contatos: dict[str, dict]) -> int:
    """Liga cada reunião ao contato do GHL pelo telefone ou e-mail. Retorna quantas achou."""
    por_tel = {c["tel_hash"]: cid for cid, c in contatos.items() if c.get("tel_hash")}
    por_email = {c["email_hash"]: cid for cid, c in contatos.items() if c.get("email_hash")}
    achadas = 0
    for r in reunioes:
        r["contact_id"] = por_tel.get(r["tel_hash"]) or por_email.get(r["email_hash"])
        achadas += bool(r["contact_id"])
    return achadas


def atualizar(db: banco.Banco, seco: bool = False) -> None:
    lido = ler_planilha()
    if not lido:
        print("Planilha de reuniões não configurada (PLANILHA_ID + credencial do Google): pulando.")
        return
    abas, origem = lido
    primeiro_ms = db.primeiro_dia_conversas_ms()
    dia_inicio = (primeiro_ms + FUSO_MS) // DIA_MS if primeiro_ms else None
    reunioes = interpretar(abas, dia_inicio)
    achadas = cruzar(reunioes, db.listar_contatos())
    inicio_txt = (EPOCA + timedelta(days=dia_inicio)).strftime("%d/%m/%Y") if dia_inicio else "sempre"
    print(f"Planilha lida de {origem}: {len(reunioes)} reuniões agendadas desde {inicio_txt}")
    print(f"  ligadas a um contato do GHL: {achadas} ({achadas * 100 // max(1, len(reunioes))}%)")
    print("  status:", dict(Counter(r["status"] for r in reunioes).most_common()))
    if not seco:
        db.substituir_reunioes(reunioes)
        print("  reuniões salvas no banco")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seco", action="store_true", help="não salva no banco")
    args = parser.parse_args()
    atualizar(banco.conectar(), seco=args.seco)


if __name__ == "__main__":
    main()
