"""Monta a pasta publicar/ (o site do dashboard) a partir do histórico no banco.

  python -m coletor.dashboard          # dados reais do banco
  python -m coletor.dashboard --demo   # dados de exemplo, para ver o visual

O código do site fica em dashboard/ (index.html, css/, js/). Este script copia esses
arquivos para publicar/, junto com o logo (marca/) e o arquivo de dados (dados.js).

dados.js leva só as classificações e o dia de cada conversa: nada de nome, telefone
ou resumo. Por isso o site pode ser hospedado e aberto dentro do GHL sem expor os leads.

Fonte: o visual usa a Urbanist (Google Fonts). Para usar a Quantify, coloque o arquivo da
fonte (.woff2, .woff, .otf ou .ttf, com licença para uso em site) na pasta fontes/.
"""

import argparse
import json
import random
import shutil
import time
from datetime import datetime, timedelta, timezone

from coletor import banco, config

PASTA_SITE = config.RAIZ / "dashboard"  # código do site: index.html, css/, js/
PASTA_SAIDA = config.RAIZ / "publicar"  # o que vai para a hospedagem (Vercel)
PASTA_FONTES = config.RAIZ / "fontes"
PASTA_MARCA = config.RAIZ / "marca"  # logo e seta da Matte (PNG com fundo transparente)
DIA_MS = 86_400_000
FUSO_MS = -3 * 3_600_000  # horário de Brasília (sem horário de verão desde 2019)
# Categorias com ordem natural (não reordenar por volume no gráfico)
ORDEM_FIXA = ["porte", "desfecho"]


def dia(ms: int) -> int:
    """Dias desde 1970 no horário de Brasília."""
    return (ms + FUSO_MS) // DIA_MS


def registros_reais(taxonomia: dict) -> list[dict]:
    chaves = [c["chave"] for c in taxonomia["categorias"]]
    db = banco.conectar()
    print(f"Lendo de: {db.onde}")
    return [
        {"t": lin["ultima_mensagem_ms"], **{k: lin["resultado"].get(k, "Não identificado") for k in chaves}}
        for lin in db.listar_analises()
    ]


def registros_demo(taxonomia: dict) -> list[dict]:
    """60 dias com disparos em massa e maioria sem resposta, só para visualizar o layout."""
    rnd = random.Random(42)
    pesos = {
        "origem": [55, 43, 2],
        "segmento": [5, 2, 4, 6, 30, 18, 8, 12, 3, 12],
        "porte": [45, 30, 10, 15],
        "dor_principal": [14, 22, 10, 9, 7, 3, 4, 31],
        "duvida_principal": [14, 12, 4, 3, 3, 1, 63],
        "objecao": [6, 10, 3, 2, 3, 76],
    }
    taxa_reuniao = {
        "Imobiliária": 0.18,
        "Advocacia": 0.12,
        "Clínica": 0.15,
        "High-ticket": 0.2,
        "Distribuidora/Atacado": 0.03,
        "Varejo/Comércio": 0.07,
        "Indústria": 0.06,
        "Serviços": 0.08,
    }
    padrao_sem_resposta = taxonomia.get("sem_resposta", {})
    agora = int(time.time() * 1000)
    disparos = {52: 700, 41: 380, 30: 1500, 23: 260, 9: 2400, 2: 900}  # dias atrás -> volume
    regs = []
    for dias_atras in range(60):
        volume = 25 + rnd.randint(0, 20) + disparos.get(dias_atras, 0)
        taxa_resp = 0.18 if dias_atras in disparos else 0.6
        for _ in range(volume):
            r = {"t": agora - dias_atras * DIA_MS - rnd.randint(0, DIA_MS - 1)}
            if rnd.random() > taxa_resp:
                for cat in taxonomia["categorias"]:
                    r[cat["chave"]] = padrao_sem_resposta.get(cat["chave"], "Não identificado")
                regs.append(r)
                continue
            for cat in taxonomia["categorias"]:
                if cat["chave"] in ("desfecho", "motivo_perda"):
                    continue
                opcoes = [o["valor"] for o in cat["opcoes"]]
                p = pesos.get(cat["chave"])
                r[cat["chave"]] = rnd.choices(opcoes, weights=p if p and len(p) == len(opcoes) else None)[0]
            des = [
                o["valor"]
                for o in next(c for c in taxonomia["categorias"] if c["chave"] == "desfecho")["opcoes"]
            ]
            if rnd.random() < taxa_reuniao.get(r.get("segmento"), 0.05):
                r["desfecho"] = des[0]
            else:
                r["desfecho"] = rnd.choices(des[1:], weights=[8, 22, 35, 35])[0]
            if r["desfecho"] in ("Sem resposta", "Perdido"):
                r["motivo_perda"] = rnd.choices(
                    [
                        "Parou de responder",
                        "Pediu para parar",
                        "Contato errado",
                        "Sem interesse agora",
                        "Fora do perfil",
                    ],
                    weights=[38, 40, 6, 11, 5],
                )[0]
            else:
                r["motivo_perda"] = "Não se aplica"
            regs.append(r)
    return regs


def compactar(taxonomia: dict, registros: list[dict]) -> list[list[int]]:
    """Cada conversa vira [dia, índice da opção de cada categoria]: ~10x menor que o JSON completo."""
    indices = []
    for cat in taxonomia["categorias"]:
        opcoes = [o["valor"] for o in cat["opcoes"]]
        indices.append(
            (
                cat["chave"],
                {v: i for i, v in enumerate(opcoes)},
                opcoes.index("Não identificado") if "Não identificado" in opcoes else 0,
            )
        )
    return [
        [dia(r["t"])] + [mapa.get(r.get(chave), padrao) for chave, mapa, padrao in indices] for r in registros
    ]


def css_fonte() -> str:
    """@font-face da Quantify se houver arquivo em fontes/ (copiado para publicar/fontes/)."""
    tipos = {".woff2": "woff2", ".woff": "woff", ".otf": "opentype", ".ttf": "truetype"}
    if PASTA_FONTES.is_dir():
        for arq in sorted(PASTA_FONTES.iterdir()):
            if arq.suffix.lower() in tipos:
                destino = PASTA_SAIDA / "fontes" / arq.name
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(arq, destino)
                print(f"Fonte incluída: {arq.name}")
                formato = tipos[arq.suffix.lower()]
                return (
                    "@font-face {\n"
                    '  font-family: "Quantify";\n'
                    f'  src: url("../fontes/{arq.name}") format("{formato}");\n'
                    "  font-display: swap;\n"
                    "}\n"
                )
    return "/* sem fonte própria: o visual usa a Urbanist (Google Fonts) */\n"


def montar_site(dados: dict) -> None:
    """Copia o site para publicar/ e grava os dados. vercel.json e outros arquivos são mantidos."""
    for origem in PASTA_SITE.rglob("*"):
        if origem.is_file():
            destino = PASTA_SAIDA / origem.relative_to(PASTA_SITE)
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, destino)
    (PASTA_SAIDA / "img").mkdir(exist_ok=True)
    for imagem in PASTA_MARCA.glob("*.png"):
        shutil.copy2(imagem, PASTA_SAIDA / "img" / imagem.name)
    (PASTA_SAIDA / "css" / "fonte.css").write_text(css_fonte(), encoding="utf-8")
    json_dados = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    (PASTA_SAIDA / "dados.js").write_text(
        f"// Gerado por python -m coletor.dashboard. Não edite à mão.\nwindow.DADOS = {json_dados};\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--demo", action="store_true", help="usar dados de exemplo")
    args = parser.parse_args()

    taxonomia = config.carregar_taxonomia()
    registros = registros_demo(taxonomia) if args.demo else registros_reais(taxonomia)
    if not registros:
        raise SystemExit(
            "Nenhuma análise no banco ainda. Rode python -m coletor.main primeiro (ou use --demo)."
        )

    agora_brasilia = datetime.now(timezone(timedelta(milliseconds=FUSO_MS)))
    dados = {
        "gerado_em": agora_brasilia.strftime("%d/%m/%Y às %H:%M"),
        "demo": args.demo,
        "fuso_ms": FUSO_MS,
        "ordem_fixa": ORDEM_FIXA,
        "categorias": [
            {
                "chave": c["chave"],
                "titulo": c["campo_ghl"].removeprefix("IA - "),
                "opcoes": [o["valor"] for o in c["opcoes"]],
            }
            for c in taxonomia["categorias"]
        ],
        "r": compactar(taxonomia, registros),
    }
    montar_site(dados)
    tamanho = (PASTA_SAIDA / "dados.js").stat().st_size / 1024
    print(f"Dashboard gerado com {len(registros)} conversas (dados: {tamanho:.0f} KB) em {PASTA_SAIDA}")
    print(f"Abra no navegador: {PASTA_SAIDA / 'index.html'}")


if __name__ == "__main__":
    main()
