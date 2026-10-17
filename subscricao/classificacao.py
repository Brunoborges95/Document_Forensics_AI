import dataclasses
import json
from pathlib import Path
from typing import Literal

OUTRO = "outro"

with open(Path(__file__).parent / "prompts" / "classificacao.json", encoding='utf-8') as doc:
    data = json.load(doc)


def classificar(llm, markdown, catalogo):
    """
    Classifica o documento (em markdown) em um dos tipos do catálogo ou 'outro'.
    Retorna {'document_type': ..., 'justificativa': ...}.
    """
    tipos = "\n".join(f"- {document_type}: {definicao['descricao']}" for document_type, definicao in catalogo.items())
    prompt_ = data['prompt'].format(tipos=tipos, document=markdown)

    # A estrutura da resposta restringe o tipo aos documentos do catálogo
    Classificacao = dataclasses.make_dataclass("Classificacao", [
        ("document_type", Literal[(*catalogo, OUTRO)]),
        ("justificativa", str),
    ])

    output = llm.call_claude(prompt_, Classificacao)
    return dataclasses.asdict(output)
