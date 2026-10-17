import logging

from . import catalogo as catalogo_
from .classificacao import OUTRO, classificar
from .extracao import extrair
from .fraude import configuracao as fraude_
from .fraude.analise import analisar_fraude
from .identificadores import verificar_documento
from .llm import LLM
from .validacoes import FICHA_CADASTRO, validate

logger = logging.getLogger(__name__)


def extrair_documentos(documentos, catalogo=None):
    """
    Classifica cada documento convertido e extrai as informações dos tipos reconhecidos.
    Retorna um resultado por documento.
    """
    if catalogo is None:
        catalogo = catalogo_.carregar()

    llm = LLM()
    resultados = []

    for documento in documentos:
        classificacao = classificar(llm, documento.markdown, catalogo)
        document_type = classificacao['document_type']
        logger.info(f"{documento.path.name} classificado como '{document_type}'")

        resultado = {
            "arquivo": documento.path.name,
            "document_type": document_type,
            "classificacao": classificacao,
        }

        if document_type != OUTRO:
            resultado["document_information"] = extrair(llm, document_type, documento, catalogo)

        resultados.append(resultado)

    return resultados


def campos_extraidos(resultado):
    # As validações não dependem de qual extração produziu cada campo
    campos = {}
    for output in resultado["document_information"].values():
        campos.update(output)

    return campos


def validar_documentos(resultados, ficha_cadastro=None):
    """
    Executa as validações de cada documento extraído. Elas enxergam a ficha de cadastro (JSON) e
    todos os documentos da proposta. Não chama a LLM, então pode ser repetida à vontade.
    """
    extraidos = [resultado for resultado in resultados if "document_information" in resultado]

    # Campos de cada documento disponível para as validações, por tipo de documento
    disponiveis = {}
    if ficha_cadastro is not None:
        disponiveis[FICHA_CADASTRO] = ficha_cadastro

    for resultado in extraidos:
        # Se houver mais de um arquivo do mesmo tipo, os outros documentos enxergam o primeiro
        disponiveis.setdefault(resultado["document_type"], campos_extraidos(resultado))

    for resultado in extraidos:
        document_type = resultado["document_type"]
        documentos = {**disponiveis, document_type: campos_extraidos(resultado)}
        resultado["dados_regras_subscricao"] = validate(document_type, documentos)

    return resultados


def analisar_fraude_documentos(resultados, documentos, catalogo=None, config=None):
    """
    Análise de fraude de cada documento classificado em um tipo do catálogo: avaliadores
    auxiliares e orquestrador, conforme o nível de risco do tipo. `documentos` são os documentos
    convertidos, na mesma ordem de `resultados`.
    """
    if catalogo is None:
        catalogo = catalogo_.carregar()
    if config is None:
        config = fraude_.carregar()

    llm = LLM()

    for resultado, documento in zip(resultados, documentos):
        if resultado["document_type"] in catalogo:
            resultado["fraude"] = analisar_fraude(llm, documento, resultado["document_type"], catalogo, config)

    return resultados


def verificar_identificadores_documentos(resultados, documentos, catalogo=None, config=None, contexto=None):
    """
    Busca e confere os identificadores (CPF, CNPJ, matrícula, linha digitável, Pix e outros) de
    cada documento classificado em um tipo do catálogo. `contexto` são as informações de que os
    verificadores podem precisar, pelo nome do parâmetro; as consultas externas seguem a
    configuração. `documentos` são os documentos convertidos, na mesma ordem de `resultados`.
    """
    if catalogo is None:
        catalogo = catalogo_.carregar()
    if config is None:
        config = fraude_.carregar()

    opcoes = fraude_.identificadores(config)
    contexto = {"dominios_pix": opcoes["dominios_pix"], **(contexto or {})}
    llm = LLM()

    for resultado, documento in zip(resultados, documentos):
        if resultado["document_type"] in catalogo:
            resultado["identificadores"] = verificar_documento(llm, documento, contexto, opcoes["consultas_externas"])

    return resultados


def processar(documentos, ficha_cadastro=None, catalogo=None, fraude=False, identificadores=False):
    """
    Classifica, extrai e valida os documentos de uma proposta. Com `fraude`, faz também a
    análise de fraude de cada documento; com `identificadores`, a verificação dos identificadores.
    """
    resultados = validar_documentos(extrair_documentos(documentos, catalogo), ficha_cadastro)

    if identificadores:
        verificar_identificadores_documentos(resultados, documentos, catalogo)
    if fraude:
        analisar_fraude_documentos(resultados, documentos, catalogo)

    return resultados
