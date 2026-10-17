import re
import datetime
from dateutil.relativedelta import relativedelta
from .ValidateDocument import prepara_ficha_cadastro, validacao
from .tools import safe_strptime
from .Distances import distances


@prepara_ficha_cadastro("rg")
def prepara_ficha_cadastro_rg(ficha_cadastro):

    ficha_cadastro["nome"] = ficha_cadastro["nome_responsavel"] if "nome_responsavel" in ficha_cadastro else ficha_cadastro.get("nome")
    ficha_cadastro["cpf"] = ficha_cadastro["cpf_responsavel"] if "cpf_responsavel" in ficha_cadastro else ficha_cadastro.get("cpf")
    ficha_cadastro["responsavel_legal"] = "nome_responsavel" in ficha_cadastro

    return ficha_cadastro

@validacao("rg", campos={"ficha_cadastro": ["nome"], "rg": ["nome"]})
def validacao_nome(ficha_cadastro, rg, limiar=90):
    """
    Valida se o nome extraído do cartao_proposta corresponde ao nome extraído dos dados, com base na similaridade.

    Lógica de Retorno:
        - TRUE: Se a similaridade for maior ou igual ao limiar especificado, a validação é considerada válida;
        - FALSE: Caso contrário.

    Parâmetros:
    limiar (int, opcional): O valor mínimo de similaridade (entre 0 e 100) para considerar a validação válida. 
                            O valor padrão é 95.
    """
    s1 = ficha_cadastro.nome
    s2 = rg.nome

    sim_score = distances(s1.upper(), s2.upper()).norm_score()
    is_valid = sim_score >= limiar
    return {'valid': is_valid, 'percent_match': sim_score}

@validacao("rg", campos={"ficha_cadastro": ["cpf"], "rg": ["cpf"]})
def validacao_cpf(ficha_cadastro, rg):
    """
    Valida se o CPF extraído do cartao_proposta corresponde ao CPF extraído dos dados.

    Lógica de Retorno:
    - TRUE: Se os CPFs forem iguais;
    - FALSE: Caso contrário.
    """
    s1 = ''.join(re.findall(r'\d+', ficha_cadastro.cpf))
    s2 = ''.join(re.findall(r'\d+', rg.cpf))
    is_valid = s1 == s2
    return {'valid': is_valid, 'percent_match': 100 if is_valid else 0}

@validacao("rg", campos={"ficha_cadastro": ["nome_mae", "responsavel_legal"], "rg": ["nome_mae"]})
def validacao_nome_mae(ficha_cadastro, rg, limiar=90):
    """
    Valida se o nome da mãe extraído do cartao_proposta corresponde ao nome da mãe extraído dos dados, com base na similaridade.

    Lógica de Retorno:
    - TRUE: Se a similaridade for maior ou igual ao limiar especificado, a validação é considerada válida;
    - FALSE: Caso contrário.

    Parâmetros:
    limiar (int, opcional): O valor mínimo de similaridade (entre 0 e 100) para considerar a validação válida. 
                            O valor padrão é 95.
    """
        
    s1 = ficha_cadastro.nome_mae
    s2 = rg.nome_mae

    responsavel_legal = ficha_cadastro.responsavel_legal
    
    if(responsavel_legal and len(s1.strip()) == 0):
        return {'valid': True, 'percent_match': 100, 
        'trecho_procurado': 'Validação não aplicável ao documento do representante legal',
        'trecho_encontrado': 'Validação não aplicável ao documento do representante legal'}

    sim_score = distances(s1.upper(), s2.upper()).norm_score()
    is_valid = sim_score >= limiar
    return {'valid': is_valid, 'percent_match': sim_score}

@validacao("rg", campos={
    "ficha_cadastro": ["data_nascimento", "responsavel_legal"],
    "rg": ["data_nascimento"],
})
def validacao_data_nascimento(ficha_cadastro, rg):
    """
    Valida se a data de nascimento extraída do cartao_proposta corresponde à data de nascimento extraída dos dados.

    Lógica de Retorno:
    - TRUE: Se as datas de nascimento forem iguais;
    - FALSE: Caso contrário.
    """
    
    s1 =  ficha_cadastro.data_nascimento

    responsavel_legal = ficha_cadastro.responsavel_legal
    
    if(responsavel_legal and len(s1.strip()) == 0):
        return {'valid': True, 'percent_match': 100, 
        'trecho_procurado': 'Validação não aplicável ao documento do representante legal',
        'trecho_encontrado': 'Validação não aplicável ao documento do representante legal'}
        
    date_1 = safe_strptime(s1, '%d/%m/%Y')
    s2 = rg.data_nascimento

    if(s2 == 'Not Found'):
        return {'valid': False, 'percent_match': 0}

    date_2 = safe_strptime(s2, '%d-%m-%Y')

    is_valid = date_1 == date_2
    return {'valid': is_valid, 'percent_match': 100 if is_valid else 0}

@validacao("rg", campos={"rg": ["data_expedicao"]})
def validacao_data_expedicao(rg):
    """
    Valida se a data de expedição do documento extraída dos dados tem menos de 10 anos.

    Lógica de Retorno:
    - TRUE: Se a data de expedição for dentro do período de 10 anos;
    - FALSE: Caso contrário.
    """
    now = datetime.datetime.now().date()
    extracted_date = rg.data_expedicao

    if(extracted_date == 'Not Found'):
        return {'valid': False, 'percent_match': 0}

    extracted_dispatch_date = safe_strptime(
        extracted_date, "%d-%m-%Y").date()

    is_valid = extracted_dispatch_date >= (now - relativedelta(years=10))
    return {'valid': is_valid, 'percent_match': 100 if is_valid else 0}