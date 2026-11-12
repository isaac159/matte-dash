"""Histórico das análises: Postgres na nuvem (DATABASE_URL) ou SQLite local como reserva.

Tabelas:
  analises    situação mais recente de cada conversa (1 linha por conversa) -> alimenta o dashboard
  historico   toda análise feita, só acrescenta (mostra como a conversa evoluiu ao longo do tempo)
  execucoes   registro de cada rodada do main.py (controla o modo incremental)

  python -m coletor.banco   # testa a conexão, cria as tabelas e mostra quantas linhas há em cada uma
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from coletor import config

# Os comandos são separados por ";" ao executar: não use ";" dentro deles (nem em comentários).
ESQUEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS analises (
    conversation_id    TEXT PRIMARY KEY,
    contact_id         TEXT,
    nome_contato       TEXT,
    ultima_mensagem_ms BIGINT NOT NULL,
    analisado_em       TIMESTAMPTZ NOT NULL,
    modelo             TEXT,
    tokens_entrada     INTEGER,
    tokens_saida       INTEGER,
    resultado          JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS historico (
    id                 BIGSERIAL PRIMARY KEY,
    conversation_id    TEXT NOT NULL,
    contact_id         TEXT,
    ultima_mensagem_ms BIGINT NOT NULL,
    analisado_em       TIMESTAMPTZ NOT NULL,
    resultado          JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS historico_conversa_idx ON historico (conversation_id, analisado_em);
CREATE TABLE IF NOT EXISTS execucoes (
    id          BIGSERIAL PRIMARY KEY,
    inicio_ms   BIGINT NOT NULL,
    fim         TIMESTAMPTZ NOT NULL,
    modo        TEXT,
    analisadas  INTEGER,
    erros       INTEGER
);
"""
TABELAS = ["analises", "historico", "execucoes"]

ESQUEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS analises (
    conversation_id    TEXT PRIMARY KEY,
    contact_id         TEXT,
    nome_contato       TEXT,
    ultima_mensagem_ms INTEGER NOT NULL,
    analisado_em       TEXT NOT NULL,
    modelo             TEXT,
    tokens_entrada     INTEGER,
    tokens_saida       INTEGER,
    resultado          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS historico (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id    TEXT NOT NULL,
    contact_id         TEXT,
    ultima_mensagem_ms INTEGER NOT NULL,
    analisado_em       TEXT NOT NULL,
    resultado          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS historico_conversa_idx ON historico (conversation_id, analisado_em);
CREATE TABLE IF NOT EXISTS execucoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio_ms   INTEGER NOT NULL,
    fim         TEXT NOT NULL,
    modo        TEXT,
    analisadas  INTEGER,
    erros       INTEGER
);
"""


class Banco:
    def __init__(self):
        self.postgres = bool(config.DATABASE_URL)
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row

            # autocommit: leituras não deixam transação aberta; gravações usam self._transacao()
            self.con = psycopg.connect(
                config.DATABASE_URL, row_factory=dict_row, autocommit=True, connect_timeout=15
            )
            self._preparar_postgres()
        else:
            self.con = sqlite3.connect(config.CAMINHO_BANCO)
            self.con.row_factory = sqlite3.Row
            self.con.executescript(ESQUEMA_SQLITE)

    def _preparar_postgres(self) -> None:
        """Cria as tabelas e liga o RLS só quando falta algo.

        ALTER TABLE trava a tabela inteira: rodar a cada conexão faria uma execução esperar
        a outra (ex.: gerar o dashboard enquanto o main.py grava). Por isso só roda na primeira vez.

        RLS: no Supabase, tabelas do schema "public" ficam expostas na API pública do projeto.
        RLS ligado sem nenhuma política bloqueia esse acesso. O script conecta como dono das
        tabelas e continua lendo e gravando normalmente.
        """
        existentes = self.con.execute(
            "SELECT count(*) AS n FROM pg_tables WHERE schemaname = current_schema() AND tablename = ANY(%s)",
            (TABELAS,),
        ).fetchone()["n"]
        if existentes < len(TABELAS):
            with self.con.transaction():
                for comando in ESQUEMA_POSTGRES.split(";"):
                    if comando.strip():
                        self.con.execute(comando)
        sem_rls = self.con.execute(
            """SELECT relname FROM pg_class
               WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r'
                 AND relname = ANY(%s) AND NOT relrowsecurity""",
            (TABELAS,),
        ).fetchall()
        for linha in sem_rls:
            self.con.execute(f'ALTER TABLE "{linha["relname"]}" ENABLE ROW LEVEL SECURITY')

    @property
    def onde(self) -> str:
        return "Postgres (nuvem)" if self.postgres else f"SQLite local ({config.CAMINHO_BANCO.name})"

    def _exec(self, sql: str, params: tuple = ()):
        if self.postgres:
            sql = sql.replace("?", "%s")
        return self.con.execute(sql, params)

    @contextmanager
    def _transacao(self):
        """Grava tudo ou nada (as duas tabelas ficam sempre coerentes)."""
        if self.postgres:
            with self.con.transaction():
                yield
        else:
            with self.con:  # sqlite3: commit no fim, rollback se der erro
                yield

    def _json(self) -> str:
        """Placeholder do resultado: JSONB no Postgres, texto no SQLite."""
        return "?::jsonb" if self.postgres else "?"

    def _agora(self):
        agora = datetime.now(UTC)
        return agora if self.postgres else agora.isoformat(timespec="seconds")

    def ja_analisada(self, conversation_id: str, ultima_mensagem_ms: int) -> bool:
        linha = self._exec(
            "SELECT ultima_mensagem_ms FROM analises WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        return bool(linha) and linha["ultima_mensagem_ms"] >= ultima_mensagem_ms

    def mapa_analisadas(self) -> dict[str, tuple[int, str]]:
        """conversation_id -> (última mensagem analisada, modelo), numa consulta só (modo incremental)."""
        linhas = self._exec("SELECT conversation_id, ultima_mensagem_ms, modelo FROM analises").fetchall()
        return {lin["conversation_id"]: (lin["ultima_mensagem_ms"], lin["modelo"]) for lin in linhas}

    def _execmany(self, sql: str, params: list[tuple]) -> None:
        if self.postgres:
            with self.con.cursor() as cur:
                cur.executemany(sql.replace("?", "%s"), params)
        else:
            self.con.executemany(sql, params)

    def salvar_analise(self, conversa: dict, resultado: dict, tokens_in: int, tokens_out: int) -> None:
        self.salvar_lote([(conversa, resultado, tokens_in, tokens_out)], config.OPENAI_MODEL)

    def salvar_lote(self, itens: list[tuple[dict, dict, int, int]], modelo: str) -> None:
        """Grava várias análises numa transação só. itens: (conversa, resultado, tokens_in, tokens_out)."""
        if not itens:
            return
        agora = self._agora()
        linhas_analise, linhas_historico = [], []
        for conversa, resultado, tokens_in, tokens_out in itens:
            resultado_json = json.dumps(resultado, ensure_ascii=False)
            ultima = conversa.get("lastMessageDate") or 0
            linhas_analise.append(
                (
                    conversa["id"],
                    conversa.get("contactId"),
                    conversa.get("fullName") or conversa.get("contactName"),
                    ultima,
                    agora,
                    modelo,
                    tokens_in,
                    tokens_out,
                    resultado_json,
                )
            )
            linhas_historico.append(
                (conversa["id"], conversa.get("contactId"), ultima, agora, resultado_json)
            )
        sql_analise = f"""
            INSERT INTO analises (conversation_id, contact_id, nome_contato, ultima_mensagem_ms,
                                  analisado_em, modelo, tokens_entrada, tokens_saida, resultado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, {self._json()})
            ON CONFLICT (conversation_id) DO UPDATE SET
              contact_id = excluded.contact_id, nome_contato = excluded.nome_contato,
              ultima_mensagem_ms = excluded.ultima_mensagem_ms, analisado_em = excluded.analisado_em,
              modelo = excluded.modelo, tokens_entrada = excluded.tokens_entrada,
              tokens_saida = excluded.tokens_saida, resultado = excluded.resultado"""
        sql_historico = f"""
            INSERT INTO historico (conversation_id, contact_id, ultima_mensagem_ms, analisado_em, resultado)
            VALUES (?, ?, ?, ?, {self._json()})"""
        with self._transacao():
            self._execmany(sql_analise, linhas_analise)
            self._execmany(sql_historico, linhas_historico)

    def ultima_execucao_ms(self) -> int | None:
        linha = self._exec("SELECT inicio_ms FROM execucoes ORDER BY id DESC LIMIT 1").fetchone()
        return linha["inicio_ms"] if linha else None

    def registrar_execucao(self, inicio_ms: int, modo: str, analisadas: int, erros: int) -> None:
        with self._transacao():
            self._exec(
                "INSERT INTO execucoes (inicio_ms, fim, modo, analisadas, erros) VALUES (?, ?, ?, ?, ?)",
                (inicio_ms, self._agora(), modo, analisadas, erros),
            )

    def listar_analises(self, desde_ms: int = 0) -> list[dict]:
        """Situação mais recente de cada conversa, da mais recente para a mais antiga."""
        linhas = self._exec(
            """SELECT conversation_id, contact_id, nome_contato, ultima_mensagem_ms, resultado
               FROM analises WHERE ultima_mensagem_ms >= ? ORDER BY ultima_mensagem_ms DESC""",
            (desde_ms,),
        ).fetchall()
        saida = []
        for linha in linhas:
            d = dict(linha)
            if isinstance(d["resultado"], str):  # SQLite guarda texto; Postgres já devolve dict
                d["resultado"] = json.loads(d["resultado"])
            saida.append(d)
        return saida

    def contagens(self) -> dict[str, int]:
        return {
            t: self._exec(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            for t in ("analises", "historico", "execucoes")
        }

    def fechar(self) -> None:
        self.con.close()


DICAS_ERRO = {
    "password authentication failed": (
        "Senha do banco errada. Redefina em Supabase > Project Settings > Database > "
        "Reset database password e atualize o DATABASE_URL no .env."
    ),
    "Tenant or user not found": (
        "Usuário ou endereço errado. Copie de novo em Connect > Direct > Session pooler."
    ),
    "could not translate host name": (
        "Endereço inválido ou conexão direta. Use o de Connect > Direct > Session pooler."
    ),
    "timeout": "O servidor não respondeu. Confira a internet e se o endereço é o do Session pooler.",
}


def conectar() -> Banco:
    try:
        return Banco()
    except Exception as e:
        if not config.DATABASE_URL:
            raise
        dica = next((d for chave, d in DICAS_ERRO.items() if chave in str(e)), None)
        if dica:
            raise SystemExit(f"Não conectou no Postgres: {dica}") from None
        raise


if __name__ == "__main__":
    banco = conectar()
    print(f"Conectado: {banco.onde}")
    for tabela, n in banco.contagens().items():
        print(f"  {tabela:<10} {n} linhas")
    banco.fechar()
