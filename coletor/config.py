"""Configuração lida do .env e da taxonomia."""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent  # pasta do projeto
load_dotenv(RAIZ / ".env")

# Console do Windows em UTF-8 para acentos não quebrarem
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _env(nome: str, padrao: str = "") -> str:
    return os.getenv(nome, padrao).strip()


GHL_TOKEN = _env("GHL_TOKEN")
GHL_LOCATION_ID = _env("GHL_LOCATION_ID")

OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-5-mini")
OPENAI_REASONING_EFFORT = _env("OPENAI_REASONING_EFFORT", "low")

# Postgres na nuvem. Vazio = usa o SQLite local (dados.db), bom só para testes.
DATABASE_URL = _env("DATABASE_URL")

PRECO_ENTRADA_1M = float(_env("PRECO_ENTRADA_1M", "0.25"))
PRECO_SAIDA_1M = float(_env("PRECO_SAIDA_1M", "2.00"))

MAX_MENSAGENS = int(_env("MAX_MENSAGENS", "30"))
MIN_MENSAGENS_LEAD = int(_env("MIN_MENSAGENS_LEAD", "0"))
PARALELO = int(_env("PARALELO", "4"))
# "sim" = grava campos "IA - ..." e tags "ia-" nos contatos do GHL. Padrão: só lê o GHL.
GRAVAR_NO_GHL = _env("GRAVAR_NO_GHL", "nao").lower() in ("sim", "s", "true", "1")
# IDs de contatos internos (grupos de aviso, números da equipe) que não entram nas métricas
IGNORAR_CONTATOS = {c.strip() for c in _env("IGNORAR_CONTATOS").split(",") if c.strip()}
# Quantos contatos sem UTMs lidos completar por rodada (a 1ª vez são ~12 mil; vai completando aos poucos)
CONTATOS_POR_RODADA = int(_env("CONTATOS_POR_RODADA", "4000"))

# Planilha de agendamentos dos closers (Google Sheets). PLANILHA_ID = trecho do link entre /d/ e /edit.
PLANILHA_ID = _env("PLANILHA_ID")
# Credencial da conta de serviço do Google: caminho do arquivo .json (local) ou o conteúdo (GitHub).
GOOGLE_CREDENCIAIS = _env("GOOGLE_CREDENCIAIS", "google-leitor.json")
GOOGLE_CREDENCIAIS_JSON = _env("GOOGLE_CREDENCIAIS_JSON")
# Para testes: ler a planilha de um arquivo .xlsx baixado em vez do Google Sheets
PLANILHA_ARQUIVO = _env("PLANILHA_ARQUIVO")

CAMINHO_BANCO = RAIZ / "dados.db"
CAMINHO_TAXONOMIA = RAIZ / "taxonomia.json"


def carregar_taxonomia() -> dict:
    with open(CAMINHO_TAXONOMIA, encoding="utf-8") as f:
        return json.load(f)


def exigir(*nomes: str) -> None:
    """Para a execução com mensagem clara se faltar alguma variável do .env."""
    faltando = [n for n in nomes if not globals().get(n)]
    if faltando:
        sys.exit(f"Faltam variáveis no .env: {', '.join(faltando)} (veja .env.example)")
