import re
from .ValidateDocument import validacao
from .tools import str2bool
from .Distances import distances

from .validacao_endereco import Validacao_endereco

@validacao("contrato_social", campos={
    "ficha_cadastro": ["razao_social"],
    "contrato_social": ["razao_social"],
})
def validacao_razao_social(ficha_cadastro, contrato_social, limiar=80):
    """
    Valida se a razão social extraída corresponde à razão social do cartão proposta.

    Lógica de Retorno:
    - TRUE: Se a similaridade entre as razões sociais for igual ou superior ao limiar;
    - FALSE: Caso contrário.

    Parâmetros:
    - limiar: Valor mínimo de similaridade para considerar válido (padrão: 80).
    """
    s1 = ficha_cadastro.razao_social
    s2 = contrato_social.razao_social
    
    sim_score = distances(s1.upper(), s2.upper()).norm_score()
    is_valid = sim_score >= limiar
    return {'valid': is_valid, 'percent_match': sim_score}

@validacao("contrato_social", campos={"ficha_cadastro": ["cnpj"], "contrato_social": ["cnpj"]})
def validacao_cnpj(ficha_cadastro, contrato_social):
    """
    Valida se o CNPJ extraído corresponde ao CNPJ do cartão proposta.

    Lógica de Retorno:
    - TRUE: Se os CNPJs forem idênticos após a remoção de caracteres não numéricos;
    - FALSE: Caso contrário.
    """
    s1 = ''.join(re.findall(r'[a-zA-Z0-9]', ficha_cadastro.cnpj))
    s2 = ''.join(re.findall(r'[a-zA-Z0-9]', contrato_social.cnpj))
    if s1 == s2:
        return {'valid': True, 'percent_match': 100}  
    else:
        return {'valid': False, 'percent_match': 0}

@validacao("contrato_social", campos={
    "ficha_cadastro": ["endereco_empresa"],
    "contrato_social": ["endereco_empresa"],
})
def validacao_endereco_empresa(ficha_cadastro, contrato_social):
    """
    Valida se o endereço da empresa extraído corresponde ao endereço do cartão proposta.

    Lógica de Retorno:
    - Determinada pela classe Validacao_endereco.
    """
    val_endereco = Validacao_endereco(ficha_cadastro.endereco_empresa, contrato_social.endereco_empresa)
    valid, score = val_endereco.validar_endereco()
    
    return {'valid': valid, 'percent_match': score}
    
def _is_valid(campo, confianca, descricao, invert_bool=False):
    is_valid = str2bool(campo) if not invert_bool else not str2bool(campo)
    return {
        "valid": is_valid,
        "percent_match": confianca if is_valid else 0,
        "trecho_procurado": "",
        "trecho_encontrado": f'{descricao}'
    }

@validacao("contrato_social", campos={
    "contrato_social": ["ha_assinatura", "confianca_assinatura", "descricao_assinatura"],
}, tipo="visual")
def validacao_ha_assinatura(contrato_social):
    """
    Valida se o documento está assinado.

    Lógica de Retorno:
    - TRUE: Se o documento estiver assinado;
    - FALSE: Caso contrário.
    """
    assinatura = contrato_social.ha_assinatura
    return _is_valid(assinatura, contrato_social.confianca_assinatura, contrato_social.descricao_assinatura)


@validacao("contrato_social", campos={"contrato_social": ["tipo_assinatura"]})
def validacao_tipo_assinatura(contrato_social):
    """
    Valida o tipo de assinatura do documento em relação ao número de assinantes.

    Lógica de Retorno:
    - TRUE: Se o tipo de assinatura for compatível com o número de assinantes;
    - FALSE: Se o tipo de assinatura for 'em conjunto' e houver apenas um assinante.

    Detalhes:
    - Verifica se o tipo de assinatura 'em conjunto' é válido para o número de assinantes.
    - Considera válido qualquer outro tipo de assinatura ou quando há mais de um assinante.
    """
    tipo_assinatura = contrato_social.tipo_assinatura.lower()
    if tipo_assinatura in ['em conjunto', 'individual']:
        return {"valid": True, "percent_match": 100, 
                "trecho_procurado": "",
                "trecho_encontrado": tipo_assinatura}
    else:
        return {"valid": False, "percent_match": 0, 
                "trecho_procurado": "",
                "trecho_encontrado": tipo_assinatura}

#@validacao("contrato_social", campos={"ficha_cadastro": ["nomes_assinatura"], "contrato_social": ["nomes_assinatura"]})
def validacao_responsaveis_assinatura(ficha_cadastro, contrato_social, limiar=90):
    """
    Valida se os responsáveis pela assinatura correspondem aos assinantes do cartão proposta.

    Lógica de Retorno:
    - TRUE: Se todos os assinantes do cartão proposta têm correspondência com os responsáveis pela assinatura;
    - FALSE: Se algum assinante não tem correspondência suficiente com os responsáveis pela assinatura.

    Detalhes:
    - Compara cada assinante do cartão proposta com todos os responsáveis pela assinatura.
    - Utiliza um algoritmo de similaridade para calcular a correspondência entre nomes.
    - Se nenhum responsável pela assinatura corresponder a um assinante acima do limiar, a validação falha.
    - A pontuação final é a média das melhores correspondências para cada assinante.

    Parâmetros:
    - limiar: Valor mínimo de similaridade para considerar uma correspondência válida (padrão: 90).
    """
    nomes_assinatura_de = contrato_social.nomes_assinatura.split(',')
    nomes_assinatura_de = [i.strip() for i in nomes_assinatura_de]
    nomes_assinatura_cp = ficha_cadastro.nomes_assinatura
    

    for i in nomes_assinatura_cp:
        assinante_score = 0
        scores = []
        for j in nomes_assinatura_de:
            sim_score = distances(i.upper(), j.upper()).norm_score()
            scores.append(sim_score)
        if all(score < limiar for score in scores):
            return {"valid": False, "percent_match": max(scores), 
                "trecho_procurado": i,
                "trecho_encontrado": nomes_assinatura_de}
        assinante_score += max(scores)
    final_score = assinante_score/len(nomes_assinatura_cp)
    
    return {"valid": True, "percent_match": final_score, 
                "trecho_procurado": nomes_assinatura_cp,
                "trecho_encontrado": nomes_assinatura_de}

@validacao("contrato_social", campos={
    "contrato_social": ["ha_registro_orgao_competente", "confianca_registro_orgao_competente", "descricao_registro_orgao_competente"],
}, tipo="visual")
def validacao_ha_registro_orgao_competente(contrato_social):
    """
    Valida se o documento contém um selo, carimbo ou termo de autenticidade que identifique o órgão competente.

    Lógica de Retorno:
    - TRUE: Se o documento conter um selo/carimbo/termo de autenticidade;
    - FALSE: Caso contrário.
    """
    selo = contrato_social.ha_registro_orgao_competente
    return _is_valid(selo, contrato_social.confianca_registro_orgao_competente, contrato_social.descricao_registro_orgao_competente)     


@validacao("contrato_social", campos={
    "contrato_social": ["sem_valor_certidao", "confianca_sem_valor_certidao", "descricao_sem_valor_certidao"],
}, tipo="visual")
def validacao_sem_valor_certidao(contrato_social):
    """
    Valida se o documento contém um marca d'água com a expressão 'sem valor de certidão'.

    Lógica de Retorno:
    - TRUE: Se o documento não conter essa marca d'água;
    - FALSE: Caso contrário.
    """
    sem_valor_certidao = contrato_social.sem_valor_certidao
    return _is_valid(sem_valor_certidao, contrato_social.confianca_sem_valor_certidao, contrato_social.descricao_sem_valor_certidao, invert_bool=True)
    
@validacao("contrato_social", campos={
    "contrato_social": ["ha_quadro_societario", "confianca_quadro_societario", "descricao_quadro_societario"],
}, tipo="visual")
def validacao_ha_quadro_societario(contrato_social):
    """
    Valida se o documento contém quadro societário presente com quotas e valor.

    Lógica de Retorno:
    - TRUE: Se o documento conter um quadro societário;
    - FALSE: Caso contrário.
    """
    quadro_societario = contrato_social.ha_quadro_societario
    return _is_valid(quadro_societario, contrato_social.confianca_quadro_societario, contrato_social.descricao_quadro_societario)

@validacao("contrato_social", campos={
    "contrato_social": ["ha_registro_orgao_competente", "ha_rodape_autenticacao", "descricao_registro_orgao_competente", "confianca_registro_orgao_competente", "descricao_rodape_autenticacao", "confianca_rodape_autenticacao"],
}, tipo="visual")

def validacao_ha_rodape_autenticacao_junta(contrato_social):
    """
    Valida se o documento contém Rodapé com autenticação da Junta Comercial (versão digital)
    ou registro do órgão competente (versão física).
    
    Lógica de Retorno:
    - TRUE: Se o documento contiver um rodapé de autenticação digital OU registro do órgão competente (selo/carimbo);
    - FALSE: Se não contiver nem rodapé nem registro do órgão competente.
    """
    ha_registro = contrato_social.ha_registro_orgao_competente
    ha_rodape = contrato_social.ha_rodape_autenticacao
    descricao_registro = contrato_social.descricao_registro_orgao_competente
    confianca_registro = contrato_social.confianca_registro_orgao_competente
    descricao_rodape = contrato_social.descricao_rodape_autenticacao
    confianca_rodape = contrato_social.confianca_rodape_autenticacao
    
    # Caso não tenha nem registro físico nem rodapé digital
    if not ha_registro and not ha_rodape:
        return {
            "valid": False, 
            "percent_match": 0, 
            "trecho_procurado": 'Registro do órgão competente (selo/carimbo) ou rodapé de autenticação digital da Junta Comercial',
            "trecho_encontrado": 'Nenhum registro ou rodapé encontrado'
        }
    
    # Caso tenha registro físico (documento físico com selo/carimbo)
    if ha_registro and not ha_rodape:
        return {
            "valid": True, 
            "percent_match": confianca_registro, 
            "trecho_procurado": 'Registro do órgão competente (selo/carimbo)',
            "trecho_encontrado": descricao_registro
        }
    
    # Caso tenha rodapé digital (documento digital)
    if ha_rodape:
        return {
            "valid": True, 
            "percent_match": confianca_rodape, 
            "trecho_procurado": 'Rodapé de autenticação digital da Junta Comercial',
            "trecho_encontrado": descricao_rodape
        } 
                    
                

    