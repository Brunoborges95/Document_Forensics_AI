import argparse
import json
import logging
import sys
from pathlib import Path

from subscricao.conversao import converter
from subscricao.pipeline import processar


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="POC de subscrição: classifica, extrai e valida os documentos de uma proposta (RG e contrato social).")
    parser.add_argument("documentos", type=Path, nargs="+", help="Imagens ou PDFs dos documentos")
    parser.add_argument("--ficha-cadastro", type=Path, help="JSON com a ficha de cadastro. Sem ela, as validações que a usam ficam aguardando o documento")
    parser.add_argument("--fraude", action="store_true", help="Faz também a análise de fraude de cada documento (orquestrador B)")
    parser.add_argument("--identificadores", action="store_true", help="Busca e confere os identificadores de cada documento (CPF, CNPJ, matrícula, linha digitável, Pix e outros)")
    parser.add_argument("--saida", type=Path, default=Path("saida"), help="Pasta onde os markdowns e o resultado são gravados")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    ficha_cadastro = None
    if args.ficha_cadastro:
        ficha_cadastro = json.loads(args.ficha_cadastro.read_text(encoding="utf-8"))

    args.saida.mkdir(parents=True, exist_ok=True)

    documentos = []
    for path in args.documentos:
        documento = converter(path)
        (args.saida / f"{path.stem}.md").write_text(documento.markdown, encoding="utf-8")
        documentos.append(documento)

    resultado = {"documentos": processar(documentos, ficha_cadastro, fraude=args.fraude, identificadores=args.identificadores)}
    resultado_json = json.dumps(resultado, indent=2, ensure_ascii=False)
    (args.saida / "resultado.json").write_text(resultado_json, encoding="utf-8")

    print(resultado_json)


if __name__ == "__main__":
    main()
