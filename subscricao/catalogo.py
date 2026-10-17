import dataclasses
import json
import keyword
import re
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic.dataclasses import dataclass

from .fraude.configuracao import RISCO_PADRAO, RISCOS
from .fraude.forense.formato import FORMATOS
from .validacoes.ValidateDocument import FICHA_CADASTRO, VALIDACOES, opcoes

# Tipos de documento, com a descrição usada na classificação e os campos extraídos de cada um.
# É o arquivo que o frontend edita
CATALOGO_PATH = Path(__file__).resolve().parent.parent / "catalogo.json"

# textual: a extração recebe o markdown do documento
# visual: a extração recebe o markdown e o próprio arquivo (PDF ou imagem), para análise visual
# de assinaturas, selos, carimbos, marcas d'água etc.
EXTRACOES = ("textual", "visual")

# Nomes que não podem ser usados como tipo de documento
RESERVADOS = (FICHA_CADASTRO, "outro")

# O que se espera do arquivo de um tipo de documento ("arquivo_esperado"), conferido pelas
# validações do arquivo (fraude/forense/validacoes.py). Tudo é opcional: o que não for definido
# não é conferido
#   formatos            formatos em que o documento costuma chegar (os do avaliador forense)
#   programas           trechos do nome dos programas que geram o PDF (Producer ou Creator)
#   assinatura_digital  o documento é emitido com assinatura digital
#   certificados        SHA-256 dos certificados aceitos na assinatura; sem a lista, vale qualquer um
ARQUIVO_ESPERADO = ("formatos", "programas", "assinatura_digital", "certificados")


@dataclass
class Endereco:
    """
    Caso não encontre no documento alguma informação de algum dos campos do Endereço, retorne 'Not Found' no campo não encontrado.
    Os campos devem ser encontrados no documento na seguinte ordem: rua, número, complemento, bairro, cidade e estado.
    """
    cep: str
    rua: str
    numero: str
    complemento: str
    bairro: str
    cidade: str
    estado: str


@dataclass
class CpfSocio:
    nome: str = Field(description="Nome completo do sócio (não incluir títulos como Dr., Dra., etc. como parte do nome)")
    cpf: str = Field(description="CPF do sócio")


# Tipos que um campo do catálogo pode ter
TIPOS = {
    "texto": str,
    "booleano": bool,
    "inteiro": int,
    "endereco": Endereco,
    "lista_nome_cpf": list[CpfSocio],
}


def carregar(path=None):
    with open(path or CATALOGO_PATH, encoding='utf-8') as doc:
        return json.load(doc)


def salvar(catalogo, path=None):
    validar(catalogo)

    with open(path or CATALOGO_PATH, "w", encoding='utf-8', newline="\n") as doc:
        json.dump(catalogo, doc, ensure_ascii=False, indent=4)
        doc.write("\n")


def _identificador(nome):
    return isinstance(nome, str) and nome.isidentifier() and not keyword.iskeyword(nome)


def validar(catalogo):
    """
    Confere se o catálogo pode ser usado na classificação e na extração.
    Levanta ValueError com todos os problemas encontrados.
    """
    problemas = []

    for document_type, definicao in catalogo.items():
        if not _identificador(document_type) or document_type in RESERVADOS:
            problemas.append(f"'{document_type}' não é um nome válido de tipo de documento (use letras, números e _).")
        if not definicao.get("descricao", "").strip():
            problemas.append(f"{document_type}: a descrição é usada na classificação e não pode ficar vazia.")
        if definicao.get("risco", RISCO_PADRAO) not in RISCOS:
            problemas.append(f"{document_type}: nível de risco '{definicao.get('risco')}' desconhecido.")
        problemas += [f"{document_type}: {problema}" for problema in _problemas_do_arquivo_esperado(definicao.get("arquivo_esperado"))]

        nomes = set()
        for campo in definicao.get("campos", []):
            nome = campo.get("nome")
            if not _identificador(nome):
                problemas.append(f"{document_type}: '{nome}' não é um nome válido de campo (use letras, números e _).")
            elif nome in nomes:
                problemas.append(f"{document_type}: o campo '{nome}' está repetido.")
            nomes.add(nome)

            if campo.get("tipo") not in TIPOS:
                problemas.append(f"{document_type}.{nome}: tipo '{campo.get('tipo')}' desconhecido.")
            if campo.get("extracao") not in EXTRACOES:
                problemas.append(f"{document_type}.{nome}: extração '{campo.get('extracao')}' desconhecida.")

    if problemas:
        raise ValueError("\n".join(problemas))


def _problemas_do_arquivo_esperado(esperado):
    if esperado is None:
        return []
    if not isinstance(esperado, dict):
        return ["o arquivo esperado precisa ser um conjunto de opções."]

    problemas = [f"opção '{chave}' desconhecida no arquivo esperado." for chave in esperado if chave not in ARQUIVO_ESPERADO]
    for chave in ("formatos", "programas", "certificados"):
        valores = esperado.get(chave, [])
        if not isinstance(valores, list) or not all(isinstance(valor, str) and valor.strip() for valor in valores):
            problemas.append(f"'{chave}' do arquivo esperado precisa ser uma lista de textos.")
            esperado = {**esperado, chave: []}

    desconhecidos = [formato for formato in esperado.get("formatos", []) if formato not in FORMATOS]
    if desconhecidos:
        problemas.append(f"formato de arquivo desconhecido: {', '.join(desconhecidos)}. Use {', '.join(FORMATOS)}.")
    if not isinstance(esperado.get("assinatura_digital", False), bool):
        problemas.append("'assinatura_digital' do arquivo esperado precisa ser verdadeiro ou falso.")
    if any(not re.fullmatch(r"[0-9a-fA-F]{64}", certificado) for certificado in esperado.get("certificados", [])):
        problemas.append("cada certificado aceito é a impressão digital SHA-256 do certificado: 64 caracteres de 0 a 9 e de a a f.")
    if esperado.get("certificados") and not esperado.get("assinatura_digital"):
        problemas.append("os certificados aceitos só valem quando o tipo espera assinatura digital.")
    return problemas


def estruturas(document_type, definicao):
    """
    Monta, a partir do catálogo, a estrutura (dataclass) de cada extração do documento.
    Retorna {tipo de extração: estrutura}, só com as extrações que têm campos.
    """
    resultado = {}

    for extraction_type in EXTRACOES:
        campos = [
            (campo["nome"], Annotated[TIPOS[campo["tipo"]], Field(description=campo.get("descricao") or None)])
            for campo in definicao["campos"] if campo["extracao"] == extraction_type
        ]
        if campos:
            resultado[extraction_type] = dataclasses.make_dataclass(f"{document_type}_{extraction_type}", campos)

    return resultado


def pendencias(catalogo):
    """
    Lista o que não bate entre as validações (código) e o catálogo (dados): campos que uma
    validação espera e o catálogo não extrai, e validações cujo tipo (textual ou visual) não
    corresponde à extração de onde vêm seus campos.
    """
    resultado = []
    vistas = set()

    for document_type, validations in VALIDACOES.items():
        for validation in validations.values():
            # a validação com condição OU está registrada em cada tipo: é conferida uma vez
            if id(validation) in vistas:
                continue
            vistas.add(id(validation))
            pertence = " ou ".join(getattr(validation, "pertence", (document_type,)))
            usa_campo_visual = False

            for chave, campos in validation.campos.items():
                for documento in opcoes(chave):
                    if documento == FICHA_CADASTRO:
                        continue
                    extraidos = {campo["nome"]: campo["extracao"] for campo in catalogo.get(documento, {}).get("campos", [])}
                    ausentes = [campo for campo in campos if campo not in extraidos]
                    if ausentes:
                        resultado.append(f"{validation.__name__} ({pertence}) espera {ausentes} do documento '{documento}'.")
                    usa_campo_visual = usa_campo_visual or any(extraidos.get(campo) == "visual" for campo in campos)

            if usa_campo_visual and validation.tipo != "visual":
                resultado.append(f"{validation.__name__} ({pertence}) usa campos da extração visual, mas está marcada como '{validation.tipo}'.")
            if validation.tipo == "visual" and not usa_campo_visual:
                resultado.append(f"{validation.__name__} ({pertence}) está marcada como 'visual', mas não usa campos da extração visual.")

    return resultado
