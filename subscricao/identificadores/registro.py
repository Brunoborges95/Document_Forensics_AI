"""
Verificação de identificadores.

Um identificador é um valor que tem regra própria e aparece em qualquer documento: CPF, CNPJ,
matrícula de certidão, linha digitável, chave de acesso, código Pix, endereço de verificação.
Ao contrário de uma validação (validacoes/), que pertence a um tipo de documento e compara os
campos extraídos dele, um verificador pertence a um tipo de identificador e confere o valor em
si, onde quer que ele apareça.

Cada verificador é uma função registrada com @verificador. Ela recebe o valor encontrado e, se
precisar, informações que podem nem estar no documento (o valor esperado de um pagamento, o ano
de um registro): são parâmetros da função, preenchidos pelo contexto de quem chama.
"""
import inspect
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# Situação de uma verificação
OK = "OK"
INVALIDO = "INVALIDO"
# não deu para conferir: valor mascarado, informação que falta, consulta externa que não respondeu
NAO_VERIFICAVEL = "NAO_VERIFICAVEL"

# Tipo de identificador que não tem verificador: entra no resultado só como achado
OUTRO = "outro"

# Tipos de identificador que a LLM procura no texto, com a descrição que ela recebe
TIPOS = {
    "cpf": "CPF de pessoa física: 11 dígitos, em geral como 000.000.000-00. Pode vir mascarado (***.456.789-**) ou sem pontuação.",
    "cnpj": "CNPJ de empresa: 14 caracteres, em geral como 00.000.000/0000-00; os 12 primeiros podem ter letras. Pode vir só a raiz (8 primeiros) ou mascarado.",
    "pis": "PIS, PASEP, NIS ou NIT do trabalhador: 11 dígitos, em geral como 000.00000.00-0.",
    "matricula_certidao": "Matrícula de certidão de registro civil (nascimento, casamento, óbito): 32 dígitos, em geral agrupados como 000000 00 00 0000 0 00000 000 0000000 00.",
    "linha_digitavel": "Linha digitável ou código de barras de boleto bancário (47 dígitos) ou de guia de arrecadação, como contas e tributos (48 dígitos, começa com 8).",
    "chave_de_acesso": "Chave de acesso de documento fiscal eletrônico (NF-e, NFC-e, CT-e, NF3e): 44 dígitos, em geral em grupos de 4.",
    "pix": "Código Pix copia e cola (BR Code): texto longo que começa com 000201.",
    "endereco": "Endereço de internet para conferir ou validar o documento (site de verificação de autenticidade, validador de assinatura, consulta de selo).",
}

# tipo -> {nome: verificador}, registrados pelo decorator @verificador
VERIFICADORES = defaultdict(dict)


def verificador(tipo, requer=(), consulta_externa=False):
    """
    Marca uma função como verificador de um tipo de identificador.

    - tipo: o tipo de identificador (uma chave de TIPOS, ou um tipo de QR Code)
    - requer: informações do contexto sem as quais o verificador não roda. As demais informações
      que a função aceita são opcionais: ela confere o que der com o que receber
    - consulta_externa: o verificador consulta um serviço fora da aplicação. Só roda quando as
      consultas externas estão ligadas

    A função recebe o valor encontrado como primeiro argumento e devolve ok(...), invalido(...)
    ou nao_verificavel(...); None quando não tem o que dizer sobre aquele valor.
    """
    def decorator(func):
        if func.__name__ in VERIFICADORES[tipo]:
            raise ValueError(f"Já existe um verificador '{func.__name__}' para o tipo '{tipo}'.")
        func.tipo = tipo
        func.requer = tuple(requer)
        func.consulta_externa = consulta_externa
        # informações do contexto que a função sabe usar
        func.parametros = tuple(list(inspect.signature(func).parameters)[1:])
        VERIFICADORES[tipo][func.__name__] = func
        return func

    return decorator


def ok(detalhe, **dados):
    return {"situacao": OK, "detalhe": detalhe, "dados": dados}


def invalido(detalhe, **dados):
    return {"situacao": INVALIDO, "detalhe": detalhe, "dados": dados}


def nao_verificavel(detalhe, **dados):
    return {"situacao": NAO_VERIFICAVEL, "detalhe": detalhe, "dados": dados}


def verificar(tipo, valor, contexto=None, consultas_externas=False):
    """
    Roda os verificadores do tipo sobre o valor. `contexto` reúne as informações disponíveis,
    pelo nome do parâmetro (por exemplo {"valor_esperado": 1520.30}); cada verificador recebe só
    as que declara. Os que consultam serviços externos só rodam com `consultas_externas`.
    """
    contexto = contexto or {}
    resultados = []

    for nome, func in VERIFICADORES.get(tipo, {}).items():
        if func.consulta_externa and not consultas_externas:
            continue
        if any(contexto.get(informacao) is None for informacao in func.requer):
            continue

        argumentos = {parametro: contexto[parametro] for parametro in func.parametros if contexto.get(parametro) is not None}
        try:
            resultado = func(valor, **argumentos)
        except Exception as e:
            logger.exception(f"Erro no verificador {nome}")
            resultado = nao_verificavel(f"O verificador falhou: {type(e).__name__}: {e}")

        if resultado is not None:
            resultados.append({"verificador": nome, "consulta_externa": func.consulta_externa, **resultado})

    return resultados
