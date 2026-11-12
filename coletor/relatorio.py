"""Métricas a partir do histórico (Postgres na nuvem ou dados.db local). Não usa IA, não gasta token.

python -m coletor.relatorio            # tudo que já foi analisado
python -m coletor.relatorio --dias 30  # só conversas com mensagem nos últimos 30 dias
"""

import argparse
import csv
import time
from collections import Counter
from datetime import datetime

from coletor import banco, config


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dias", type=int, help="considerar só os últimos N dias")
    args = parser.parse_args()

    taxonomia = config.carregar_taxonomia()
    db = banco.conectar()
    desde_ms = int(time.time() * 1000) - args.dias * 86_400_000 if args.dias else 0
    linhas = db.listar_analises(desde_ms)
    if not linhas:
        print("Nenhuma análise no período. Rode python -m coletor.main primeiro.")
        return

    resultados = [lin["resultado"] for lin in linhas]
    total = len(resultados)
    print(f"{total} conversas analisadas{f' nos últimos {args.dias} dias' if args.dias else ''}\n")
    for cat in taxonomia["categorias"]:
        print(cat["chave"])
        for valor, n in Counter(r.get(cat["chave"], "?") for r in resultados).most_common():
            print(f"  {valor:<28} {n:>5}  {n / total:6.1%}")
        print()

    pasta = config.RAIZ / "relatorios"
    pasta.mkdir(exist_ok=True)
    caminho = pasta / f"analises_{datetime.now():%Y%m%d_%H%M}.csv"
    chaves = [c["chave"] for c in taxonomia["categorias"]]
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["contato", "contact_id", "ultima_mensagem", *chaves, "resumo"])
        for lin, r in zip(linhas, resultados, strict=True):
            data = datetime.fromtimestamp(lin["ultima_mensagem_ms"] / 1000).strftime("%d/%m/%Y")
            w.writerow(
                [
                    lin["nome_contato"],
                    lin["contact_id"],
                    data,
                    *[r.get(k, "") for k in chaves],
                    r.get("resumo", ""),
                ]
            )
    print(f"CSV completo: {caminho}")


if __name__ == "__main__":
    main()
