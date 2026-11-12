"""Cliente mínimo da API v2 do GHL (LeadConnector).

Endpoints usados (conferidos nas specs oficiais em github.com/GoHighLevel/highlevel-api-docs):
  GET  /conversations/search                     conversations.readonly
  GET  /conversations/{id}/messages              conversations/message.readonly
  GET  /contacts/{id}                            contacts.readonly
  PUT  /contacts/{id}                            contacts.write
  POST/DELETE /contacts/{id}/tags                contacts.write
  GET/POST /locations/{id}/customFields          locations/customFields.*
"""

import time

import requests

BASE_URL = "https://services.leadconnectorhq.com"
VERSAO_CONVERSAS = "2021-04-15"
VERSAO_PADRAO = "2021-07-28"


class ErroGHL(Exception):
    pass


class GHL:
    def __init__(self, token: str, location_id: str):
        self.location_id = location_id
        self.sessao = requests.Session()
        self.sessao.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
        )

    def _req(self, metodo: str, caminho: str, versao: str = VERSAO_PADRAO, **kwargs) -> dict:
        """Requisição com nova tentativa em 429 (limite: 100 req / 10 s) e erros 5xx."""
        url = BASE_URL + caminho
        for tentativa in range(5):
            resp = self.sessao.request(metodo, url, headers={"Version": versao}, timeout=60, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                espera = float(resp.headers.get("Retry-After") or 2**tentativa)
                time.sleep(espera)
                continue
            if not resp.ok:
                raise ErroGHL(f"{metodo} {caminho} -> {resp.status_code}: {resp.text[:300]}")
            return resp.json() if resp.content else {}
        raise ErroGHL(f"{metodo} {caminho} falhou após várias tentativas (limite de requisições)")

    # ---------- Conversas ----------

    def conversas_desde(self, desde_ms: int):
        """Gera conversas com última mensagem a partir de `desde_ms`, da mais recente para a mais antiga."""
        params = {
            "locationId": self.location_id,
            "sortBy": "last_message_date",
            "sort": "desc",
            "limit": 100,
        }
        while True:
            dados = self._req("GET", "/conversations/search", VERSAO_CONVERSAS, params=params)
            conversas = dados.get("conversations", [])
            if not conversas:
                return
            for c in conversas:
                if (c.get("lastMessageDate") or 0) < desde_ms:
                    return
                yield c
            ultima = conversas[-1]
            cursor = (ultima.get("sort") or [None])[0] or ultima.get("lastMessageDate")
            if not cursor or len(conversas) < params["limit"]:
                return
            params["startAfterDate"] = cursor

    def mensagens(self, conversation_id: str, maximo: int) -> tuple[list[dict], bool]:
        """Até `maximo` mensagens mais recentes, em ordem cronológica.

        Retorna (mensagens, truncada). truncada=True quando a conversa tem mais mensagens que
        `maximo`: o começo ficou de fora (importa para saber quem iniciou o contato).
        """
        coletadas: list[dict] = []
        params: dict = {"limit": 100}
        tem_mais = False
        while len(coletadas) < maximo:
            dados = self._req(
                "GET", f"/conversations/{conversation_id}/messages", VERSAO_CONVERSAS, params=params
            )
            # A API devolve {"messages": {"messages": [...], "nextPage": ..., "lastMessageId": ...}}
            bloco = dados.get("messages", dados)
            if isinstance(bloco, list):
                bloco = {"messages": bloco}
            lote = bloco.get("messages", [])
            coletadas.extend(lote)
            tem_mais = bool(bloco.get("nextPage") and bloco.get("lastMessageId") and lote)
            if not tem_mais:
                break
            params["lastMessageId"] = bloco["lastMessageId"]
        coletadas.sort(key=lambda m: m.get("dateAdded") or "")
        return coletadas[-maximo:], tem_mais or len(coletadas) > maximo

    # ---------- Contatos ----------

    def contato(self, contact_id: str) -> dict:
        return self._req("GET", f"/contacts/{contact_id}").get("contact", {})

    def atualizar_campos(self, contact_id: str, campos: list[dict]) -> None:
        """campos: [{"id": <id do campo>, "field_value": <valor>}]"""
        self._req("PUT", f"/contacts/{contact_id}", json={"customFields": campos})

    def adicionar_tags(self, contact_id: str, tags: list[str]) -> None:
        if tags:
            self._req("POST", f"/contacts/{contact_id}/tags", json={"tags": tags})

    def remover_tags(self, contact_id: str, tags: list[str]) -> None:
        if tags:
            self._req("DELETE", f"/contacts/{contact_id}/tags", json={"tags": tags})

    # ---------- Campos personalizados ----------

    def campos_personalizados(self) -> list[dict]:
        dados = self._req("GET", f"/locations/{self.location_id}/customFields", params={"model": "contact"})
        return dados.get("customFields", [])

    def criar_campo(self, nome: str, tipo: str, opcoes: list[str] | None = None) -> dict:
        corpo: dict = {"name": nome, "dataType": tipo, "model": "contact"}
        if opcoes:
            corpo["options"] = opcoes
        return self._req("POST", f"/locations/{self.location_id}/customFields", json=corpo)
