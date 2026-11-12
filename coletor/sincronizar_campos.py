"""Cria no GHL os campos personalizados definidos em taxonomia.json.

  python -m coletor.sincronizar_campos --seco   # só mostra o que faria
  python -m coletor.sincronizar_campos          # cria os campos que faltam

Campos que já existem não são alterados; se faltar alguma opção na lista suspensa,
o script avisa para você adicionar manualmente no GHL.
"""

import argparse

from coletor import config
from coletor.ghl import GHL


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seco", action="store_true", help="não cria nada, só mostra")
    args = parser.parse_args()

    config.exigir("GHL_TOKEN", "GHL_LOCATION_ID")
    taxonomia = config.carregar_taxonomia()
    ghl = GHL(config.GHL_TOKEN, config.GHL_LOCATION_ID)
    existentes = {c["name"]: c for c in ghl.campos_personalizados()}

    desejados = [
        (c["campo_ghl"], "SINGLE_OPTIONS", [o["valor"] for o in c["opcoes"]]) for c in taxonomia["categorias"]
    ]
    desejados.append((taxonomia["resumo"]["campo_ghl"], "LARGE_TEXT", None))

    for nome, tipo, opcoes in desejados:
        campo = existentes.get(nome)
        if campo:
            atuais = set(campo.get("picklistOptions") or [])
            faltando = [o for o in (opcoes or []) if o not in atuais]
            if faltando:
                print(f"! '{nome}' existe, mas faltam opções (adicione no GHL): {', '.join(faltando)}")
            else:
                print(f"✓ '{nome}' já existe")
            continue
        if args.seco:
            print(f"+ criaria '{nome}' ({tipo}){': ' + ', '.join(opcoes) if opcoes else ''}")
            continue
        ghl.criar_campo(nome, tipo, opcoes)
        print(f"+ criado '{nome}' ({tipo})")


if __name__ == "__main__":
    main()
