"""Analisa as conversas do GHL com IA e salva a classificação no banco (e no GHL, se GRAVAR_NO_GHL=sim).

Exemplos:
  python -m coletor.main --dias 30 --limite 50 --seco   # teste: 50 conversas, não grava nada, gera CSV
  python -m coletor.main --dias 30                      # retroativo: último mês, salva no banco
                                                # (e no GHL só se GRAVAR_NO_GHL=sim no .env)
  python -m coletor.main                                # incremental: só o que mudou desde a última execução
"""

import argparse
import csv
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from coletor import banco, config
from coletor.classificar import Classificador, montar_contexto, montar_transcricao
from coletor.contatos import completar_contatos, dados_do_contato, mapa_campos_utm
from coletor.ghl import GHL

UM_DIA_MS = 24 * 60 * 60 * 1000
PREFIXO_SEGURO = "ia-"


def slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "-".join(sem_acento.lower().split())


def mapear_campos(ghl: GHL, taxonomia: dict) -> dict[str, str]:
    """Nome do campo no GHL -> id. Para se algum campo da taxonomia não existir."""
    existentes = {c["name"]: c["id"] for c in ghl.campos_personalizados()}
    nomes = [c["campo_ghl"] for c in taxonomia["categorias"]] + [taxonomia["resumo"]["campo_ghl"]]
    faltando = [n for n in nomes if n not in existentes]
    if faltando:
        raise SystemExit(
            f"Campos não encontrados no GHL: {', '.join(faltando)}\n"
            "Rode antes: python -m coletor.sincronizar_campos"
        )
    return {n: existentes[n] for n in nomes}


def lead_respondeu(conversa: dict, desde_ms: int) -> bool:
    """Se o lead escreveu algo desde `desde_ms`, pelos dados da listagem (sem buscar mensagens).

    WhatsApp: o GHL informa a data da última mensagem recebida. Outros canais (Instagram,
    e-mail...) são poucos e vão sempre para a IA, que decide se houve resposta.
    """
    if (conversa.get("lastInboundWhatsappMessageDate") or 0) >= desde_ms or conversa.get(
        "lastMessageDirection"
    ) == "inbound":
        return True
    return (conversa.get("lastMessageType") or "TYPE_WHATSAPP") != "TYPE_WHATSAPP"


def resultado_sem_resposta(taxonomia: dict) -> dict:
    """Classificação fixa para quem nunca respondeu (sem chamar a IA)."""
    fixos = taxonomia.get("sem_resposta", {})
    resultado = {}
    for cat in taxonomia["categorias"]:
        valor = fixos.get(cat["chave"], "Não identificado")
        if valor not in [o["valor"] for o in cat["opcoes"]]:
            raise SystemExit(
                f"taxonomia.json: '{valor}' não é opção de '{cat['chave']}' (bloco sem_resposta)"
            )
        resultado[cat["chave"]] = valor
    resultado["resumo"] = fixos.get("resumo", "Lead não respondeu.")
    return resultado


def gravar_no_ghl(
    ghl: GHL,
    taxonomia: dict,
    ids_campos: dict,
    contact_id: str,
    resultado: dict,
    tags_atuais: list[str] | None = None,
) -> None:
    campos = [
        {"id": ids_campos[cat["campo_ghl"]], "field_value": resultado[cat["chave"]]}
        for cat in taxonomia["categorias"]
    ]
    campos.append({"id": ids_campos[taxonomia["resumo"]["campo_ghl"]], "field_value": resultado["resumo"]})
    ghl.atualizar_campos(contact_id, campos)

    # Tags espelhadas: troca a tag antiga de cada categoria pela nova (ex.: ia-seg:imobiliaria).
    # Só toca em tags com prefixo "ia-": tags que o time já usa na conta nunca são removidas.
    if tags_atuais is None:
        tags_atuais = ghl.contato(contact_id).get("tags", [])
    tags_atuais = [t.lower() for t in tags_atuais]
    novas, remover = [], []
    for cat in taxonomia["categorias"]:
        prefixo = f"{cat['prefixo_tag']}:"
        if not prefixo.startswith(PREFIXO_SEGURO):
            raise SystemExit(
                f"prefixo_tag '{cat['prefixo_tag']}' precisa começar com '{PREFIXO_SEGURO}' (taxonomia.json)"
            )
        nova = prefixo + slug(resultado[cat["chave"]])
        remover += [t for t in tags_atuais if t.startswith(prefixo) and t != nova]
        if nova not in tags_atuais:
            novas.append(nova)
    ghl.remover_tags(contact_id, remover)
    ghl.adicionar_tags(contact_id, novas)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dias", type=int, help="analisar conversas com mensagem nos últimos N dias")
    parser.add_argument("--limite", type=int, help="máximo de conversas a analisar nesta execução")
    parser.add_argument(
        "--seco", action="store_true", help="não grava no GHL nem no banco; gera CSV para conferência"
    )
    parser.add_argument("--forcar", action="store_true", help="reanalisa mesmo conversas que não mudaram")
    args = parser.parse_args()

    config.exigir("GHL_TOKEN", "GHL_LOCATION_ID", "OPENAI_API_KEY")
    taxonomia = config.carregar_taxonomia()
    ghl = GHL(config.GHL_TOKEN, config.GHL_LOCATION_ID)
    classificador = Classificador(taxonomia)
    db = banco.conectar()
    print(f"Banco: {db.onde}")
    inicio_ms = int(time.time() * 1000)

    if args.dias:
        desde_ms = inicio_ms - args.dias * UM_DIA_MS
        modo = "retroativo"
    else:
        desde_ms = db.ultima_execucao_ms() or inicio_ms - UM_DIA_MS
        modo = "incremental"
    if args.seco:
        modo = "seco"
    # GRAVAR_NO_GHL desligado: o GHL só é lido (conversas e contatos), nada é escrito nele
    gravar_ghl = config.GRAVAR_NO_GHL and not args.seco
    ids_campos = mapear_campos(ghl, taxonomia) if gravar_ghl else None
    print("GHL: " + ("grava campos e tags nos contatos" if gravar_ghl else "somente leitura"))
    campos_utm = mapa_campos_utm(ghl)
    contatos_lidos: list[dict] = []

    print(
        f"Modo {modo} | conversas desde {datetime.fromtimestamp(desde_ms / 1000):%d/%m/%Y %H:%M}", flush=True
    )
    ja_feitas = {} if args.forcar or args.seco else db.mapa_analisadas()
    conversas, sem_resposta, vistas = [], [], set()
    for c in ghl.conversas_desde(desde_ms):
        if not c.get("contactId") or c["contactId"] in config.IGNORAR_CONTATOS or c["id"] in vistas:
            continue
        vistas.add(c["id"])
        ultima_feita, modelo_feito = ja_feitas.get(c["id"], (-1, None))
        if ultima_feita >= (c.get("lastMessageDate") or 0):
            continue
        if lead_respondeu(c, desde_ms):
            conversas.append(c)
        elif modelo_feito in (None, "sem-ia"):
            sem_resposta.append(c)
        # já analisada pela IA e o lead não respondeu de novo: mantém a análise (não vira "sem resposta")
        if args.limite and len(conversas) + len(sem_resposta) >= args.limite:
            break
    print(
        f"{len(conversas)} conversas com resposta do lead (vão para a IA) | "
        f"{len(sem_resposta)} sem resposta (registradas sem IA)",
        flush=True,
    )

    if sem_resposta and not args.seco:
        padrao = resultado_sem_resposta(taxonomia)
        for i in range(0, len(sem_resposta), 500):
            db.salvar_lote([(c, padrao, 0, 0) for c in sem_resposta[i : i + 500]], "sem-ia")
        print(f"{len(sem_resposta)} conversas sem resposta salvas no banco", flush=True)

    def processar(conversa: dict):
        mensagens, truncada = ghl.mensagens(conversa["id"], config.MAX_MENSAGENS)
        transcricao, do_lead = montar_transcricao(mensagens)
        if not transcricao or do_lead < config.MIN_MENSAGENS_LEAD:
            return None
        contato = ghl.contato(conversa["contactId"])
        contatos_lidos.append(dados_do_contato({**contato, "id": conversa["contactId"]}, campos_utm))
        contexto = montar_contexto(contato, truncada, config.MAX_MENSAGENS)
        resultado, t_in, t_out = classificador.classificar(transcricao, contexto)
        if gravar_ghl:
            gravar_no_ghl(
                ghl, taxonomia, ids_campos, conversa["contactId"], resultado, contato.get("tags", [])
            )
        return resultado, t_in, t_out

    analisadas, ignoradas, erros = [], 0, 0
    tokens_in = tokens_out = 0
    with ThreadPoolExecutor(max_workers=config.PARALELO) as pool:
        futuros = {pool.submit(processar, c): c for c in conversas}
        for i, futuro in enumerate(as_completed(futuros), 1):
            conversa = futuros[futuro]
            nome = conversa.get("fullName") or conversa.get("contactName") or conversa["contactId"]
            try:
                saida = futuro.result()
            except Exception as e:  # uma conversa com erro não derruba as outras
                erros += 1
                print(f"[{i}/{len(conversas)}] ERRO {nome}: {e}", flush=True)
                continue
            if saida is None:
                ignoradas += 1
                continue
            resultado, t_in, t_out = saida
            tokens_in += t_in
            tokens_out += t_out
            analisadas.append((conversa, resultado))
            if not args.seco:
                db.salvar_analise(conversa, resultado, t_in, t_out)
            resumo_cats = " | ".join(resultado[c["chave"]] for c in taxonomia["categorias"])
            print(f"[{i}/{len(conversas)}] {nome}: {resumo_cats}", flush=True)

    if args.seco:
        exportar_csv(taxonomia, analisadas)
    else:
        # UTMs e origem: salva os contatos já lidos e completa os que faltam (sem IA, só leitura do GHL)
        db.salvar_contatos(contatos_lidos)
        completados = completar_contatos(ghl, db, limite=config.CONTATOS_POR_RODADA, paralelo=config.PARALELO)
        print(f"Contatos com UTMs/origem atualizados: {len(contatos_lidos) + completados}", flush=True)
        db.registrar_execucao(inicio_ms, modo, len(analisadas) + len(sem_resposta), erros)

    custo = tokens_in / 1e6 * config.PRECO_ENTRADA_1M + tokens_out / 1e6 * config.PRECO_SAIDA_1M
    print(
        f"\nAnalisadas pela IA: {len(analisadas)} | sem resposta (sem IA): {len(sem_resposta)} | "
        f"puladas (sem mensagens): {ignoradas} | erros: {erros}"
    )
    print(f"Tokens: {tokens_in:,} entrada / {tokens_out:,} saída | custo estimado: US$ {custo:.4f}")
    for cat in taxonomia["categorias"]:
        contagem = Counter(r[cat["chave"]] for _, r in analisadas)
        if contagem:
            print(f"\n{cat['chave']}:")
            for valor, n in contagem.most_common():
                print(f"  {valor:<28} {n}")


def exportar_csv(taxonomia: dict, analisadas: list) -> None:
    pasta = config.RAIZ / "relatorios"
    pasta.mkdir(exist_ok=True)
    caminho = pasta / f"teste_{datetime.now():%Y%m%d_%H%M}.csv"
    chaves = [c["chave"] for c in taxonomia["categorias"]]
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["contato", "contact_id", "conversation_id", *chaves, "resumo"])
        for conversa, r in analisadas:
            w.writerow(
                [
                    conversa.get("fullName") or conversa.get("contactName"),
                    conversa.get("contactId"),
                    conversa["id"],
                    *[r[k] for k in chaves],
                    r["resumo"],
                ]
            )
    print(f"\nCSV para conferência: {caminho}")


if __name__ == "__main__":
    main()
