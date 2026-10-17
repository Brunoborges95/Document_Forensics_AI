import dataclasses
import json
from pathlib import Path

from pydantic import TypeAdapter

from .catalogo import estruturas

with open(Path(__file__).parent / "prompts" / "extracao.json", encoding='utf-8') as doc:
    data = json.load(doc)


def build_prompt(extraction_type, instrucoes, estrutura, markdown):
    """
    Monta a prompt de extração: regras gerais do tipo de extração, instruções do documento e a
    estrutura, em que a descrição de cada campo diz o que deve ser respondido.
    """
    schema = TypeAdapter(estrutura).json_schema()

    return data[extraction_type]['prompt'].format(
        instrucoes=instrucoes,
        document=markdown,
        estrutura=json.dumps(schema, ensure_ascii=False, indent=2),
    )


def extrair(llm, document_type, documento, catalogo):
    """
    Executa as extrações que o catálogo define para o tipo de documento.
    Retorna {tipo de extração: dados extraídos}.
    """
    definicao = catalogo.get(document_type)
    if definicao is None:
        return {}

    document_information = {}

    for extraction_type, estrutura in estruturas(document_type, definicao).items():
        instrucoes = definicao.get("instrucoes", {}).get(extraction_type, "")
        prompt_ = build_prompt(extraction_type, instrucoes, estrutura, documento.markdown)

        # A extração textual recebe só o markdown; a visual recebe também o próprio arquivo
        file_path = documento.path if extraction_type == "visual" else None

        output = llm.call_claude(prompt_, estrutura, file_path=file_path)
        document_information[extraction_type] = dataclasses.asdict(output)

    return document_information
