import datetime

import pytest

from subscricao.validacoes import FICHA_CADASTRO, validate
from subscricao.validacoes.ValidateDocument import VALIDACOES, validacao

EXPEDICAO_RECENTE = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%d-%m-%Y")

ENDERECO = {
    "cep": "01310-100",
    "rua": "Avenida Paulista",
    "numero": "1000",
    "complemento": "Sala 12",
    "bairro": "Bela Vista",
    "cidade": "São Paulo",
    "estado": "SP",
}

# a ficha de cadastro chega pronta em JSON e vale para todos os documentos da proposta
FICHA = {
    "nome": "MARIA DA SILVA SOUZA",
    "cpf": "123.456.789-09",
    "nome_mae": "ANA DA SILVA SOUZA",
    "data_nascimento": "14/01/1990",
    "razao_social": "EXEMPLO COMERCIO DE ALIMENTOS LTDA",
    "cnpj": "12.345.678/0001-90",
    "endereco_empresa": ENDERECO,
    "nomes_assinatura": ["MARIA DA SILVA SOUZA"],
}

DADOS_RG = {
    "nome": "Maria da Silva Souza",
    "numero_rg": "12.345.678-9",
    "cpf": "123.456.789-09",
    "nome_pai": "José Souza",
    "nome_mae": "Ana da Silva Souza",
    "data_nascimento": "14-01-1990",
    "data_expedicao": EXPEDICAO_RECENTE,
}

# campos da extração textual
DADOS_CONTRATO_SOCIAL_TEXTUAL = {
    "razao_social": "Exemplo Comércio de Alimentos Ltda",
    "cnpj": "12.345.678/0001-90",
    "administrador": "Maria da Silva Souza",
    "socios": "Maria da Silva Souza, Pedro Souza",
    "tipo_assinatura": "Individual",
    "nomes_assinatura": "Maria da Silva Souza",
    "endereco_empresa": ENDERECO,
    "cpfs": [{"nome": "Maria da Silva Souza", "cpf": "123.456.789-09"}],
}

# campos da extração visual
DADOS_CONTRATO_SOCIAL_VISUAL = {
    "ha_assinatura": True,
    "descricao_assinatura": "Assinatura digital dos sócios",
    "confianca_assinatura": 95,
    "ha_registro_orgao_competente": True,
    "descricao_registro_orgao_competente": "Certificação digital da Junta Comercial",
    "confianca_registro_orgao_competente": 90,
    "sem_valor_certidao": False,
    "descricao_sem_valor_certidao": "Não aplicável",
    "confianca_sem_valor_certidao": 98,
    "ha_quadro_societario": True,
    "descricao_quadro_societario": "Tabela com dois sócios, quotas e valores",
    "confianca_quadro_societario": 92,
    "ha_rodape_autenticacao": True,
    "descricao_rodape_autenticacao": "Rodapé com protocolo e hash",
    "confianca_rodape_autenticacao": 88,
}

DADOS_CONTRATO_SOCIAL = {**DADOS_CONTRATO_SOCIAL_TEXTUAL, **DADOS_CONTRATO_SOCIAL_VISUAL}

VALIDACOES_TEXTUAIS_CONTRATO_SOCIAL = {
    "validacao_razao_social", "validacao_cnpj", "validacao_endereco_empresa", "validacao_tipo_assinatura",
}
VALIDACOES_VISUAIS_CONTRATO_SOCIAL = {
    "validacao_ha_assinatura", "validacao_ha_registro_orgao_competente", "validacao_sem_valor_certidao",
    "validacao_ha_quadro_societario", "validacao_ha_rodape_autenticacao_junta",
}


def registradas(document_type):
    return dict(VALIDACOES[document_type])


def resultados(output):
    """Junta subscription_validations e fraud_validations em um só dicionário."""
    return {nome: resultado for validations in output.values() for nome, resultado in validations.items()}


def erro(resultado):
    return resultado["regras_subscricao_errors"]


# --- declaração das validações ---

def test_validacoes_registradas_por_documento():
    assert set(registradas("rg")) == {
        "validacao_nome", "validacao_cpf", "validacao_nome_mae",
        "validacao_data_nascimento", "validacao_data_expedicao",
    }
    assert set(registradas("contrato_social")) == VALIDACOES_TEXTUAIS_CONTRATO_SOCIAL | VALIDACOES_VISUAIS_CONTRATO_SOCIAL


def test_validacao_declara_os_documentos_e_campos_que_espera():
    # compara o RG com a ficha de cadastro
    assert registradas("rg")["validacao_cpf"].campos == {"ficha_cadastro": ["cpf"], "rg": ["cpf"]}
    # só precisa do próprio documento
    assert registradas("rg")["validacao_data_expedicao"].campos == {"rg": ["data_expedicao"]}
    assert registradas("contrato_social")["validacao_ha_assinatura"].campos == {
        "contrato_social": ["ha_assinatura", "confianca_assinatura", "descricao_assinatura"],
    }


def test_validacao_indica_se_e_textual_ou_visual():
    assert {validation.tipo for validation in registradas("rg").values()} == {"textual"}
    tipos = {nome: validation.tipo for nome, validation in registradas("contrato_social").items()}
    assert {nome for nome, tipo in tipos.items() if tipo == "textual"} == VALIDACOES_TEXTUAIS_CONTRATO_SOCIAL
    assert {nome for nome, tipo in tipos.items() if tipo == "visual"} == VALIDACOES_VISUAIS_CONTRATO_SOCIAL

    with pytest.raises(ValueError, match="Tipo de validação inválido: 'fraude'"):
        validacao("rg", campos={"rg": ["cpf"]}, tipo="fraude")


def test_validacao_precisa_receber_os_documentos_que_declara():
    with pytest.raises(TypeError, match="contrato_social"):
        @validacao("rg", campos={"rg": ["cpf"], "contrato_social": ["cpfs"]})
        def validacao_cpf_do_socio(rg):
            return {"valid": True}


# --- validações com mais de um documento ---

def test_validacao_com_varios_documentos_recebe_apenas_os_campos_declarados(monkeypatch):
    monkeypatch.setitem(VALIDACOES, "rg", {})
    recebidos = {}

    @validacao("rg", campos={"ficha_cadastro": ["cnpj"], "rg": ["nome"], "contrato_social": ["socios", "cnpj"]})
    def validacao_titular_e_socio(ficha_cadastro, rg, contrato_social):
        recebidos.update(ficha_cadastro=vars(ficha_cadastro), rg=vars(rg), contrato_social=vars(contrato_social))
        socio = rg.nome.upper() in contrato_social.socios.upper()
        return {"valid": socio and ficha_cadastro.cnpj == contrato_social.cnpj,
                "trecho_procurado": rg.nome, "trecho_encontrado": contrato_social.socios}

    documentos = {FICHA_CADASTRO: FICHA, "rg": DADOS_RG, "contrato_social": DADOS_CONTRATO_SOCIAL}
    output = validate("rg", documentos)

    assert recebidos == {
        "ficha_cadastro": {"cnpj": "12.345.678/0001-90"},
        "rg": {"nome": "Maria da Silva Souza"},
        "contrato_social": {"socios": "Maria da Silva Souza, Pedro Souza", "cnpj": "12.345.678/0001-90"},
    }
    assert output["subscription_validations"]["validacao_titular_e_socio"] == {
        "valid": True,
        "target": "titular_e_socio",
        "trecho_procurado": "Maria da Silva Souza",
        "trecho_encontrado": "Maria da Silva Souza, Pedro Souza",
        "percent_match": 100.0,
        "regras_subscricao_errors": "OK",
        "tipo": "textual",
    }


def test_validacao_espera_os_documentos_que_faltam(monkeypatch):
    monkeypatch.setitem(VALIDACOES, "rg", {})

    @validacao("rg", campos={"ficha_cadastro": ["cnpj"], "rg": ["nome"], "contrato_social": ["socios"]})
    def validacao_titular_e_socio(ficha_cadastro, rg, contrato_social):
        raise AssertionError("não deve executar sem todos os documentos")

    output = validate("rg", {"rg": DADOS_RG})

    assert output["subscription_validations"]["validacao_titular_e_socio"] == {
        "valid": False,
        "target": "titular_e_socio",
        "trecho_procurado": "",
        "trecho_encontrado": ["ficha_cadastro", "contrato_social"],
        "percent_match": 0,
        "regras_subscricao_errors": "ESPERAR_DOCUMENTOS",
        "tipo": "textual",
    }


def test_sem_ficha_de_cadastro_so_rodam_as_validacoes_que_nao_precisam_dela():
    validations = validate("rg", {"rg": DADOS_RG})["subscription_validations"]

    assert validations["validacao_data_expedicao"]["valid"] is True
    for nome in ("validacao_nome", "validacao_cpf", "validacao_nome_mae", "validacao_data_nascimento"):
        assert validations[nome]["regras_subscricao_errors"] == "ESPERAR_DOCUMENTOS"
        assert validations[nome]["trecho_encontrado"] == ["ficha_cadastro"]


# --- RG ---

def test_rg_valido():
    output = validate("rg", {FICHA_CADASTRO: FICHA, "rg": DADOS_RG})

    assert set(output) == {"subscription_validations"}
    validations = output["subscription_validations"]
    assert set(validations) == set(registradas("rg"))
    assert all(v["valid"] for v in validations.values())
    assert all(v["regras_subscricao_errors"] == "OK" for v in validations.values())

    # trecho procurado vem da ficha de cadastro; trecho encontrado, do documento
    assert validations["validacao_nome"]["trecho_procurado"] == "MARIA DA SILVA SOUZA"
    assert validations["validacao_nome"]["trecho_encontrado"] == "Maria da Silva Souza"
    assert validations["validacao_cpf"] == {
        "valid": True,
        "target": "cpf",
        "trecho_procurado": "123.456.789-09",
        "trecho_encontrado": "123.456.789-09",
        "percent_match": 100.0,
        "regras_subscricao_errors": "OK",
        "tipo": "textual",
    }
    # datas extraídas (DD-MM-YYYY) são normalizadas para DD/MM/YYYY na saída
    assert validations["validacao_data_nascimento"]["trecho_encontrado"] == "14/01/1990"


def test_rg_divergente_e_nao_encontrado():
    dados_rg = {**DADOS_RG, "cpf": "987.654.321-00", "nome": "Carlos Pereira Lima", "data_expedicao": "Not Found"}

    validations = validate("rg", {FICHA_CADASTRO: FICHA, "rg": dados_rg})["subscription_validations"]

    assert validations["validacao_cpf"]["valid"] is False
    assert validations["validacao_cpf"]["regras_subscricao_errors"] == "INCORRETO"
    assert validations["validacao_nome"]["valid"] is False
    assert validations["validacao_data_expedicao"]["valid"] is False
    assert validations["validacao_data_expedicao"]["regras_subscricao_errors"] == "NAO_ENCONTRADO"
    assert validations["validacao_data_expedicao"]["trecho_encontrado"] == "Trecho não encontrado"
    assert validations["validacao_nome_mae"]["valid"] is True


def test_rg_data_invalida():
    dados_rg = {**DADOS_RG, "data_nascimento": "31-02-1990"}

    validations = validate("rg", {FICHA_CADASTRO: FICHA, "rg": dados_rg})["subscription_validations"]

    assert validations["validacao_data_nascimento"]["valid"] is False
    assert validations["validacao_data_nascimento"]["regras_subscricao_errors"] == "INCORRETO"


def test_rg_do_responsavel_legal():
    ficha = {
        "nome": "EMPRESA QUALQUER",
        "nome_responsavel": "MARIA DA SILVA SOUZA",
        "cpf_responsavel": "123.456.789-09",
        "nome_mae": "",
        "data_nascimento": "",
    }

    validations = validate("rg", {FICHA_CADASTRO: ficha, "rg": DADOS_RG})["subscription_validations"]

    assert validations["validacao_nome"]["trecho_procurado"] == "MARIA DA SILVA SOUZA"
    assert validations["validacao_nome"]["valid"] is True
    assert validations["validacao_nome_mae"]["valid"] is True
    assert validations["validacao_data_nascimento"]["valid"] is True
    # a ficha de cadastro recebida não é alterada
    assert "responsavel_legal" not in ficha


def test_campo_ausente_afeta_apenas_a_validacao_que_o_declara():
    dados_rg = {campo: valor for campo, valor in DADOS_RG.items() if campo != "nome_mae"}

    validations = validate("rg", {FICHA_CADASTRO: FICHA, "rg": dados_rg})["subscription_validations"]

    assert validations["validacao_nome_mae"]["regras_subscricao_errors"] == "ERRO_INTERNO"
    assert all(v["valid"] for nome, v in validations.items() if nome != "validacao_nome_mae")


# --- contrato social ---

def test_contrato_social_valido():
    output = validate("contrato_social", {FICHA_CADASTRO: FICHA, "contrato_social": DADOS_CONTRATO_SOCIAL})

    # as validações não se dividem mais em subscrição e fraude: cada uma só diz se é textual ou visual
    assert set(output) == {"subscription_validations"}
    validations = output["subscription_validations"]
    assert {nome for nome, v in validations.items() if v["tipo"] == "textual"} == VALIDACOES_TEXTUAIS_CONTRATO_SOCIAL
    assert {nome for nome, v in validations.items() if v["tipo"] == "visual"} == VALIDACOES_VISUAIS_CONTRATO_SOCIAL
    assert all(v["valid"] for v in validations.values())
    assert all(v["regras_subscricao_errors"] == "OK" for v in validations.values())
    assert output["subscription_validations"]["validacao_endereco_empresa"]["percent_match"] == 100.0
    assert output["subscription_validations"]["validacao_ha_assinatura"]["percent_match"] == 95.0
    assert output["subscription_validations"]["validacao_ha_assinatura"]["trecho_encontrado"] == "Assinatura digital dos sócios"


def test_contrato_social_divergente():
    dados_contrato_social = {
        **DADOS_CONTRATO_SOCIAL,
        "cnpj": "99.999.999/0001-99",
        "tipo_assinatura": "Not Found",
        "endereco_empresa": {**ENDERECO, "cep": "20000-000", "rua": "Rua das Flores", "numero": "5", "cidade": "Rio de Janeiro", "estado": "RJ"},
        "ha_assinatura": False,
        "sem_valor_certidao": True,
        "ha_registro_orgao_competente": False,
        "ha_rodape_autenticacao": False,
    }

    validations = resultados(validate("contrato_social", {FICHA_CADASTRO: FICHA, "contrato_social": dados_contrato_social}))

    assert validations["validacao_cnpj"]["valid"] is False
    assert validations["validacao_tipo_assinatura"]["valid"] is False
    assert validations["validacao_endereco_empresa"]["valid"] is False
    assert validations["validacao_ha_assinatura"]["valid"] is False
    assert validations["validacao_ha_assinatura"]["percent_match"] == 0.0
    # a marca d'água 'SEM VALOR DE CERTIDÃO' presente reprova o documento
    assert validations["validacao_sem_valor_certidao"]["valid"] is False
    assert validations["validacao_ha_rodape_autenticacao_junta"]["valid"] is False
    assert validations["validacao_razao_social"]["valid"] is True
    assert validations["validacao_ha_quadro_societario"]["valid"] is True


def test_validacoes_sao_independentes_entre_si():
    # só a extração textual está disponível: as validações que dependem de campos visuais
    # falham sozinhas e as demais rodam normalmente
    documentos = {FICHA_CADASTRO: FICHA, "contrato_social": DADOS_CONTRATO_SOCIAL_TEXTUAL}

    validations = resultados(validate("contrato_social", documentos))

    for nome in VALIDACOES_TEXTUAIS_CONTRATO_SOCIAL:
        assert validations[nome]["valid"] is True
    for nome in VALIDACOES_VISUAIS_CONTRATO_SOCIAL:
        assert validations[nome]["valid"] is False
        assert erro(validations[nome]) == "ERRO_INTERNO"


# --- condição OU entre documentos ---

VINCULO = ("certidao_casamento", "escritura_uniao_estavel")
DADOS_VINCULO = {"nome_titular": "JOAO PEREIRA LIMA", "nome": "Maria da Silva Souza"}


@pytest.fixture
def validacao_do_conjuge(monkeypatch):
    """Uma validação que pertence à certidão de casamento OU à escritura de união estável."""
    for documento in VINCULO:
        monkeypatch.setitem(VALIDACOES, documento, {})
    recebidos = []

    @validacao(VINCULO, campos={"ficha_cadastro": ["nome"], VINCULO: ["nome", "nome_titular"]})
    def validacao_nome_conjuge(ficha_cadastro, certidao_casamento, escritura_uniao_estavel):
        recebidos.append({documento: argumento and vars(argumento) for documento, argumento in zip(VINCULO, (certidao_casamento, escritura_uniao_estavel))})
        documento = certidao_casamento or escritura_uniao_estavel
        return {"valid": documento.nome.upper() == ficha_cadastro.nome.upper(), "percent_match": 100,
                "trecho_procurado": ficha_cadastro.nome, "trecho_encontrado": documento.nome}

    return validacao_nome_conjuge, recebidos


def test_validacao_com_ou_pertence_a_cada_documento_da_condicao(validacao_do_conjuge):
    funcao, _ = validacao_do_conjuge

    assert VALIDACOES["certidao_casamento"]["validacao_nome_conjuge"] is funcao
    assert VALIDACOES["escritura_uniao_estavel"]["validacao_nome_conjuge"] is funcao
    assert funcao.pertence == VINCULO


def test_validacao_com_ou_roda_com_o_documento_que_estiver_na_proposta(validacao_do_conjuge):
    _, recebidos = validacao_do_conjuge

    output = validate("escritura_uniao_estavel", {FICHA_CADASTRO: FICHA, "escritura_uniao_estavel": DADOS_VINCULO})

    resultado = output["subscription_validations"]["validacao_nome_conjuge"]
    assert resultado["valid"] is True and resultado["regras_subscricao_errors"] == "OK"
    # o tipo que não está na proposta chega como None
    assert recebidos == [{"certidao_casamento": None, "escritura_uniao_estavel": {"nome": "Maria da Silva Souza", "nome_titular": "JOAO PEREIRA LIMA"}}]


def test_com_os_dois_documentos_cada_um_e_validado_com_os_proprios_dados(validacao_do_conjuge):
    _, recebidos = validacao_do_conjuge
    documentos = {FICHA_CADASTRO: FICHA, "certidao_casamento": DADOS_VINCULO, "escritura_uniao_estavel": {**DADOS_VINCULO, "nome": "OUTRA PESSOA"}}

    certidao = validate("certidao_casamento", documentos)["subscription_validations"]["validacao_nome_conjuge"]
    escritura = validate("escritura_uniao_estavel", documentos)["subscription_validations"]["validacao_nome_conjuge"]

    assert (certidao["valid"], escritura["valid"]) == (True, False)
    assert [[documento for documento, dados in chamada.items() if dados] for chamada in recebidos] == [["certidao_casamento"], ["escritura_uniao_estavel"]]


def test_validacao_com_ou_espera_os_outros_documentos(validacao_do_conjuge):
    output = validate("certidao_casamento", {"certidao_casamento": DADOS_VINCULO})

    resultado = output["subscription_validations"]["validacao_nome_conjuge"]
    assert resultado["regras_subscricao_errors"] == "ESPERAR_DOCUMENTOS"
    assert resultado["trecho_encontrado"] == ["ficha_cadastro"]


def test_documento_alternativo_que_nao_e_o_validado(monkeypatch):
    monkeypatch.setitem(VALIDACOES, "comprovante_residencia", {})
    recebidos = []

    @validacao("comprovante_residencia", campos={"comprovante_residencia": ["nome"], ("rg", "cnh"): ["nome_mae"]})
    def validacao_nome_da_mae(comprovante_residencia, rg, cnh):
        recebidos.append((rg and vars(rg), cnh and vars(cnh)))
        return {"valid": True}

    so_com_a_cnh = validate("comprovante_residencia", {"comprovante_residencia": {"nome": "Ana"}, "cnh": {"nome_mae": "Ana"}})
    sem_nenhum = validate("comprovante_residencia", {"comprovante_residencia": {"nome": "Ana"}})

    # basta um dos dois; o que falta chega como None
    assert so_com_a_cnh["subscription_validations"]["validacao_nome_da_mae"]["regras_subscricao_errors"] == "OK"
    assert recebidos == [(None, {"nome_mae": "Ana"})]
    # sem nenhum, a validação espera e diz quais documentos serviriam
    esperando = sem_nenhum["subscription_validations"]["validacao_nome_da_mae"]
    assert esperando["regras_subscricao_errors"] == "ESPERAR_DOCUMENTOS"
    assert esperando["trecho_encontrado"] == ["rg ou cnh"]


def test_validacao_com_ou_precisa_receber_todos_os_documentos_da_condicao(monkeypatch):
    for documento in VINCULO:
        monkeypatch.setitem(VALIDACOES, documento, {})

    with pytest.raises(TypeError, match="escritura_uniao_estavel"):
        @validacao(VINCULO, campos={VINCULO: ["nome"]})
        def validacao_nome(certidao_casamento):
            pass


def test_pendencia_do_catalogo_aparece_uma_vez_para_a_validacao_com_ou(validacao_do_conjuge, monkeypatch):
    from subscricao import catalogo as catalogo_

    @validacao(VINCULO, campos={VINCULO: ["campo_que_nao_existe"]})
    def validacao_campo_que_nao_existe(certidao_casamento, escritura_uniao_estavel):
        pass

    pendencias = [p for p in catalogo_.pendencias(catalogo_.carregar()) if "validacao_campo_que_nao_existe" in p]

    assert pendencias == [
        "validacao_campo_que_nao_existe (certidao_casamento ou escritura_uniao_estavel) espera ['campo_que_nao_existe'] do documento 'certidao_casamento'.",
        "validacao_campo_que_nao_existe (certidao_casamento ou escritura_uniao_estavel) espera ['campo_que_nao_existe'] do documento 'escritura_uniao_estavel'.",
    ]
