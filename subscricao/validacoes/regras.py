"""
Regras prontas para os padrões de validação mais comuns. Cada chamada registra uma validação com
o nome validacao_<campo>, como se fosse uma função @validacao escrita à mão:

    similaridade("cnh", "nome", limiar=90)
    igualdade("cnh", "cpf")

Regras com lógica própria continuam sendo funções com @validacao.
"""
import re
import datetime
from dateutil.relativedelta import relativedelta
from .ValidateDocument import FICHA_CADASTRO, validacao
from .tools import safe_strptime, str2bool
from .Distances import distances


def _registrar(document_type, campo, campos, tipo, regra):
    regra.__name__ = regra.__qualname__ = f"validacao_{campo}"
    return validacao(document_type, campos=campos, tipo=tipo)(regra)


def similaridade(document_type, campo, limiar=90, tipo='textual'):
    """
    O campo do documento deve ser parecido com o mesmo campo da ficha de cadastro (nomes, razão
    social). `limiar` é a similaridade mínima, de 0 a 100.
    """
    def regra(**documentos):
        s1 = getattr(documentos[FICHA_CADASTRO], campo)
        s2 = getattr(documentos[document_type], campo)

        sim_score = distances(s1.upper(), s2.upper()).norm_score()
        is_valid = sim_score >= limiar
        return {'valid': is_valid, 'percent_match': sim_score}

    return _registrar(document_type, campo, {FICHA_CADASTRO: [campo], document_type: [campo]}, tipo, regra)


def igualdade(document_type, campo, caracteres=r'\d', tipo='textual'):
    """
    O campo do documento deve ser igual ao mesmo campo da ficha de cadastro, comparando só os
    caracteres que casam com `caracteres`: dígitos por padrão (CPF); r'[a-zA-Z0-9]' para CNPJ.
    """
    def regra(**documentos):
        s1 = ''.join(re.findall(caracteres, getattr(documentos[FICHA_CADASTRO], campo)))
        s2 = ''.join(re.findall(caracteres, getattr(documentos[document_type], campo)))
        is_valid = s1 == s2
        return {'valid': is_valid, 'percent_match': 100 if is_valid else 0}

    return _registrar(document_type, campo, {FICHA_CADASTRO: [campo], document_type: [campo]}, tipo, regra)


def data_igual(document_type, campo, tipo='textual'):
    """
    A data do documento (DD-MM-YYYY) deve ser a mesma da ficha de cadastro (DD/MM/YYYY).
    """
    def regra(**documentos):
        date_1 = safe_strptime(getattr(documentos[FICHA_CADASTRO], campo), '%d/%m/%Y')
        s2 = getattr(documentos[document_type], campo)

        if(s2 == 'Not Found'):
            return {'valid': False, 'percent_match': 0}

        date_2 = safe_strptime(s2, '%d-%m-%Y')

        is_valid = date_1 == date_2
        return {'valid': is_valid, 'percent_match': 100 if is_valid else 0}

    return _registrar(document_type, campo, {FICHA_CADASTRO: [campo], document_type: [campo]}, tipo, regra)


def data_recente(document_type, campo, anos, tipo='textual'):
    """
    A data do documento (DD-MM-YYYY) deve ter no máximo `anos` anos.
    """
    def regra(**documentos):
        now = datetime.datetime.now().date()
        extracted_date = getattr(documentos[document_type], campo)

        if(extracted_date == 'Not Found'):
            return {'valid': False, 'percent_match': 0}

        extracted_dispatch_date = safe_strptime(extracted_date, "%d-%m-%Y").date()

        is_valid = extracted_dispatch_date >= (now - relativedelta(years=anos))
        return {'valid': is_valid, 'percent_match': 100 if is_valid else 0}

    return _registrar(document_type, campo, {document_type: [campo]}, tipo, regra)


def booleano(document_type, campo, confianca, descricao, esperado=True, tipo='visual'):
    """
    O campo booleano do documento deve ter o valor `esperado`. É o padrão das respostas da análise
    visual, que vêm com um campo de confiança e outro de descrição: `confianca` vira o
    percent_match e `descricao` vira o trecho encontrado.
    """
    def regra(**documentos):
        documento = documentos[document_type]
        is_valid = str2bool(getattr(documento, campo)) == esperado
        return {
            "valid": is_valid,
            "percent_match": getattr(documento, confianca) if is_valid else 0,
            "trecho_procurado": "",
            "trecho_encontrado": f'{getattr(documento, descricao)}'
        }

    return _registrar(document_type, campo, {document_type: [campo, confianca, descricao]}, tipo, regra)
