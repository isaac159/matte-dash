"""UTMs e origem de cada contato (lidos do GHL, sem IA) e chaves para cruzar com a planilha.

Telefone e e-mail não são guardados: viram um hash (tel_hash / email_hash), suficiente para
achar o mesmo contato na planilha dos closers.

  python -m coletor.contatos   # completa os contatos que ainda não têm UTMs lidos
"""

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor

from coletor import banco, config
from coletor.ghl import GHL

CAMPOS_UTM = ["utm_source", "utm_medium", "utm_campaign", "utm_content"]


def chave_telefone(valor) -> str | None:
    """DDD + 8 últimos dígitos: ignora +55, zero à esquerda e o nono dígito (que às vezes falta)."""
    texto = str(valor or "").strip()
    if re.fullmatch(r"\d+\.0", texto):  # número lido da planilha como 17992358961.0
        texto = texto[:-2]
    digitos = re.sub(r"\D", "", texto)
    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos[2:]
    digitos = digitos.lstrip("0")
    if len(digitos) < 10:
        return None
    return digitos[:2] + digitos[-8:]


def chave_email(valor) -> str | None:
    email = str(valor or "").strip().lower()
    return email if "@" in email else None


def hash_chave(chave: str | None) -> str | None:
    return hashlib.sha256(f"matte:{chave}".encode()).hexdigest()[:32] if chave else None


def mapa_campos_utm(ghl: GHL) -> dict[str, str]:
    """id do campo personalizado -> nome do UTM (utm_source, ...)."""
    mapa = {}
    for campo in ghl.campos_personalizados():
        chave = (campo.get("fieldKey") or "").removeprefix("contact.")
        if chave in CAMPOS_UTM:
            mapa[campo["id"]] = chave
    return mapa


def dados_do_contato(contato: dict, campos_utm: dict[str, str]) -> dict:
    """Linha da tabela contatos a partir do contato do GHL."""
    linha = {"contact_id": contato.get("id")}
    for campo in contato.get("customFields") or []:
        nome = campos_utm.get(campo.get("id"))
        valor = campo.get("value")
        if nome and valor not in (None, ""):
            linha[nome] = str(valor).strip()[:200]
    atribuicao = contato.get("attributionSource") or {}
    linha["origem_crm"] = (
        atribuicao.get("sessionSource") or atribuicao.get("medium") or contato.get("source") or None
    )
    veio_de_formulario = bool(atribuicao.get("formId") or atribuicao.get("formName"))
    linha["veio_de_form"] = int(veio_de_formulario or any(linha.get(c) for c in CAMPOS_UTM))
    linha["tel_hash"] = hash_chave(chave_telefone(contato.get("phone")))
    linha["email_hash"] = hash_chave(chave_email(contato.get("email")))
    return linha


def completar_contatos(ghl: GHL, db: banco.Banco, limite: int, paralelo: int = 8) -> int:
    """Lê do GHL os contatos que ainda não estão na tabela contatos. Retorna quantos salvou."""
    faltando = db.contatos_sem_dados(limite)
    if not faltando:
        return 0
    campos_utm = mapa_campos_utm(ghl)

    def buscar(contact_id: str) -> dict | None:
        try:
            contato = ghl.contato(contact_id)
        except Exception:  # contato apagado no GHL etc.: registra vazio para não tentar sempre
            return {"contact_id": contact_id, "veio_de_form": 0}
        return dados_do_contato({**contato, "id": contact_id}, campos_utm)

    salvos = 0
    for inicio in range(0, len(faltando), 400):
        with ThreadPoolExecutor(paralelo) as pool:
            lote = [c for c in pool.map(buscar, faltando[inicio : inicio + 400]) if c]
        db.salvar_contatos(lote)
        salvos += len(lote)
        print(f"  contatos lidos do GHL: {salvos}/{len(faltando)}", flush=True)
    return salvos


def main() -> None:
    config.exigir("GHL_TOKEN", "GHL_LOCATION_ID")
    ghl = GHL(config.GHL_TOKEN, config.GHL_LOCATION_ID)
    db = banco.conectar()
    total = completar_contatos(ghl, db, limite=config.CONTATOS_POR_RODADA, paralelo=config.PARALELO)
    print(f"{total} contatos atualizados")


if __name__ == "__main__":
    main()
