import inspect
import logging
from functools import wraps
from enum import Enum
import traceback
from collections import defaultdict
from types import SimpleNamespace
from .tools import DataNotFoundError, InvalidDateError, ValidationResultNormalizer

validation_result_normalizer = ValidationResultNormalizer()

logger = logging.getLogger(__name__)

class ValidationResultCode(Enum):
    NAO_ENCONTRADO = 404
    INCORRETO = 400
    INVALIDO = 422
    ESPERAR_DOCUMENTOS = 409
    ERRO_INTERNO = 500
    SERVICO_INDISPONIVEL = 503
    OK = 200

# A ficha de cadastro (cartão proposta na referência) é um documento como os outros para as
# validações. A diferença é que chega pronta em JSON, sem passar pela extração
FICHA_CADASTRO = "ficha_cadastro"

# Tipos de validação: a textual usa só campos da extração textual; a visual usa campos da
# extração visual (assinaturas, selos, carimbos etc.). A análise de fraude não é uma validação:
# vem do orquestrador, em subscricao/fraude
TIPOS = ("textual", "visual")

# document_type -> {nome: validação}, registradas pelo decorator @validacao
VALIDACOES = defaultdict(dict)

# document_type -> ajuste da ficha de cadastro registrado pelo decorator @prepara_ficha_cadastro
PREPARA_FICHA_CADASTRO = {}

def check_error(campo, valid):
    if valid:
        return ValidationResultCode.OK
    if campo is not None:
        if (not isinstance(campo, dict) and isinstance(campo, str) and campo.upper() == "NOT FOUND"):
            return ValidationResultCode.NAO_ENCONTRADO
        else:
            return ValidationResultCode.INCORRETO
    else:
        return ValidationResultCode.INCORRETO


def opcoes(documento):
    """
    Os tipos de documento de uma entrada do decorator: um tipo só, ou uma tupla de tipos que se
    lê como OU ("certidao_casamento" ou "escritura_uniao_estavel").
    """
    return tuple(documento) if isinstance(documento, tuple) else (documento,)


def descreve(documento):
    return " ou ".join(opcoes(documento))


def validacao(document_type, campos: dict, tipo: str = 'textual'):
    """
    Marca uma função como validação de um tipo de documento.

    - document_type: documento ao qual a validação pertence. Uma tupla de tipos é uma condição OU:
      a validação pertence a qualquer um deles e roda para cada documento desses tipos na proposta
    - campos: {documento: [campos]} com todos os documentos de que a validação precisa e os campos
      esperados de cada um. Além do próprio documento, pode incluir a ficha de cadastro e outros
      documentos. A função recebe um argumento por documento, com o nome dele, contendo apenas os
      campos declarados. Uma tupla de tipos como chave também é OU: basta um deles na proposta, e
      os que faltam chegam à função como None
    - tipo: 'textual' ou 'visual'
    """
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de validação inválido: '{tipo}'. Use um de {TIPOS}.")

    def validation_decorator(func):
        parametros = inspect.signature(func).parameters
        recebe_qualquer = any(parametro.kind is inspect.Parameter.VAR_KEYWORD for parametro in parametros.values())
        nao_recebidos = [documento for chave in campos for documento in opcoes(chave) if documento not in parametros and not recebe_qualquer]
        if nao_recebidos:
            raise TypeError(f"{func.__name__} declara os documentos {nao_recebidos}, mas não os recebe como parâmetro.")
        for documento in opcoes(document_type):
            if func.__name__ in VALIDACOES[documento]:
                raise ValueError(f"Já existe uma validação '{func.__name__}' para o documento '{documento}'.")

        @wraps(func)
        def wrapper(**documentos):
            name_fn = func.__name__
            val_name_fn = name_fn[name_fn.find('_')+1:]
            result = None
            error_key_name = 'regras_subscricao_errors'

            try:
                result = func(**documentos)

            except DataNotFoundError:
                logger.info("Data não encontrada — LLM não encontrou a data no documento.")
                result = {
                    "valid": False,
                    "percent_match": 0,
                    "trecho_encontrado": "",
                    error_key_name: ValidationResultCode.NAO_ENCONTRADO.value
                }

            except InvalidDateError as e:
                logger.info("Data inexistente ou inválida.")
                result = {
                    "valid": False,
                    "percent_match": 0,
                    "trecho_encontrado": str(e.value),
                    error_key_name: ValidationResultCode.INCORRETO.value
                }

            except Exception as e:
                logger.exception(f"Erro não mapeado encontrado durante a validação {val_name_fn}: {e}")
                result = {
                    "valid": False,
                    "percent_match": 0,
                    "trecho_encontrado": "",
                    error_key_name: ValidationResultCode.ERRO_INTERNO.value
                }

            if not isinstance(result, dict):
                logger.info(f"Necessário fornecer como output um payload válido para '{name_fn}'.")
                return None

            # Por padrão, o trecho procurado vem da ficha de cadastro e o encontrado, do próprio
            # documento: com a condição OU, o tipo que está sendo validado
            proprio = next((documentos[documento] for documento in opcoes(document_type) if documentos.get(documento) is not None), None)
            valid = result.get('valid')
            target = result.get('target', val_name_fn)
            trecho_procurado = result.get('trecho_procurado', getattr(documentos.get(FICHA_CADASTRO), target, None))
            trecho_encontrado = result.get('trecho_encontrado', getattr(proprio, target, None))
            score = max(0, float(result.get('percent_match', 100)))
            errorcode = result.get(error_key_name, check_error(trecho_encontrado, valid).value)

            return {
                "valid": valid,
                "target": target,
                "trecho_procurado": validation_result_normalizer.normalize(trecho_procurado),
                "trecho_encontrado": validation_result_normalizer.normalize(trecho_encontrado),
                "percent_match": score,
                error_key_name: ValidationResultCode(errorcode).name
            }

        # Marcar atributos e registrar a validação para o documento (para cada um, na condição OU)
        setattr(wrapper, 'campos', campos)
        setattr(wrapper, 'tipo', tipo)
        setattr(wrapper, 'pertence', opcoes(document_type))
        for documento in opcoes(document_type):
            VALIDACOES[documento][func.__name__] = wrapper
        return wrapper

    return validation_decorator


def prepara_ficha_cadastro(document_type: str):
    """
    Marca a função que ajusta a ficha de cadastro para as validações de um tipo de documento.
    """
    def decorator(func):
        PREPARA_FICHA_CADASTRO[document_type] = func
        return func

    return decorator


def validate(document_type: str, documentos: dict) -> dict:
    """
    Executa as validações do documento. `documentos` reúne, por tipo, os campos de todos os
    documentos disponíveis, incluindo a ficha de cadastro. Cada validação recebe apenas os
    documentos e os campos que declarou.
    """
    documentos = dict(documentos)
    if document_type in PREPARA_FICHA_CADASTRO and FICHA_CADASTRO in documentos:
        documentos[FICHA_CADASTRO] = PREPARA_FICHA_CADASTRO[document_type](dict(documentos[FICHA_CADASTRO]))

    validations = {}

    for validation in VALIDACOES.get(document_type, {}).values():
        method_name = validation.__name__
        error_key = "regras_subscricao_errors"

        # Na entrada com condição OU, basta um dos documentos. Na que contém o documento validado,
        # vale só ele: a validação roda uma vez para cada documento a que pertence
        presentes = {}
        for chave in validation.campos:
            if document_type in opcoes(chave):
                presentes[chave] = [document_type] if document_type in documentos else []
            else:
                presentes[chave] = [documento for documento in opcoes(chave) if documento in documentos]
        documentos_ausentes = [descreve(chave) for chave, encontrados in presentes.items() if not encontrados]

        if documentos_ausentes:
            logger.info(f'[INFO] {documentos_ausentes} não disponível ainda para {method_name}.')
            result = {
                "valid": False,
                "target": method_name.replace("validacao_", ""),
                "trecho_procurado": "",
                "trecho_encontrado": documentos_ausentes,
                "percent_match": 0,
                error_key: ValidationResultCode.ESPERAR_DOCUMENTOS.name
            }
        else:
            try:
                recebidos = {}
                for chave, campos in validation.campos.items():
                    for documento in opcoes(chave):
                        if documento not in presentes[chave]:
                            recebidos[documento] = None
                            continue
                        campos_ausentes = [campo for campo in campos if campo not in documentos[documento]]
                        if campos_ausentes:
                            raise KeyError(f"Campos ausentes no documento '{documento}': {campos_ausentes}")

                        recebidos[documento] = SimpleNamespace(**{campo: documentos[documento][campo] for campo in campos})

                result = validation(**recebidos)
            except Exception as e:
                logger.error(f"Erro na validação: {method_name}")
                logger.error(traceback.format_exc())

                result = {
                    "valid": False,
                    "target": method_name.replace("validacao_", ""),
                    "trecho_procurado": '',
                    "trecho_encontrado": '',
                    "percent_match": 0,
                    error_key: ValidationResultCode.ERRO_INTERNO.name
                }

        if isinstance(result, dict):
            result["tipo"] = validation.tipo

        validations[method_name] = result

    return {"subscription_validations": validations}
