"""
Verificadores de cada tipo de identificador. A maioria confere o valor em si (dígitos
verificadores, estrutura, o que o próprio número diz). Os parâmetros além do valor são
informações que quem chama pode ter ou não: sem elas, o verificador confere o que der.
"""
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from ..validacoes.Distances import distances
from . import consultas
from .registro import invalido, nao_verificavel, ok, verificador

# Caracteres usados para esconder parte de um número
MASCARA = "*#•●∙·"


def _sem_pontuacao(valor):
    return re.sub(r"[\s.\-/]", "", str(valor))


def _digitos(valor):
    return re.sub(r"\D", "", str(valor))


def _numero(valor):
    """Valor em reais, de número ou de texto em formato brasileiro (1.520,30) ou com ponto decimal."""
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = re.sub(r"[^\d.,-]", "", str(valor))
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    return float(texto)


def _data(valor):
    """Data de date, datetime ou texto DD/MM/AAAA, DD-MM-AAAA ou AAAA-MM-DD."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(valor).strip(), formato).date()
        except ValueError:
            pass
    raise ValueError(f"data em formato desconhecido: {valor!r}")


def _mesmos_dos_visiveis(valor, esperado):
    """
    Compara, posição a posição, o que está visível de um número mascarado com o número
    esperado. None quando os tamanhos não batem e não dá para alinhar.
    """
    valor, esperado = _sem_pontuacao(valor), _sem_pontuacao(esperado).upper()
    if len(valor) != len(esperado):
        return None
    return all(c in MASCARA or c in "xX" or c.upper() == e for c, e in zip(valor, esperado))


def _lista(valor):
    return list(valor) if isinstance(valor, (list, tuple, set)) else [valor]


# ---------------------------------------------------------------------------------------------
# CPF
# ---------------------------------------------------------------------------------------------

def _dv_cpf(digitos):
    resto = sum(d * peso for d, peso in zip(digitos, range(len(digitos) + 1, 1, -1))) % 11
    return 0 if resto < 2 else 11 - resto


def cpf_mascarado(valor):
    """No CPF todo caractere é dígito: qualquer outra coisa no lugar de um deles é máscara."""
    return bool(re.search(r"\D", _sem_pontuacao(valor)))


def cpf_valido(valor):
    digitos = [int(c) for c in _digitos(valor)]
    if cpf_mascarado(valor) or len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    return digitos[9] == _dv_cpf(digitos[:9]) and digitos[10] == _dv_cpf(digitos[:10])


@verificador("cpf")
def cpf_digito_verificador(valor):
    """O CPF tem 11 dígitos e os dois dígitos verificadores conferem."""
    digitos = _digitos(valor)
    if cpf_mascarado(valor):
        return nao_verificavel(f"CPF mascarado, com {len(digitos)} de 11 dígitos visíveis: não dá para conferir o dígito verificador.", mascarado=True)
    if len(digitos) != 11:
        return invalido(f"CPF com {len(digitos)} dígitos em vez de 11.")
    if len(set(digitos)) == 1:
        return invalido("CPF com todos os dígitos iguais.")
    if not cpf_valido(valor):
        return invalido("Os dígitos verificadores do CPF não conferem.")
    return ok("Dígitos verificadores do CPF conferem.")


@verificador("cpf", requer=("cpf_esperado",))
def cpf_esperado(valor, cpf_esperado):
    """O CPF é um dos esperados (um CPF ou uma lista deles). No mascarado, compara o que está visível."""
    esperados = [_digitos(esperado) for esperado in _lista(cpf_esperado)]
    if cpf_mascarado(valor):
        comparacoes = [_mesmos_dos_visiveis(valor, esperado) for esperado in esperados]
        if all(comparacao is None for comparacao in comparacoes):
            return nao_verificavel("CPF mascarado em formato que não dá para alinhar com o esperado.", mascarado=True)
        if any(comparacoes):
            return ok("Os dígitos visíveis do CPF mascarado batem com o esperado.", mascarado=True)
        return invalido("Os dígitos visíveis do CPF mascarado não batem com o esperado.", mascarado=True)
    if _digitos(valor) in esperados:
        return ok("O CPF é o esperado.")
    return invalido("O CPF não é o esperado.")


# ---------------------------------------------------------------------------------------------
# CNPJ
# ---------------------------------------------------------------------------------------------

def _dv_cnpj(valores):
    pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(valores):]
    resto = sum(valor * peso for valor, peso in zip(valores, pesos)) % 11
    return 0 if resto < 2 else 11 - resto


def cnpj_mascarado(valor):
    """
    O CNPJ pode ter letras nas 12 primeiras posições, então um X sozinho não é máscara. São
    máscara os caracteres de máscara e a letra X repetida (XX.XXX.XXX/0001-XX).
    """
    corpo = _sem_pontuacao(valor)
    return bool(re.search(f"[{re.escape(MASCARA)}]", corpo) or re.search(r"[xX]{2,}", corpo) or re.search(r"[xX]$", corpo))


def cnpj_valido(valor):
    corpo = _sem_pontuacao(valor).upper()
    if cnpj_mascarado(valor) or not re.fullmatch(r"[0-9A-Z]{12}\d{2}", corpo) or len(set(corpo)) == 1:
        return False
    # no CNPJ alfanumérico o valor de cada caractere é o código ASCII menos 48 (0-9 continuam 0-9)
    valores = [ord(c) - 48 for c in corpo]
    return valores[12] == _dv_cnpj(valores[:12]) and valores[13] == _dv_cnpj(valores[:13])


@verificador("cnpj")
def cnpj_digito_verificador(valor):
    """O CNPJ tem 14 caracteres e os dois dígitos verificadores conferem."""
    corpo = _sem_pontuacao(valor).upper()
    if cnpj_mascarado(valor):
        return nao_verificavel("CNPJ mascarado: não dá para conferir o dígito verificador.", mascarado=True)
    if re.fullmatch(r"[0-9A-Z]{8}", corpo):
        return nao_verificavel("Só a raiz do CNPJ (8 primeiros caracteres): sem dígito verificador para conferir.", raiz=corpo)
    if not re.fullmatch(r"[0-9A-Z]{12}\d{2}", corpo):
        return invalido(f"CNPJ com {len(corpo)} caracteres ou com caractere fora do formato (são 14, e os 2 últimos são dígitos).")
    if not cnpj_valido(valor):
        return invalido("Os dígitos verificadores do CNPJ não conferem.")
    return ok("Dígitos verificadores do CNPJ conferem.", raiz=corpo[:8], filial=corpo[8:12])


@verificador("cnpj", requer=("cnpj_esperado",))
def cnpj_esperado(valor, cnpj_esperado):
    """O CNPJ é um dos esperados. Só com a raiz, ou mascarado, compara o que está visível."""
    corpo = _sem_pontuacao(valor).upper()
    esperados = [_sem_pontuacao(esperado).upper() for esperado in _lista(cnpj_esperado)]
    if cnpj_mascarado(valor):
        comparacoes = [_mesmos_dos_visiveis(valor, esperado) for esperado in esperados]
        if all(comparacao is None for comparacao in comparacoes):
            return nao_verificavel("CNPJ mascarado em formato que não dá para alinhar com o esperado.", mascarado=True)
        if any(comparacoes):
            return ok("Os caracteres visíveis do CNPJ mascarado batem com o esperado.", mascarado=True)
        return invalido("Os caracteres visíveis do CNPJ mascarado não batem com o esperado.", mascarado=True)
    if len(corpo) == 8:
        if any(esperado.startswith(corpo) for esperado in esperados):
            return ok("A raiz do CNPJ é a do esperado.")
        return invalido("A raiz do CNPJ não é a do esperado.")
    if corpo in esperados:
        return ok("O CNPJ é o esperado.")
    if any(esperado[:8] == corpo[:8] for esperado in esperados):
        return invalido("O CNPJ é da mesma empresa do esperado (mesma raiz), mas de outro estabelecimento.", mesma_raiz=True)
    return invalido("O CNPJ não é o esperado.")


@verificador("cnpj", consulta_externa=True)
def cnpj_cadastro(valor, razao_social_esperada=None, limiar_razao_social=80):
    """
    Consulta externa: o CNPJ existe na base da Receita e a situação cadastral é ativa. Com a
    razão social esperada, confere também se o nome cadastrado é parecido com ela.
    """
    if not cnpj_valido(valor):
        return None  # mascarado, só a raiz ou com dígito errado: não há o que consultar

    corpo = _sem_pontuacao(valor).upper()
    try:
        cadastro = consultas.cadastro_cnpj(corpo)
    except consultas.ConsultaIndisponivel as e:
        return nao_verificavel(f"A consulta do CNPJ não respondeu: {e}")

    if cadastro is None:
        return invalido("O CNPJ não existe na base da Receita.")

    situacao = str(cadastro.get("descricao_situacao_cadastral", "")).upper()
    dados = {
        "razao_social": cadastro.get("razao_social"),
        "situacao_cadastral": situacao,
        "data_inicio_atividade": cadastro.get("data_inicio_atividade"),
        "municipio": cadastro.get("municipio"),
        "uf": cadastro.get("uf"),
    }
    problemas = []
    if situacao != "ATIVA":
        problemas.append(f"situação cadastral {situacao or 'não informada'}")
    if razao_social_esperada:
        semelhanca = distances(str(dados["razao_social"] or "").upper(), str(razao_social_esperada).upper()).norm_score()
        dados["semelhanca_razao_social"] = round(semelhanca, 1)
        if semelhanca < limiar_razao_social:
            problemas.append(f"a razão social cadastrada ({dados['razao_social']}) não é a esperada")

    if problemas:
        return invalido("Na base da Receita: " + "; ".join(problemas) + ".", **dados)
    return ok(f"CNPJ ativo na base da Receita: {dados['razao_social']}.", **dados)


# ---------------------------------------------------------------------------------------------
# PIS / PASEP / NIS
# ---------------------------------------------------------------------------------------------

def pis_valido(valor):
    digitos = [int(c) for c in _digitos(valor)]
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    resto = sum(d * peso for d, peso in zip(digitos[:10], (3, 2, 9, 8, 7, 6, 5, 4, 3, 2))) % 11
    return digitos[10] == (0 if resto < 2 else 11 - resto)


@verificador("pis")
def pis_digito_verificador(valor):
    """O PIS/PASEP/NIS tem 11 dígitos e o dígito verificador confere."""
    digitos = _digitos(valor)
    if re.search(r"\D", _sem_pontuacao(valor)):
        return nao_verificavel("PIS mascarado: não dá para conferir o dígito verificador.", mascarado=True)
    if len(digitos) != 11:
        return invalido(f"PIS com {len(digitos)} dígitos em vez de 11.")
    if not pis_valido(valor):
        return invalido("O dígito verificador do PIS não confere.")
    return ok("Dígito verificador do PIS confere.")


# ---------------------------------------------------------------------------------------------
# Matrícula de certidão de registro civil
# ---------------------------------------------------------------------------------------------

# Tipo do livro (15º dígito) e a certidão correspondente
LIVROS = {
    "1": ("Livro A", "nascimento"),
    "2": ("Livro B", "casamento"),
    "3": ("Livro B Auxiliar", "casamento"),
    "4": ("Livro C", "obito"),
    "5": ("Livro C Auxiliar", "obito"),
    "6": ("Livro D", "proclamas"),
    "7": ("Livro E", "outros"),
}

# O registro civil obrigatório no Brasil é de 1889; antes disso não há matrícula a esperar
PRIMEIRO_ANO_DE_REGISTRO = 1889


def _dv_matricula(digitos, primeiro_peso):
    """Módulo 11 com os pesos subindo de 0 a 10 em ciclo, a partir do peso inicial; resto 10 vira 1."""
    resto = sum(int(d) * ((primeiro_peso + i) % 11) for i, d in enumerate(digitos)) % 11
    return 1 if resto == 10 else resto


def matricula_valida(valor):
    digitos = _digitos(valor)
    return len(digitos) == 32 and digitos[30:] == f"{_dv_matricula(digitos[:30], 2)}{_dv_matricula(digitos[:31], 1)}"


def partes_da_matricula(valor):
    digitos = _digitos(valor)
    return {
        "serventia": digitos[0:6],
        "acervo": digitos[6:8],
        "servico": digitos[8:10],
        "ano_registro": int(digitos[10:14]),
        "livro": LIVROS.get(digitos[14], ("tipo de livro desconhecido", None))[0],
        "tipo_certidao": LIVROS.get(digitos[14], (None, None))[1],
        "numero_livro": digitos[15:20],
        "folha": digitos[20:23],
        "termo": digitos[23:30],
    }


@verificador("matricula_certidao")
def matricula_certidao(valor, tipo_certidao=None, ano_registro=None, data_nascimento=None, hoje=None):
    """
    A matrícula tem 32 dígitos, os dígitos verificadores conferem e o que ela diz é coerente: o
    serviço é o de registro civil, o ano do registro existe e o livro é de um tipo conhecido.

    Com as informações a mais, confere o que a matrícula diz contra elas: o tipo da certidão
    ('nascimento', 'casamento' ou 'obito'), o ano do registro e, em certidão de nascimento, que
    o registro não é anterior ao nascimento.
    """
    digitos = _digitos(valor)
    if re.search(r"\D", _sem_pontuacao(valor)):
        return nao_verificavel("Matrícula mascarada ou com caracteres que não são dígitos.", mascarado=True)
    if len(digitos) != 32:
        return invalido(f"Matrícula com {len(digitos)} dígitos em vez de 32.")

    partes = partes_da_matricula(valor)
    hoje = _data(hoje) if hoje else date.today()
    problemas = []

    if not matricula_valida(valor):
        problemas.append("os dígitos verificadores não conferem")
    if partes["servico"] != "55":
        problemas.append(f"o código do serviço é {partes['servico']}, e o do registro civil das pessoas naturais é 55")
    if partes["acervo"] not in ("01", "02"):
        problemas.append(f"o código do acervo é {partes['acervo']}, e só existem 01 (próprio) e 02 (incorporado)")
    if partes["tipo_certidao"] is None:
        problemas.append(f"o tipo de livro {digitos[14]} não existe")
    if not PRIMEIRO_ANO_DE_REGISTRO <= partes["ano_registro"] <= hoje.year:
        problemas.append(f"o ano do registro na matrícula é {partes['ano_registro']}")

    if tipo_certidao and partes["tipo_certidao"] and partes["tipo_certidao"] != str(tipo_certidao).lower():
        problemas.append(f"a matrícula é de {partes['livro']} ({partes['tipo_certidao']}), e a certidão é de {tipo_certidao}")
    if ano_registro and int(ano_registro) != partes["ano_registro"]:
        problemas.append(f"o ano do registro na matrícula é {partes['ano_registro']}, e o esperado é {ano_registro}")
    if data_nascimento and partes["tipo_certidao"] == "nascimento" and partes["ano_registro"] < _data(data_nascimento).year:
        problemas.append(f"o ano do registro na matrícula ({partes['ano_registro']}) é anterior ao nascimento ({_data(data_nascimento).year})")

    if problemas:
        return invalido("Matrícula incoerente: " + "; ".join(problemas) + ".", **partes)
    return ok(f"Matrícula coerente: {partes['livro']} ({partes['tipo_certidao']}), registro de {partes['ano_registro']}.", **partes)


# ---------------------------------------------------------------------------------------------
# Linha digitável e código de barras (boleto e arrecadação)
# ---------------------------------------------------------------------------------------------

BASE_DO_FATOR_DE_VENCIMENTO = date(1997, 10, 7)
# Em 22/02/2025 o fator de vencimento chegou a 9999 e voltou a 1000
REINICIO_DO_FATOR = date(2025, 2, 22)


def _mod10(digitos):
    soma = 0
    for i, d in enumerate(reversed(digitos)):
        produto = int(d) * (2 if i % 2 == 0 else 1)
        soma += produto // 10 + produto % 10
    return (10 - soma % 10) % 10


def _mod11(digitos):
    """Módulo 11 com pesos de 2 a 9, da direita para a esquerda. Devolve o resto."""
    return sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(digitos))) % 11


def _vencimento_do_fator(fator, hoje):
    if fator == 0:
        return None
    candidatos = [BASE_DO_FATOR_DE_VENCIMENTO + timedelta(days=fator)]
    if fator >= 1000:
        candidatos.append(REINICIO_DO_FATOR + timedelta(days=fator - 1000))
    # o mesmo fator vale para duas datas, a 9 mil dias uma da outra: fica a mais próxima de hoje
    return min(candidatos, key=lambda candidato: abs((candidato - hoje).days))


def ler_linha_digitavel(valor, hoje=None):
    """
    O que a linha digitável (47 ou 48 dígitos) ou o código de barras (44) diz, e se os dígitos
    verificadores conferem. None quando a quantidade de dígitos não é de nenhum deles.
    """
    digitos = _digitos(valor)
    hoje = _data(hoje) if hoje else date.today()

    if len(digitos) == 48 or (len(digitos) == 44 and digitos[0] == "8"):
        # arrecadação: quatro blocos de 11 dígitos, cada um com o seu dígito verificador
        if len(digitos) == 48:
            blocos = [digitos[i:i + 12] for i in range(0, 48, 12)]
            barras = "".join(bloco[:11] for bloco in blocos)
        else:
            blocos, barras = [], digitos
        modulo10 = barras[2] in "67"
        dv = (lambda d: _mod10(d)) if modulo10 else (lambda d: 0 if _mod11(d) in (0, 1) else 11 - _mod11(d))
        confere = all(str(dv(bloco[:11])) == bloco[11] for bloco in blocos) and str(dv(barras[:3] + barras[4:])) == barras[3]
        # com identificador 6 ou 8 o campo é o valor em reais; com 7 ou 9, uma quantidade de referência
        valor_em_reais = int(barras[4:15]) / 100 if barras[2] in "68" else None
        return {"tipo": "arrecadação", "digitos_conferem": confere, "valor": valor_em_reais, "vencimento": None, "segmento": barras[1]}

    if len(digitos) in (44, 47):
        if len(digitos) == 47:
            campos = [(digitos[0:9], digitos[9]), (digitos[10:20], digitos[20]), (digitos[21:31], digitos[31])]
            barras = digitos[0:4] + digitos[32] + digitos[33:47] + digitos[4:9] + digitos[10:20] + digitos[21:31]
        else:
            campos, barras = [], digitos
        resto = _mod11(barras[:4] + barras[5:])
        geral = 1 if 11 - resto in (0, 10, 11) else 11 - resto
        confere = all(str(_mod10(campo)) == dv for campo, dv in campos) and str(geral) == barras[4]
        centavos = int(barras[9:19])
        return {
            "tipo": "boleto",
            "digitos_conferem": confere,
            "valor": centavos / 100 if centavos else None,
            "vencimento": _vencimento_do_fator(int(barras[5:9]), hoje),
            "banco": barras[0:3],
        }

    return None


@verificador("linha_digitavel")
def linha_digitavel(valor, valor_esperado=None, vencimento_esperado=None, hoje=None):
    """
    Os dígitos verificadores da linha digitável conferem. Com as informações a mais, confere o
    valor e o vencimento que a própria linha traz contra os esperados.
    """
    if re.search(f"[{re.escape(MASCARA)}xX]", str(valor)):
        return nao_verificavel("Linha digitável mascarada.", mascarado=True)
    leitura = ler_linha_digitavel(valor, hoje)
    if leitura is None:
        return invalido(f"Linha digitável com {len(_digitos(valor))} dígitos: o boleto tem 47 e a arrecadação, 48.")

    dados = {**leitura, "vencimento": leitura["vencimento"].isoformat() if leitura["vencimento"] else None}
    problemas = []
    if not leitura["digitos_conferem"]:
        problemas.append("os dígitos verificadores não conferem")
    if valor_esperado is not None and leitura["valor"] is not None and abs(leitura["valor"] - _numero(valor_esperado)) > 0.005:
        problemas.append(f"o valor na linha é R$ {leitura['valor']:.2f}, e o esperado é R$ {_numero(valor_esperado):.2f}")
    if vencimento_esperado and leitura["vencimento"] and leitura["vencimento"] != _data(vencimento_esperado):
        problemas.append(f"o vencimento na linha é {leitura['vencimento']:%d/%m/%Y}, e o esperado é {_data(vencimento_esperado):%d/%m/%Y}")

    if problemas:
        return invalido(f"Linha digitável de {leitura['tipo']}: " + "; ".join(problemas) + ".", **dados)
    partes = [f"valor R$ {leitura['valor']:.2f}" if leitura["valor"] is not None else "sem valor na linha"]
    if leitura["vencimento"]:
        partes.append(f"vencimento {leitura['vencimento']:%d/%m/%Y}")
    return ok(f"Linha digitável de {leitura['tipo']} com dígitos verificadores corretos ({', '.join(partes)}).", **dados)


# ---------------------------------------------------------------------------------------------
# Chave de acesso de documento fiscal eletrônico
# ---------------------------------------------------------------------------------------------

UFS = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE",
    "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
    "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}
MODELOS = {"55": "NF-e", "65": "NFC-e", "57": "CT-e", "67": "CT-e OS", "58": "MDF-e", "59": "CF-e SAT", "62": "NFCom", "63": "BP-e", "66": "NF3e"}


def partes_da_chave(valor):
    digitos = _digitos(valor)
    return {
        "uf": UFS.get(digitos[0:2]),
        "ano_mes": f"20{digitos[2:4]}-{digitos[4:6]}",
        "emitente": digitos[6:20],
        "modelo": MODELOS.get(digitos[20:22], digitos[20:22]),
        "serie": digitos[22:25],
        "numero": digitos[25:34],
    }


@verificador("chave_de_acesso")
def chave_de_acesso(valor, cnpj_esperado=None, data_emissao=None):
    """
    A chave tem 44 dígitos, o dígito verificador confere e o que ela diz existe: a UF, o mês, o
    modelo do documento e o CNPJ do emitente. Com as informações a mais, confere o emitente e o
    mês de emissão contra os esperados.
    """
    digitos = _digitos(valor)
    if re.search(f"[{re.escape(MASCARA)}xX]", str(valor)):
        return nao_verificavel("Chave de acesso mascarada.", mascarado=True)
    if len(digitos) != 44:
        return invalido(f"Chave de acesso com {len(digitos)} dígitos em vez de 44.")

    partes = partes_da_chave(valor)
    resto = _mod11(digitos[:43])
    problemas = []
    if digitos[43] != str(0 if resto in (0, 1) else 11 - resto):
        problemas.append("o dígito verificador não confere")
    if partes["uf"] is None:
        problemas.append(f"o código de UF {digitos[0:2]} não existe")
    if not 1 <= int(digitos[4:6]) <= 12:
        problemas.append(f"o mês de emissão na chave é {digitos[4:6]}")
    if digitos[20:22] not in MODELOS:
        problemas.append(f"o modelo de documento {digitos[20:22]} não é conhecido")
    # o emitente pode ser pessoa física (produtor rural): o CPF vem com zeros à esquerda
    if not cnpj_valido(partes["emitente"]) and not (partes["emitente"].startswith("000") and cpf_valido(partes["emitente"][3:])):
        problemas.append("o CNPJ do emitente que está na chave tem dígito verificador errado")

    if cnpj_esperado and _sem_pontuacao(cnpj_esperado) != partes["emitente"]:
        problemas.append("o emitente que está na chave não é o CNPJ esperado")
    if data_emissao and f"{_data(data_emissao):%Y-%m}" != partes["ano_mes"]:
        problemas.append(f"a chave é de {partes['ano_mes']}, e a emissão esperada é de {_data(data_emissao):%Y-%m}")

    if problemas:
        return invalido("Chave de acesso incoerente: " + "; ".join(problemas) + ".", **partes)
    return ok(f"Chave de acesso coerente: {partes['modelo']} de {partes['uf']}, emitida em {partes['ano_mes']}.", **partes)


# ---------------------------------------------------------------------------------------------
# Pix (BR Code), do texto ou de QR Code
# ---------------------------------------------------------------------------------------------

def _tlv(conteudo):
    """Campos do BR Code: cada um vem como identificador (2), tamanho (2) e valor."""
    campos, i = {}, 0
    while i + 4 <= len(conteudo):
        tamanho = int(conteudo[i + 2:i + 4])
        campos[conteudo[i:i + 2]] = conteudo[i + 4:i + 4 + tamanho]
        i += 4 + tamanho
    if i != len(conteudo):
        raise ValueError("sobraram caracteres depois do último campo")
    return campos


def _crc16(dados):
    crc = 0xFFFF
    for byte in dados.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def _tipo_da_chave(chave):
    if re.fullmatch(r"\d{11}", chave) and cpf_valido(chave):
        return "CPF"
    if re.fullmatch(r"[0-9A-Z]{12}\d{2}", chave.upper()) and cnpj_valido(chave):
        return "CNPJ"
    if "@" in chave:
        return "e-mail"
    if re.fullmatch(r"\+\d{12,14}", chave):
        return "telefone"
    if re.fullmatch(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", chave):
        return "chave aleatória"
    return "desconhecido"


def ler_pix(valor):
    """
    O que o código Pix diz: recebedor, cidade, valor, e a chave (estático) ou o endereço da
    cobrança (dinâmico). Levanta ValueError quando o texto não é um BR Code do Pix.
    """
    conteudo = str(valor).strip()
    try:
        campos = _tlv(conteudo)
    except (ValueError, IndexError) as e:
        raise ValueError(f"o código não segue a estrutura do BR Code ({e})") from e

    conta = {}
    for identificador in map("{:02d}".format, range(26, 52)):
        try:
            candidato = _tlv(campos.get(identificador, ""))
        except (ValueError, IndexError):
            continue
        if candidato.get("00", "").lower() == "br.gov.bcb.pix":
            conta = candidato
            break
    if not conta:
        raise ValueError("o código não tem a conta do Pix (br.gov.bcb.pix)")

    try:
        adicionais = _tlv(campos.get("62", ""))
    except (ValueError, IndexError):
        adicionais = {}
    chave = conta.get("01")
    return {
        "tipo": "dinâmico" if "25" in conta else "estático",
        "crc_confere": conteudo[-8:-4] == "6304" and _crc16(conteudo[:-4]) == conteudo[-4:].upper(),
        "recebedor": campos.get("59"),
        "cidade": campos.get("60"),
        "valor": float(campos["54"]) if "54" in campos else None,
        "chave": chave,
        "tipo_da_chave": _tipo_da_chave(chave) if chave else None,
        "endereco_da_cobranca": conta.get("25"),
        "txid": adicionais.get("05"),
    }


@verificador("pix")
def pix_estrutura(valor, valor_esperado=None, recebedor_esperado=None, limiar_recebedor=80):
    """
    O código Pix segue a estrutura do BR Code e o código de controle (CRC) confere. Com as
    informações a mais, confere o valor que o código traz e o nome do recebedor contra os
    esperados. No Pix dinâmico o valor fica na cobrança, não no código: é o pix_cobranca que o lê.
    """
    try:
        leitura = ler_pix(valor)
    except ValueError as e:
        return invalido(f"Código Pix inválido: {e}.")

    problemas = []
    if not leitura["crc_confere"]:
        problemas.append("o código de controle (CRC) não confere")
    if valor_esperado is not None and leitura["valor"] is not None and abs(leitura["valor"] - _numero(valor_esperado)) > 0.005:
        problemas.append(f"o valor no código é R$ {leitura['valor']:.2f}, e o esperado é R$ {_numero(valor_esperado):.2f}")
    if recebedor_esperado and leitura["recebedor"]:
        # o BR Code corta o nome do recebedor em 25 caracteres
        esperado = str(recebedor_esperado).upper()[:25]
        if distances(leitura["recebedor"].upper(), esperado).norm_score() < limiar_recebedor:
            problemas.append(f"o recebedor no código é {leitura['recebedor']}, e o esperado é {recebedor_esperado}")

    if problemas:
        return invalido("Código Pix: " + "; ".join(problemas) + ".", **leitura)
    destino = f"cobrança em {leitura['endereco_da_cobranca'].split('/')[0]}" if leitura["tipo"] == "dinâmico" else f"chave do tipo {leitura['tipo_da_chave']}"
    valor_do_codigo = f"R$ {leitura['valor']:.2f}" if leitura["valor"] is not None else "sem valor no código"
    return ok(f"Código Pix {leitura['tipo']} bem formado: recebedor {leitura['recebedor']}, {valor_do_codigo}, {destino}.", **leitura)


@verificador("pix", consulta_externa=True)
def pix_cobranca(valor, valor_esperado=None, devedor_esperado=None, dominios_pix=consultas.DOMINIOS_PIX):
    """
    Consulta externa: busca a cobrança de um Pix dinâmico no endereço que vem no código e
    confere que ela existe. Com as informações a mais, compara o valor da cobrança com o valor
    esperado (o do pagamento, por exemplo) e o CPF ou CNPJ do devedor com o esperado.
    """
    try:
        leitura = ler_pix(valor)
    except ValueError:
        return None  # o pix_estrutura já aponta o código inválido
    endereco = leitura["endereco_da_cobranca"]
    if not endereco:
        return None  # Pix estático: não há cobrança a consultar

    host = urlsplit(f"https://{endereco}").hostname
    try:
        resposta = consultas.cobranca_pix(endereco, dominios_pix)
    except consultas.EnderecoNaoPermitido:
        return nao_verificavel(f"O endereço da cobrança ({host}) não está entre os domínios que a aplicação aceita consultar.", host=host)
    except consultas.ConsultaIndisponivel as e:
        return nao_verificavel(f"A consulta da cobrança em {host} não respondeu: {e}", host=host)

    if resposta["http"] == 404:
        return invalido(f"Não existe cobrança no endereço que está no código Pix ({host}).", host=host, http=404)
    if resposta["http"] == 410:
        return nao_verificavel(f"A cobrança existiu em {host}, mas não está mais disponível (vencida, paga ou removida).", host=host, http=410)

    cobranca = resposta["cobranca"]
    valores = cobranca.get("valor", {})
    devedor = cobranca.get("devedor", {})
    dados = {
        "host": host,
        "status": cobranca.get("status"),
        "valor_original": valores.get("original"),
        "valor_final": valores.get("final"),
        "vencimento": cobranca.get("calendario", {}).get("dataDeVencimento"),
        "devedor": devedor.get("cnpj") or devedor.get("cpf"),
        "nome_do_devedor": devedor.get("nome"),
    }
    problemas = []
    if valor_esperado is not None:
        da_cobranca = [_numero(v) for v in (dados["valor_final"], dados["valor_original"]) if v is not None]
        if da_cobranca and all(abs(v - _numero(valor_esperado)) > 0.005 for v in da_cobranca):
            problemas.append(f"o valor da cobrança é R$ {da_cobranca[0]:.2f}, e o esperado é R$ {_numero(valor_esperado):.2f}")
    if devedor_esperado and dados["devedor"] and _digitos(devedor_esperado) != _digitos(dados["devedor"]):
        problemas.append("o devedor da cobrança não é o esperado")

    if problemas:
        return invalido(f"Cobrança em {host}: " + "; ".join(problemas) + ".", **dados)
    return ok(f"Cobrança encontrada em {host}, com status {dados['status']}.", **dados)


# ---------------------------------------------------------------------------------------------
# Endereço de verificação
# ---------------------------------------------------------------------------------------------

# Domínios reservados a órgãos públicos no Brasil
DOMINIOS_OFICIAIS = ("gov.br", "jus.br", "mp.br", "leg.br", "def.br", "mil.br")

# Entidades de registro e plataformas de assinatura que aparecem nos documentos
DOMINIOS_CONHECIDOS = (
    "registrocivil.org.br", "funarpen.com.br", "e-notariado.org.br", "censec.org.br", "onr.org.br",
    "clicksign.com", "docusign.com", "docusign.net", "d4sign.com.br", "zapsign.com.br", "portaldeassinaturas.com.br",
)

ENCURTADORES = ("bit.ly", "tinyurl.com", "goo.gl", "t.co", "is.gd", "cutt.ly", "encurtador.com.br", "rebrand.ly")


@verificador("endereco")
def endereco_dominio(valor, dominios_conhecidos=DOMINIOS_CONHECIDOS):
    """
    De quem é o endereço: de órgão público, de uma entidade conhecida ou de um domínio que a
    aplicação não reconhece. O endereço não é acessado.
    """
    texto = str(valor).strip()
    try:
        host = (urlsplit(texto if "://" in texto else f"https://{texto}").hostname or "").lower()
    except ValueError:
        host = ""
    if not host or "." not in host:
        return invalido("O texto não é um endereço de internet.")

    def pertence(dominios):
        return any(host == dominio or host.endswith(f".{dominio}") for dominio in dominios)

    if re.fullmatch(r"[\d.]+", host):
        return nao_verificavel("O endereço é um número de IP, sem domínio que identifique de quem é.", host=host)
    if pertence(ENCURTADORES):
        return nao_verificavel("O endereço é de um encurtador: não dá para saber aonde leva sem acessá-lo.", host=host)
    if pertence(DOMINIOS_OFICIAIS):
        return ok(f"Endereço de órgão público ({host}).", host=host, origem="órgão público")
    if pertence(dominios_conhecidos):
        return ok(f"Endereço de entidade conhecida ({host}).", host=host, origem="entidade conhecida")
    return nao_verificavel(f"Domínio que a aplicação não reconhece ({host}): confira de quem é.", host=host)
