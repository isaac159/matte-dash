"""Classifica uma conversa com a API da OpenAI, presa às opções da taxonomia."""

import json

from openai import OpenAI

from coletor import config

LIMITE_CARACTERES_MENSAGEM = 1500  # mensagens do lead: é o que importa para a classificação
# Mensagens da Matte (disparos, follow-ups) são longas e repetidas: o começo basta para o contexto
LIMITE_CARACTERES_EMPRESA = 300


def montar_transcricao(mensagens: list[dict]) -> tuple[str, int]:
    """Converte mensagens do GHL em texto. Retorna (transcrição, nº de mensagens do lead)."""
    linhas = []
    do_lead = 0
    for m in mensagens:
        tipo = m.get("messageType") or ""
        if tipo.startswith("TYPE_ACTIVITY"):
            continue
        corpo = (m.get("body") or "").strip()
        if not corpo:
            if tipo == "TYPE_CALL":
                corpo = "[ligação]"
            elif m.get("attachments"):
                corpo = "[anexo/áudio/imagem]"
            else:
                continue
        if m.get("direction") == "inbound":
            autor, limite = "LEAD", LIMITE_CARACTERES_MENSAGEM
            do_lead += 1
        else:
            autor, limite = "EMPRESA", LIMITE_CARACTERES_EMPRESA
        if len(corpo) > limite:
            corpo = corpo[:limite].rstrip() + "…"
        data = (m.get("dateAdded") or "")[:16].replace("T", " ")
        linhas.append(f"[{data}] {autor}: {corpo}")
    return "\n".join(linhas), do_lead


def montar_schema(taxonomia: dict) -> dict:
    propriedades = {}
    for cat in taxonomia["categorias"]:
        propriedades[cat["chave"]] = {
            "type": "string",
            "enum": [o["valor"] for o in cat["opcoes"]],
            "description": cat["descricao"],
        }
    propriedades["resumo"] = {"type": "string", "description": taxonomia["resumo"]["descricao"]}
    return {
        "type": "object",
        "properties": propriedades,
        "required": list(propriedades),
        "additionalProperties": False,
    }


def montar_instrucoes(taxonomia: dict) -> str:
    partes = [
        "Você analisa conversas comerciais entre leads e a Matte, agência que implementa "
        "agentes de IA e automação de atendimento/vendas.",
        "Classifique a conversa escolhendo exatamente uma opção de cada categoria, "
        "usando os critérios abaixo. Baseie-se no que está na conversa e nos dados do contato "
        "no CRM (nome, empresa, domínio do e-mail); quando não houver evidência, use "
        "'Não identificado' (se existir na categoria).",
        "Mensagens marcadas como EMPRESA são da Matte (pessoas ou automações). "
        "Respostas automáticas de ausência do lead não contam como resposta.",
        "Regra importante: dor, dúvida e objeção são só o que o LEAD escreveu. O que a EMPRESA "
        "disse, ofereceu ou sugeriu (ex.: 'leads esfriam por falta de follow-up') nunca conta como "
        "dor do lead. Se o lead não descreveu um problema, use 'Não identificado' em dor_principal.",
        "",
    ]
    for cat in taxonomia["categorias"]:
        partes.append(f"## {cat['chave']} — {cat['descricao']}")
        for o in cat["opcoes"]:
            partes.append(f"- {o['valor']}: {o['descricao']}")
        partes.append("")
    partes.append(f"## resumo — {taxonomia['resumo']['descricao']} Escreva em português.")
    return "\n".join(partes)


class Classificador:
    def __init__(self, taxonomia: dict, modelo: str | None = None, esforco: str | None = None):
        self.cliente = OpenAI(api_key=config.OPENAI_API_KEY)
        self.instrucoes = montar_instrucoes(taxonomia)
        self.schema = montar_schema(taxonomia)
        self.modelo = modelo or config.OPENAI_MODEL
        self.esforco = config.OPENAI_REASONING_EFFORT if esforco is None else esforco

    def classificar(self, transcricao: str, contexto: str = "") -> tuple[dict, int, int]:
        """Retorna (resultado, tokens de entrada, tokens de saída).

        contexto: dados do contato no CRM e avisos (ex.: conversa truncada), em texto.
        """
        extras = {}
        if self.esforco:
            extras["reasoning_effort"] = self.esforco
        resp = self.cliente.chat.completions.create(
            model=self.modelo,
            messages=[
                {"role": "system", "content": self.instrucoes},
                {"role": "user", "content": f"{contexto}\n\nConversa:\n\n{transcricao}".strip()},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "classificacao_conversa", "strict": True, "schema": self.schema},
            },
            **extras,
        )
        escolha = resp.choices[0]
        if escolha.message.refusal:
            raise RuntimeError(f"IA recusou: {escolha.message.refusal}")
        if escolha.finish_reason == "length":
            raise RuntimeError("Resposta da IA cortada por limite de tokens")
        resultado = json.loads(escolha.message.content)
        uso = resp.usage
        return resultado, uso.prompt_tokens, uso.completion_tokens


PROVEDORES_EMAIL = {
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
    "yahoo.com.br",
    "icloud.com",
    "live.com",
    "bol.com.br",
    "uol.com.br",
    "terra.com.br",
    "msn.com",
    "me.com",
}


def montar_contexto(contato: dict, truncada: bool, maximo: int) -> str:
    """Dados do contato no CRM que ajudam a identificar o segmento (sem telefone)."""
    linhas = ["Dados do contato no CRM:"]
    nome = " ".join(filter(None, [contato.get("firstName"), contato.get("lastName")])) or contato.get(
        "contactName"
    )
    if nome:
        linhas.append(f"- Nome: {nome}")
    if contato.get("companyName"):
        linhas.append(f"- Empresa: {contato['companyName']}")
    dominio = (contato.get("email") or "").rpartition("@")[2].lower()
    if dominio and dominio not in PROVEDORES_EMAIL:
        linhas.append(f"- Domínio do e-mail: {dominio}")
    if contato.get("source"):
        linhas.append(f"- Origem registrada no CRM: {contato['source']}")
    if len(linhas) == 1:
        linhas.append("- (sem dados)")
    if truncada:
        linhas.append(
            f"Atenção: conversa longa, mostrando só as últimas {maximo} mensagens; o começo não aparece."
        )
    return "\n".join(linhas)
