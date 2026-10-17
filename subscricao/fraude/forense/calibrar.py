"""
Gera calibracao.json a partir de uma pasta de documentos autênticos. Com --fraudes, mede também o
desempenho em cada sensibilidade (0 a 10) e indica a melhor.

    python -m subscricao.fraude.forense.calibrar PASTA_DE_AUTENTICOS [--fraudes PASTA] [--paginas 3] [--processos 6]
    python -m subscricao.fraude.forense.calibrar --de-medidas medidas.json

Medir leva alguns segundos por página. Com --medidas as medidas brutas ficam gravadas, e com
--de-medidas a calibração é refeita a partir delas, sem medir de novo.

O alarme falso é medido em validação cruzada: metade dos autênticos calibra, a outra metade é
avaliada, e depois se inverte. A calibração gravada usa todos os autênticos.
"""
import argparse
import json
import os
import random
from multiprocessing import Pool
from pathlib import Path

from . import calibracao as calibragem
from .avaliador import ALARME_FALSO, BAIXO, NAO_ANALISAVEL, avaliar, medir_documento

EXTENSOES = (".pdf", ".png", ".jpg", ".jpeg", ".jfif")


def _mede(item):
    path, max_paginas = item
    try:
        return {"arquivo": str(path), "paginas": medir_documento(path, max_paginas)}
    except Exception as e:
        return {"arquivo": str(path), "erro": f"{type(e).__name__}: {e}"}


def medir_pasta(pasta, max_paginas, processos):
    arquivos = sorted(p for p in Path(pasta).rglob("*") if p.is_file() and p.suffix.lower() in EXTENSOES)
    # vários processos dividindo a GPU não rendem mais que a CPU e caem juntos se ela falhar
    os.environ["FORENSE_GPU"] = "0"
    with Pool(processos) as pool:
        medidas = pool.map(_mede, [(path, max_paginas) for path in arquivos], chunksize=2)
    erros = [medida for medida in medidas if "erro" in medida]
    for medida in erros[:10]:
        print("ERRO", medida["arquivo"], medida["erro"])
    return [medida for medida in medidas if "erro" not in medida]


def _paginas(documentos):
    return [pagina for documento in documentos for pagina in documento["paginas"]]


def _sinalizados(documentos, calibracao, sensibilidade):
    """Fração dos documentos analisáveis que recebem MODERADO ou ALTO."""
    niveis = [avaliar(documento["paginas"], sensibilidade, calibracao)["nivel"] for documento in documentos]
    analisaveis = [nivel for nivel in niveis if nivel != NAO_ANALISAVEL]
    return sum(nivel != BAIXO for nivel in analisaveis) / max(len(analisaveis), 1), len(analisaveis)


def desempenho(autenticos, fraudes):
    """
    Alarme falso e detecção em cada sensibilidade, em validação cruzada de duas metades, e a
    sensibilidade que mais separa fraudes de autênticos (maior detecção menos alarme falso).
    """
    embaralhados = autenticos[:]
    random.Random(7).shuffle(embaralhados)
    metades = (embaralhados[::2], embaralhados[1::2])

    tabela = []
    for sensibilidade in range(len(ALARME_FALSO)):
        alarmes, deteccoes = [], []
        for treino, teste in (metades, metades[::-1]):
            calibracao = calibragem.montar(_paginas(treino))
            alarmes.append(_sinalizados(teste, calibracao, sensibilidade)[0])
            deteccoes.append(_sinalizados(fraudes, calibracao, sensibilidade)[0])
        tabela.append({"sensibilidade": sensibilidade, "alarme_falso_nominal": ALARME_FALSO[sensibilidade],
                       "alarme_falso_medido": round(sum(alarmes) / 2, 4), "deteccao": round(sum(deteccoes) / 2, 4)})
    melhor = max(tabela, key=lambda linha: linha["deteccao"] - linha["alarme_falso_medido"])
    return tabela, melhor["sensibilidade"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("autenticos", nargs="?", help="pasta com documentos autênticos (PDF e imagens, com subpastas)")
    parser.add_argument("--de-medidas", help="refaz a calibração a partir de medidas gravadas com --medidas")
    parser.add_argument("--fraudes", help="pasta com documentos fraudados, para medir o desempenho")
    parser.add_argument("--paginas", type=int, default=3, help="páginas medidas por documento")
    parser.add_argument("--processos", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    parser.add_argument("--saida", default=str(calibragem.CALIBRACAO_PATH))
    parser.add_argument("--medidas", help="grava as medidas brutas neste JSON")
    args = parser.parse_args()

    if args.de_medidas:
        gravadas = json.loads(Path(args.de_medidas).read_text(encoding="utf-8"))
        autenticos, fraudes = gravadas["autenticos"], gravadas["fraudes"]
    elif args.autenticos:
        autenticos = medir_pasta(args.autenticos, args.paginas, args.processos)
        fraudes = medir_pasta(args.fraudes, args.paginas, args.processos) if args.fraudes else []
    else:
        parser.error("informe a pasta de autênticos ou --de-medidas")
    calibracao = calibragem.montar(_paginas(autenticos))
    calibracao["origem"] = {"documentos": len(autenticos), "paginas_por_documento": args.paginas}
    print(f"autênticos: {len(autenticos)} documentos | páginas por formato:",
          {formato: referencia["paginas"] for formato, referencia in calibracao["formatos"].items()})

    if fraudes:
        tabela, melhor = desempenho(autenticos, fraudes)
        calibracao["desempenho"], calibracao["sensibilidade_recomendada"] = tabela, melhor
        print(f"fraudes: {len(fraudes)} documentos")
        print("sensibilidade | alarme falso nominal | alarme falso medido | detecção")
        for linha in tabela:
            marca = "  <- melhor" if linha["sensibilidade"] == melhor else ""
            print(f"{linha['sensibilidade']:13} | {linha['alarme_falso_nominal']:20.1%} | {linha['alarme_falso_medido']:19.1%} | {linha['deteccao']:8.1%}{marca}")

    calibragem.salvar(calibracao, args.saida)
    print("calibração gravada em", args.saida)
    if args.medidas and not args.de_medidas:
        Path(args.medidas).write_text(json.dumps({"autenticos": autenticos, "fraudes": fraudes}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
