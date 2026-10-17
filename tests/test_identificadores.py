import base64
import copy
import json
import shutil
from datetime import date
from pathlib import Path

import cv2
import pytest
from PIL import Image
from pydantic import TypeAdapter
from streamlit.testing.v1 import AppTest

from subscricao import catalogo as catalogo_, identificadores, pipeline
from subscricao.conversao import DocumentoConvertido
from subscricao.fraude import configuracao as fraude_
from subscricao.identificadores import INVALIDO, NAO_VERIFICAVEL, OK, busca, consultas, registro, verificadores as v, verificar

from test_fraude import CATALOGO, CONFIG

APP = Path(__file__).resolve().parent.parent / "app.py"


def situacoes(tipo, valor, contexto=None, consultas_externas=False):
    """{verificador: situação} das verificações que rodaram."""
    return {r["verificador"]: r["situacao"] for r in verificar(tipo, valor, contexto, consultas_externas)}


def unica(tipo, valor, contexto=None, consultas_externas=False):
    resultados = verificar(tipo, valor, contexto, consultas_externas)
    assert len(resultados) == 1, resultados
    return resultados[0]


# --- CPF ---

@pytest.mark.parametrize("valor, situacao, trecho", [
    ("123.456.789-09", OK, "conferem"),
    ("12345678909", OK, "conferem"),
    ("123.456.789-00", INVALIDO, "não conferem"),
    ("123.456.789-0", INVALIDO, "10 dígitos"),
    ("111.111.111-11", INVALIDO, "todos os dígitos iguais"),
    # mascarado não é inválido: só não dá para conferir
    ("***.456.789-**", NAO_VERIFICAVEL, "6 de 11 dígitos visíveis"),
    ("123.XXX.XXX-09", NAO_VERIFICAVEL, "mascarado"),
    ("•••.456.789-••", NAO_VERIFICAVEL, "mascarado"),
])
def test_digito_verificador_do_cpf(valor, situacao, trecho):
    resultado = unica("cpf", valor)

    assert resultado["verificador"] == "cpf_digito_verificador"
    assert resultado["situacao"] == situacao
    assert trecho in resultado["detalhe"]


@pytest.mark.parametrize("valor, esperado, situacao", [
    ("123.456.789-09", "12345678909", OK),
    ("123.456.789-09", ["111.444.777-35", "123.456.789-09"], OK),
    ("123.456.789-09", "111.444.777-35", INVALIDO),
    # no mascarado, compara só o que está visível
    ("***.456.789-**", "123.456.789-09", OK),
    ("123.***.***-09", "123.456.789-09", OK),
    ("***.456.789-**", "111.444.777-35", INVALIDO),
    ("***456789**", "123.456.789-09", OK),
    ("***.456.78*", "123.456.789-09", NAO_VERIFICAVEL),
])
def test_cpf_esperado_so_roda_com_a_informacao(valor, esperado, situacao):
    # sem a informação, só o dígito verificador é conferido
    assert list(situacoes("cpf", valor)) == ["cpf_digito_verificador"]

    assert situacoes("cpf", valor, {"cpf_esperado": esperado})["cpf_esperado"] == situacao


# --- CNPJ ---

@pytest.mark.parametrize("valor, situacao, trecho", [
    ("12.345.678/0001-95", OK, "conferem"),
    ("12345678000195", OK, "conferem"),
    ("12.ABC.345/01DE-35", OK, "conferem"),
    ("12.345.678/0001-90", INVALIDO, "não conferem"),
    ("12.345.678/0001-9", INVALIDO, "13 caracteres"),
    ("12.345.678", NAO_VERIFICAVEL, "raiz"),
    ("12.***.***/0001-**", NAO_VERIFICAVEL, "mascarado"),
    ("XX.XXX.XXX/0001-XX", NAO_VERIFICAVEL, "mascarado"),
])
def test_digito_verificador_do_cnpj(valor, situacao, trecho):
    resultado = unica("cnpj", valor)

    assert resultado["situacao"] == situacao
    assert trecho in resultado["detalhe"]


def test_letra_no_cnpj_alfanumerico_nao_e_mascara():
    assert not v.cnpj_mascarado("1X.ABC.345/01DE-35")
    assert v.cnpj_mascarado("1X.ABC.345/01DE-XX")
    assert v.cnpj_mascarado("12.345.678/0001-9*")


@pytest.mark.parametrize("valor, situacao, trecho", [
    ("12.345.678/0001-95", OK, "é o esperado"),
    ("12.345.678/0002-76", INVALIDO, "outro estabelecimento"),
    ("11.444.777/0001-61", INVALIDO, "não é o esperado"),
    ("12.345.678", OK, "raiz"),
    ("11.444.777", INVALIDO, "raiz"),
    ("12.***.***/0001-**", OK, "visíveis"),
    ("99.***.***/0001-**", INVALIDO, "visíveis"),
])
def test_cnpj_esperado(valor, situacao, trecho):
    resultado = next(r for r in verificar("cnpj", valor, {"cnpj_esperado": "12.345.678/0001-95"}) if r["verificador"] == "cnpj_esperado")

    assert resultado["situacao"] == situacao
    assert trecho in resultado["detalhe"]


# --- PIS ---

@pytest.mark.parametrize("valor, situacao", [
    ("123.45678.90-0", OK),
    ("123.45678.90-1", INVALIDO),
    ("123.45678.90", INVALIDO),
    ("123.*****.90-0", NAO_VERIFICAVEL),
])
def test_digito_verificador_do_pis(valor, situacao):
    assert unica("pis", valor)["situacao"] == situacao


# --- matrícula de certidão ---

def matricula(serventia="123456", acervo="01", servico="55", ano="2015", livro="1", numero_livro="00012", folha="345", termo="0001234"):
    corpo = f"{serventia}{acervo}{servico}{ano}{livro}{numero_livro}{folha}{termo}"
    dv1 = v._dv_matricula(corpo, 2)
    return f"{serventia} {acervo} {servico} {ano} {livro} {numero_livro} {folha} {termo} {dv1}{v._dv_matricula(corpo + str(dv1), 1)}"


def test_matricula_coerente_diz_o_que_e_a_certidao():
    resultado = unica("matricula_certidao", matricula())

    assert resultado["situacao"] == OK
    assert resultado["detalhe"] == "Matrícula coerente: Livro A (nascimento), registro de 2015."
    assert resultado["dados"] == {
        "serventia": "123456", "acervo": "01", "servico": "55", "ano_registro": 2015, "livro": "Livro A", "tipo_certidao": "nascimento",
        "numero_livro": "00012", "folha": "345", "termo": "0001234",
    }


@pytest.mark.parametrize("valor, contexto, trecho", [
    (matricula()[:-1] + "9", {}, "os dígitos verificadores não conferem"),
    (matricula(servico="54"), {}, "o código do serviço é 54"),
    (matricula(acervo="07"), {}, "o código do acervo é 07"),
    (matricula(livro="9"), {}, "o tipo de livro 9 não existe"),
    (matricula(ano="2031"), {"hoje": "2026-10-13"}, "o ano do registro na matrícula é 2031"),
    (matricula(ano="1800"), {}, "o ano do registro na matrícula é 1800"),
    # o que a matrícula diz contra o que se sabe por fora
    (matricula(), {"tipo_certidao": "casamento"}, "a matrícula é de Livro A (nascimento), e a certidão é de casamento"),
    (matricula(), {"ano_registro": 2016}, "o ano do registro na matrícula é 2015, e o esperado é 2016"),
    (matricula(), {"data_nascimento": "14/01/2016"}, "é anterior ao nascimento (2016)"),
])
def test_matricula_incoerente(valor, contexto, trecho):
    resultado = unica("matricula_certidao", valor, contexto)

    assert resultado["situacao"] == INVALIDO
    assert trecho in resultado["detalhe"]


def test_matricula_com_as_informacoes_certas_continua_coerente():
    contexto = {"tipo_certidao": "nascimento", "ano_registro": 2015, "data_nascimento": "20/12/2014", "hoje": date(2026, 10, 13)}

    assert unica("matricula_certidao", matricula(), contexto)["situacao"] == OK
    assert unica("matricula_certidao", matricula()[:-3], contexto)["detalhe"] == "Matrícula com 30 dígitos em vez de 32."


# --- linha digitável ---

def linha_de_boleto(valor_em_centavos=152030, fator=1500, banco="001", campo_livre="1234567890123456789012345"):
    sem_dv = f"{banco}9{fator:04d}{valor_em_centavos:010d}{campo_livre}"
    resto = v._mod11(sem_dv)
    geral = 1 if 11 - resto in (0, 10, 11) else 11 - resto
    campos = [f"{banco}9{campo_livre[:5]}", campo_livre[5:15], campo_livre[15:]]
    return " ".join(f"{campo}{v._mod10(campo)}" for campo in campos) + f" {geral} {fator:04d}{valor_em_centavos:010d}"


def linha_de_arrecadacao(valor_em_centavos=79552, identificador="8"):
    sem_dv = f"85{identificador}{valor_em_centavos:011d}" + "0179" + "2024071912345678901234567"[:26]
    sem_dv = sem_dv[:43]
    dv = (lambda d: v._mod10(d)) if identificador in "67" else (lambda d: 0 if v._mod11(d) in (0, 1) else 11 - v._mod11(d))
    barras = sem_dv[:3] + str(dv(sem_dv)) + sem_dv[3:]
    return " ".join(f"{barras[i:i + 11]}-{dv(barras[i:i + 11])}" for i in range(0, 44, 11))


def test_linha_digitavel_de_boleto_traz_valor_e_vencimento():
    resultado = unica("linha_digitavel", linha_de_boleto(), {"hoje": "2026-10-13"})

    assert resultado["situacao"] == OK
    assert resultado["dados"]["tipo"] == "boleto" and resultado["dados"]["banco"] == "001"
    assert resultado["dados"]["valor"] == 1520.30
    # o fator 1500 vale para 2001 e, depois do reinício de 2025, para 2026: fica a data mais próxima de hoje
    assert resultado["dados"]["vencimento"] == "2026-07-07"
    assert "valor R$ 1520.30, vencimento 07/07/2026" in resultado["detalhe"]


def test_linha_digitavel_de_arrecadacao():
    resultado = unica("linha_digitavel", linha_de_arrecadacao())
    assert resultado["situacao"] == OK
    assert resultado["dados"]["tipo"] == "arrecadação" and resultado["dados"]["valor"] == 795.52

    # com identificador 6 os dígitos são de módulo 10
    assert unica("linha_digitavel", linha_de_arrecadacao(identificador="6"))["situacao"] == OK


@pytest.mark.parametrize("linha, contexto, trecho", [
    (linha_de_boleto()[:-1] + "9", {}, "os dígitos verificadores não conferem"),
    (linha_de_arrecadacao()[:-1] + "9", {}, "os dígitos verificadores não conferem"),
    (linha_de_boleto(), {"valor_esperado": "1.250,30"}, "o valor na linha é R$ 1520.30, e o esperado é R$ 1250.30"),
    (linha_de_arrecadacao(), {"valor_esperado": 800}, "o valor na linha é R$ 795.52, e o esperado é R$ 800.00"),
    (linha_de_boleto(), {"vencimento_esperado": "08/07/2026", "hoje": "2026-10-13"}, "o vencimento na linha é 07/07/2026, e o esperado é 08/07/2026"),
    ("12345 67890", {}, "10 dígitos"),
])
def test_linha_digitavel_com_problema(linha, contexto, trecho):
    resultado = unica("linha_digitavel", linha, contexto)

    assert resultado["situacao"] == INVALIDO
    assert trecho in resultado["detalhe"]


def test_linha_digitavel_com_o_valor_e_o_vencimento_esperados():
    contexto = {"valor_esperado": "R$ 1.520,30", "vencimento_esperado": date(2026, 7, 7), "hoje": "2026-10-13"}

    assert unica("linha_digitavel", linha_de_boleto(), contexto)["situacao"] == OK


# --- chave de acesso ---

def chave(uf="35", ano_mes="2311", emitente="12345678000195", modelo="55", resto="001000000123" + "1" + "12345678"):
    sem_dv = f"{uf}{ano_mes}{emitente}{modelo}{resto}"
    r = v._mod11(sem_dv)
    completa = sem_dv + str(0 if r in (0, 1) else 11 - r)
    return " ".join(completa[i:i + 4] for i in range(0, 44, 4))


def test_chave_de_acesso_coerente():
    resultado = unica("chave_de_acesso", chave())

    assert resultado["situacao"] == OK
    assert resultado["detalhe"] == "Chave de acesso coerente: NF-e de SP, emitida em 2023-11."
    assert resultado["dados"]["emitente"] == "12345678000195" and resultado["dados"]["numero"] == "000000123"


@pytest.mark.parametrize("valor, contexto, trecho", [
    (chave()[:-1] + "0", {}, "o dígito verificador não confere"),
    (chave(uf="99"), {}, "o código de UF 99 não existe"),
    (chave(ano_mes="2313"), {}, "o mês de emissão na chave é 13"),
    (chave(modelo="01"), {}, "o modelo de documento 01 não é conhecido"),
    (chave(emitente="12345678000190"), {}, "o CNPJ do emitente que está na chave tem dígito verificador errado"),
    (chave(), {"cnpj_esperado": "11.444.777/0001-61"}, "o emitente que está na chave não é o CNPJ esperado"),
    (chave(), {"data_emissao": "05/12/2023"}, "a chave é de 2023-11, e a emissão esperada é de 2023-12"),
])
def test_chave_de_acesso_incoerente(valor, contexto, trecho):
    resultado = unica("chave_de_acesso", valor, contexto)

    assert resultado["situacao"] == INVALIDO
    assert trecho in resultado["detalhe"]


def test_chave_de_acesso_de_produtor_rural_traz_cpf_no_emitente():
    assert unica("chave_de_acesso", chave(emitente="00012345678909"))["situacao"] == OK
    assert unica("chave_de_acesso", chave(), {"cnpj_esperado": "12.345.678/0001-95", "data_emissao": "2023-11-30"})["situacao"] == OK


# --- Pix ---

def campo(identificador, valor):
    return f"{identificador}{len(valor):02d}{valor}"


def pix(valor="1520.30", recebedor="CAIXA ECONOMICA FEDERAL", chave_pix="12345678000195", endereco=None):
    conta = campo("00", "br.gov.bcb.pix") + (campo("25", endereco) if endereco else campo("01", chave_pix))
    codigo = campo("00", "01") + campo("01", "12" if endereco else "11") + campo("26", conta) + campo("52", "0000") + campo("53", "986")
    if valor:
        codigo += campo("54", valor)
    codigo += campo("58", "BR") + campo("59", recebedor) + campo("60", "BRASILIA") + campo("62", campo("05", "TXID123")) + "6304"
    return codigo + v._crc16(codigo)


COBRANCA = "pix-qrcode.caixa.gov.br/api/v2/cobv/0123456789abcdef"


def test_pix_estatico_bem_formado():
    resultado = unica("pix", pix())

    assert resultado["situacao"] == OK
    assert resultado["dados"]["tipo"] == "estático" and resultado["dados"]["valor"] == 1520.30
    assert resultado["dados"]["chave"] == "12345678000195" and resultado["dados"]["tipo_da_chave"] == "CNPJ"
    assert resultado["dados"]["recebedor"] == "CAIXA ECONOMICA FEDERAL" and resultado["dados"]["txid"] == "TXID123"


def test_pix_dinamico_traz_o_endereco_da_cobranca():
    resultado = unica("pix", pix(valor=None, endereco=COBRANCA))

    assert resultado["situacao"] == OK
    assert resultado["dados"]["tipo"] == "dinâmico" and resultado["dados"]["endereco_da_cobranca"] == COBRANCA
    assert "sem valor no código, cobrança em pix-qrcode.caixa.gov.br" in resultado["detalhe"]


@pytest.mark.parametrize("codigo, contexto, trecho", [
    (pix()[:-1] + ("0" if pix()[-1] != "0" else "1"), {}, "o código de controle (CRC) não confere"),
    (pix().replace("1520.30", "9520.30"), {}, "o código de controle (CRC) não confere"),
    (pix(), {"valor_esperado": 1250.30}, "o valor no código é R$ 1520.30, e o esperado é R$ 1250.30"),
    (pix(), {"recebedor_esperado": "Companhia de Energia do Estado"}, "o recebedor no código é CAIXA ECONOMICA FEDERAL"),
    ("00020101021126", {}, "não segue a estrutura do BR Code"),
    (campo("00", "01") + campo("59", "LOJA") + "6304ABCD", {}, "não tem a conta do Pix"),
])
def test_pix_com_problema(codigo, contexto, trecho):
    resultado = unica("pix", codigo, contexto)

    assert resultado["situacao"] == INVALIDO
    assert trecho in resultado["detalhe"]


def test_pix_com_o_valor_e_o_recebedor_esperados():
    assert unica("pix", pix(), {"valor_esperado": "1.520,30", "recebedor_esperado": "Caixa Econômica Federal"})["situacao"] == OK


# --- consultas externas ---

class Resposta:
    def __init__(self, status_code, corpo=""):
        self.status_code = status_code
        self.text = corpo if isinstance(corpo, str) else json.dumps(corpo)

    def json(self):
        return json.loads(self.text)


def jws(dados):
    parte = lambda conteudo: base64.urlsafe_b64encode(json.dumps(conteudo).encode()).decode().rstrip("=")
    return f"{parte({'alg': 'RS256'})}.{parte(dados)}.assinatura"


@pytest.fixture
def servico(monkeypatch):
    """Troca o acesso à rede por respostas prontas e registra os endereços consultados."""
    chamadas = []

    def responder(resposta):
        def _get(url, **kwargs):
            chamadas.append(url)
            if isinstance(resposta, Exception):
                raise resposta
            return resposta
        monkeypatch.setattr(consultas, "_get", _get)
        return chamadas

    def sem_rede(url, **kwargs):
        raise AssertionError(f"consulta externa inesperada: {url}")

    monkeypatch.setattr(consultas, "_get", sem_rede)
    return responder


COBRANCA_ATIVA = {
    "status": "ATIVA", "txid": "abc", "calendario": {"dataDeVencimento": "2026-10-20"},
    "valor": {"original": "1520.30", "final": "1520.30"}, "devedor": {"cnpj": "12345678000195", "nome": "EMPRESA EXEMPLO LTDA"},
}


def test_verificadores_com_consulta_externa_so_rodam_quando_permitido(servico):
    # a fixture faz qualquer acesso à rede falhar: sem a permissão, ninguém consulta
    assert list(situacoes("pix", pix(valor=None, endereco=COBRANCA))) == ["pix_estrutura"]
    assert list(situacoes("cnpj", "12.345.678/0001-95")) == ["cnpj_digito_verificador"]

    chamadas = servico(Resposta(200, jws(COBRANCA_ATIVA)))
    assert situacoes("pix", pix(valor=None, endereco=COBRANCA), consultas_externas=True) == {"pix_estrutura": OK, "pix_cobranca": OK}
    assert chamadas == [f"https://{COBRANCA}"]


def test_cobranca_do_pix_e_comparada_com_o_valor_do_pagamento(servico):
    servico(Resposta(200, jws(COBRANCA_ATIVA)))
    codigo = pix(valor=None, endereco=COBRANCA)

    def cobranca(**contexto):
        return next(r for r in verificar("pix", codigo, contexto, consultas_externas=True) if r["verificador"] == "pix_cobranca")

    confere = cobranca(valor_esperado="1.520,30", devedor_esperado="12.345.678/0001-95")
    assert confere["situacao"] == OK and confere["consulta_externa"] is True
    assert confere["dados"]["valor_final"] == "1520.30" and confere["dados"]["vencimento"] == "2026-10-20"

    diverge = cobranca(valor_esperado=1250.30)
    assert diverge["situacao"] == INVALIDO
    assert "o valor da cobrança é R$ 1520.30, e o esperado é R$ 1250.30" in diverge["detalhe"]

    assert "o devedor da cobrança não é o esperado" in cobranca(devedor_esperado="11.444.777/0001-61")["detalhe"]


@pytest.mark.parametrize("resposta, situacao, trecho", [
    (Resposta(404), INVALIDO, "Não existe cobrança no endereço"),
    (Resposta(410), NAO_VERIFICAVEL, "não está mais disponível"),
    (Resposta(503), NAO_VERIFICAVEL, "não respondeu: HTTP 503"),
    (Resposta(200, "isto não é uma cobrança"), NAO_VERIFICAVEL, "não é uma cobrança assinada"),
    (consultas.ConsultaIndisponivel("ConnectTimeout"), NAO_VERIFICAVEL, "não respondeu: ConnectTimeout"),
])
def test_cobranca_do_pix_que_nao_vem(servico, resposta, situacao, trecho):
    servico(resposta)

    resultado = next(r for r in verificar("pix", pix(valor=None, endereco=COBRANCA), consultas_externas=True) if r["verificador"] == "pix_cobranca")

    assert resultado["situacao"] == situacao
    assert trecho in resultado["detalhe"]


def test_endereco_de_cobranca_fora_dos_dominios_permitidos_nao_e_consultado(servico):
    # o endereço vem de dentro do documento: a aplicação não acessa o que não estiver na lista
    codigo = pix(valor=None, endereco="pix.banco-qualquer.com.br/cobv/123")

    resultado = next(r for r in verificar("pix", codigo, consultas_externas=True) if r["verificador"] == "pix_cobranca")
    assert resultado["situacao"] == NAO_VERIFICAVEL
    assert "pix.banco-qualquer.com.br" in resultado["detalhe"] and "não está entre os domínios" in resultado["detalhe"]

    # com o domínio na lista da configuração, a consulta acontece
    chamadas = servico(Resposta(200, jws(COBRANCA_ATIVA)))
    contexto = {"dominios_pix": ["banco-qualquer.com.br"]}
    assert situacoes("pix", codigo, contexto, consultas_externas=True)["pix_cobranca"] == OK
    assert chamadas == ["https://pix.banco-qualquer.com.br/cobv/123"]


@pytest.mark.parametrize("endereco, permitido", [
    ("pix-qrcode.caixa.gov.br/api/v2/cobv/abc", True),
    ("https://pix-qrcode.caixa.gov.br/api/v2/cobv/abc", True),
    ("sub.pix-qrcode.caixa.gov.br/abc", True),
    ("http://pix-qrcode.caixa.gov.br/abc", False),
    ("pix-qrcode.caixa.gov.br.exemplo.com/abc", False),
    ("exemplopix-qrcode.caixa.gov.br/abc", False),
    ("usuario@pix-qrcode.caixa.gov.br/abc", False),
    ("pix-qrcode.caixa.gov.br:8443/abc", False),
    ("127.0.0.1/abc", False),
    ("localhost/abc", False),
    ("192.168.0.10/pix-qrcode.caixa.gov.br", False),
])
def test_enderecos_que_a_aplicacao_aceita_consultar(endereco, permitido):
    assert consultas.endereco_permitido(endereco, consultas.DOMINIOS_PIX) is permitido


def test_pix_estatico_nao_tem_cobranca_a_consultar(servico):
    assert list(situacoes("pix", pix(), consultas_externas=True)) == ["pix_estrutura"]


CADASTRO = {"razao_social": "EXEMPLO COMERCIO DE ALIMENTOS LTDA", "descricao_situacao_cadastral": "ATIVA", "data_inicio_atividade": "2015-03-02", "municipio": "SAO PAULO", "uf": "SP"}


def test_cadastro_do_cnpj_na_receita(servico):
    chamadas = servico(Resposta(200, CADASTRO))

    resultados = {r["verificador"]: r for r in verificar("cnpj", "12.345.678/0001-95", {"razao_social_esperada": "Exemplo Comércio de Alimentos Ltda"}, consultas_externas=True)}

    assert chamadas == ["https://brasilapi.com.br/api/cnpj/v1/12345678000195"]
    assert resultados["cnpj_cadastro"]["situacao"] == OK
    assert resultados["cnpj_cadastro"]["detalhe"] == "CNPJ ativo na base da Receita: EXEMPLO COMERCIO DE ALIMENTOS LTDA."
    assert resultados["cnpj_cadastro"]["dados"]["data_inicio_atividade"] == "2015-03-02"


@pytest.mark.parametrize("resposta, contexto, situacao, trecho", [
    (Resposta(200, {**CADASTRO, "descricao_situacao_cadastral": "BAIXADA"}), {}, INVALIDO, "situação cadastral BAIXADA"),
    (Resposta(200, CADASTRO), {"razao_social_esperada": "Outra Empresa de Transportes S.A."}, INVALIDO, "não é a esperada"),
    (Resposta(404), {}, INVALIDO, "não existe na base da Receita"),
    (Resposta(429), {}, NAO_VERIFICAVEL, "não respondeu: HTTP 429"),
])
def test_cadastro_do_cnpj_com_problema(servico, resposta, contexto, situacao, trecho):
    servico(resposta)

    resultado = next(r for r in verificar("cnpj", "12.345.678/0001-95", contexto, consultas_externas=True) if r["verificador"] == "cnpj_cadastro")

    assert resultado["situacao"] == situacao
    assert trecho in resultado["detalhe"]


@pytest.mark.parametrize("valor", ["12.345.678/0001-90", "12.345.678", "12.***.***/0001-**"])
def test_cnpj_que_nao_passa_no_digito_nao_e_consultado(servico, valor):
    # a fixture faz qualquer acesso à rede falhar
    assert list(situacoes("cnpj", valor, consultas_externas=True)) == ["cnpj_digito_verificador"]


# --- endereço ---

@pytest.mark.parametrize("valor, situacao, trecho", [
    ("https://servicos.receita.fazenda.gov.br/Servicos/cnpjreva/valida.asp", OK, "órgão público"),
    ("selo.tjes.jus.br/consulta?selo=123", OK, "órgão público"),
    ("www.registrocivil.org.br/validar", OK, "entidade conhecida"),
    ("https://validador.clicksign.com/abc", OK, "entidade conhecida"),
    ("https://validacao-de-documentos.com/abc", NAO_VERIFICAVEL, "não reconhece"),
    ("https://receita.fazenda.gov.br.exemplo.com/valida", NAO_VERIFICAVEL, "não reconhece"),
    ("https://bit.ly/3abcde", NAO_VERIFICAVEL, "encurtador"),
    ("http://192.168.0.10/valida", NAO_VERIFICAVEL, "número de IP"),
    ("texto qualquer", INVALIDO, "não é um endereço"),
])
def test_dominio_do_endereco_de_verificacao(valor, situacao, trecho):
    resultado = unica("endereco", valor)

    assert resultado["situacao"] == situacao
    assert trecho in resultado["detalhe"]


# --- registro dos verificadores ---

def test_verificador_recebe_do_contexto_so_o_que_declara(monkeypatch):
    monkeypatch.setitem(registro.VERIFICADORES, "teste", {})

    @registro.verificador("teste")
    def sempre(valor, limite=10, **outros):
        return registro.ok(f"{valor} com limite {limite}")

    @registro.verificador("teste", requer=("esperado",))
    def compara(valor, esperado):
        return registro.ok("igual") if valor == esperado else registro.invalido("diferente")

    @registro.verificador("teste")
    def sem_nada_a_dizer(valor):
        return None

    @registro.verificador("teste")
    def quebrado(valor):
        raise RuntimeError("falhou")

    assert sempre.parametros == ("limite", "outros") and compara.requer == ("esperado",)

    resultados = {r["verificador"]: r for r in verificar("teste", "abc", {"limite": 5, "nao_usado": 1})}
    assert resultados["sempre"]["detalhe"] == "abc com limite 5"
    # sem a informação que requer, o verificador não roda; o que devolve None não aparece
    assert "compara" not in resultados and "sem_nada_a_dizer" not in resultados
    # e o que falha não derruba os outros
    assert resultados["quebrado"]["situacao"] == NAO_VERIFICAVEL and "RuntimeError: falhou" in resultados["quebrado"]["detalhe"]

    assert situacoes("teste", "abc", {"esperado": "abc"})["compara"] == OK
    assert situacoes("teste", "abc", {"esperado": None}).get("compara") is None

    with pytest.raises(ValueError, match="Já existe um verificador 'sempre' para o tipo 'teste'"):
        @registro.verificador("teste")
        def sempre(valor):  # noqa: F811
            return None


def test_tipo_sem_verificador_nao_tem_verificacoes():
    assert verificar("outro", "NIRE 35.300.170.563") == []
    assert verificar("qr_dados_codificados", "x") == []


def test_todo_tipo_que_a_llm_procura_tem_verificador():
    assert set(identificadores.TIPOS) <= set(identificadores.VERIFICADORES)


# --- busca ---

class FakeLLM:
    def __init__(self, identificadores_, qr_codes=()):
        self.resposta = {"identificadores": list(identificadores_), "qr_codes": list(qr_codes)}
        self.calls = []

    def call_claude(self, prompt, output_format=None, file_path=None, max_tokens=None):
        self.calls.append({"prompt": prompt, "output_format": output_format, "file_path": file_path})
        return TypeAdapter(output_format).validate_python(self.resposta)


def achado(tipo, valor, descricao="descrição", localizacao="página 1"):
    return {"tipo": tipo, "valor": valor, "descricao": descricao, "localizacao": localizacao}


MARKDOWN = "Sócio: JOAO, CPF 123.456.789-09. Empresa CNPJ 12.345.678/0001-90. Procurador CPF ***.456.789-**. NIRE 35300170563."


def test_busca_devolve_os_identificadores_do_texto_e_os_qr_codes():
    documento = DocumentoConvertido(path=Path("contrato.png"), markdown=MARKDOWN)
    llm = FakeLLM(
        [
            achado("cpf", "123.456.789-09", "CPF do sócio João"),
            achado("cpf", "123.456.789-09", "repetido"),
            achado("cnpj", "12.345.678/0001-90", "CNPJ da empresa"),
            achado("cpf", "***.456.789-**", "CPF do procurador, mascarado"),
            achado("outro", "35300170563", "NIRE da empresa"),
            # a LLM trocou um dígito ao copiar: o valor não está no texto
            achado("cpf", "123.456.789-08", "CPF copiado errado"),
        ],
        qr_codes=[{"numero": 1, "descricao": "QR Code do Pix para pagamento da guia"}],
    )
    qr_codes = [{"conteudo": pix(), "pagina": 2}, {"conteudo": "https://selo.tjes.jus.br/consulta?selo=1", "pagina": 2}]

    encontrados = busca.buscar(llm, documento, qr_codes)

    chamada = llm.calls[0]
    assert chamada["file_path"] == documento.path
    assert f"<documento>{MARKDOWN}</documento>" in chamada["prompt"]
    assert "- matricula_certidao: Matrícula de certidão de registro civil" in chamada["prompt"]
    assert "1. página 2: QR Code de Pix\n2. página 2: QR Code com endereço de internet" in chamada["prompt"]

    assert [(i["tipo"], i["valor"], i["origem"], i["no_texto"]) for i in encontrados] == [
        ("cpf", "123.456.789-09", "texto", True),
        ("cnpj", "12.345.678/0001-90", "texto", True),
        ("cpf", "***.456.789-**", "texto", True),
        ("outro", "35300170563", "texto", True),
        ("cpf", "123.456.789-08", "texto", False),
        ("pix", pix(), "qr_code", None),
        ("endereco", "https://selo.tjes.jus.br/consulta?selo=1", "qr_code", None),
    ]
    # a LLM diz para que serve o QR Code; sem a descrição dela, fica a do tipo
    assert encontrados[5]["descricao"] == "QR Code do Pix para pagamento da guia" and encontrados[5]["localizacao"] == "página 2"
    assert encontrados[6]["descricao"] == "QR Code com endereço de internet"


def test_sem_qr_code_a_prompt_avisa_e_o_pix_do_texto_nao_duplica():
    codigo = pix()
    documento = DocumentoConvertido(path=Path("guia.png"), markdown=f"Pix copia e cola: {codigo}")
    llm = FakeLLM([achado("pix", codigo, "Pix copia e cola da guia")])

    assert "Nenhum QR Code foi lido neste documento" in busca.montar_prompt(documento.markdown, [])
    # o mesmo código lido do QR e copiado do texto entra uma vez
    encontrados = busca.buscar(llm, documento, [{"conteudo": codigo, "pagina": 1}])
    assert [(i["tipo"], i["origem"]) for i in encontrados] == [("pix", "texto")]


@pytest.mark.parametrize("conteudo, tipo", [
    (pix(), "pix"),
    ("https://selo.funarpen.com.br/consulta/abc", "endereco"),
    ("www.fazenda.pr.gov.br/nf3e", "endereco"),
    ("dfe-portal.svrs.rs.gov.br/nf3e/qrcode?chNF3e=1", "endereco"),
    ("É\x9b\x05ø\x92abc123", "qr_dados_codificados"),
    ("MG-12-3-4-567890123456-A1B2C3", "qr_dados_codificados"),
    ("Certidão emitida em cartório do 1º ofício", "qr_texto"),
])
def test_tipo_do_qr_code_pelo_conteudo(conteudo, tipo):
    assert busca.classificar_qr(conteudo) == tipo


def test_qr_code_e_lido_de_imagem_e_de_pdf(tmp_path):
    conteudo = "https://selo.tjes.jus.br/consulta?selo=123456"
    qr = cv2.QRCodeEncoder.create().encode(conteudo)
    qr = cv2.resize(qr, (qr.shape[1] * 10, qr.shape[0] * 10), interpolation=cv2.INTER_NEAREST)
    pagina = Image.new("L", (1000, 1400), 255)
    pagina.paste(Image.fromarray(qr), (300, 500))
    pagina.save(tmp_path / "documento.png")
    pagina.save(tmp_path / "documento.pdf", "PDF", resolution=150, save_all=True, append_images=[pagina])

    assert busca.ler_qr_codes(tmp_path / "documento.png") == [{"conteudo": conteudo, "pagina": 1}]
    # o mesmo código nas duas páginas do PDF entra uma vez
    assert busca.ler_qr_codes(tmp_path / "documento.pdf") == [{"conteudo": conteudo, "pagina": 1}]


def test_arquivo_que_nao_abre_fica_sem_qr_code_e_a_busca_continua():
    documento = DocumentoConvertido(path=Path("nao_existe.png"), markdown="CPF 123.456.789-09")

    encontrados = busca.buscar(FakeLLM([achado("cpf", "123.456.789-09")]), documento)

    assert [i["tipo"] for i in encontrados] == ["cpf"]


def test_verificar_documento_junta_busca_e_verificadores(monkeypatch):
    monkeypatch.setattr(busca, "ler_qr_codes", lambda path: [{"conteudo": "É\x9b\x05ø\x92abc", "pagina": 1}])
    documento = DocumentoConvertido(path=Path("contrato.png"), markdown=MARKDOWN)
    llm = FakeLLM([
        achado("cpf", "123.456.789-09"), achado("cnpj", "12.345.678/0001-90"), achado("cpf", "***.456.789-**"), achado("outro", "35300170563", "NIRE"),
    ])

    encontrados = identificadores.verificar_documento(llm, documento, {"cpf_esperado": "123.456.789-09"})

    resumo = [(i["tipo"], i["tem_verificador"], [(r["verificador"], r["situacao"]) for r in i["verificacoes"]]) for i in encontrados]
    assert resumo == [
        ("cpf", True, [("cpf_digito_verificador", OK), ("cpf_esperado", OK)]),
        ("cnpj", True, [("cnpj_digito_verificador", INVALIDO)]),
        ("cpf", True, [("cpf_digito_verificador", NAO_VERIFICAVEL), ("cpf_esperado", OK)]),
        ("outro", False, []),
        ("qr_dados_codificados", False, []),
    ]
    # o dado codificado não vai para o resultado: só o tamanho
    assert encontrados[4]["valor"] == "(8 caracteres codificados)"


# --- pipeline e configuração ---

def test_pipeline_verifica_os_identificadores_dos_documentos_do_catalogo(monkeypatch):
    llm = FakeLLM([achado("cpf", "123.456.789-00")])
    monkeypatch.setattr(pipeline, "LLM", lambda: llm)
    monkeypatch.setattr(busca, "ler_qr_codes", lambda path: [])
    recebido = {}
    original = pipeline.verificar_documento

    def espia(llm_, documento, contexto, consultas_externas):
        recebido.update(contexto=contexto, consultas_externas=consultas_externas)
        return original(llm_, documento, contexto, consultas_externas)

    monkeypatch.setattr(pipeline, "verificar_documento", espia)
    resultados = [{"document_type": "rg"}, {"document_type": "outro"}]
    documentos = [DocumentoConvertido(path=Path("rg.png"), markdown="CPF 123.456.789-00"), DocumentoConvertido(path=Path("x.png"), markdown="")]
    config = {**CONFIG, "identificadores": {"consultas_externas": True, "dominios_pix": ["exemplo.com.br"]}}

    pipeline.verificar_identificadores_documentos(resultados, documentos, CATALOGO, config, contexto={"valor_esperado": 10})

    assert len(llm.calls) == 1 and "identificadores" not in resultados[1]
    assert resultados[0]["identificadores"][0]["verificacoes"][0]["situacao"] == INVALIDO
    # as opções da configuração chegam aos verificadores
    assert recebido == {"contexto": {"dominios_pix": ["exemplo.com.br"], "valor_esperado": 10}, "consultas_externas": True}


def test_opcoes_dos_identificadores_na_configuracao(tmp_path):
    # sem a seção, as consultas externas ficam desligadas
    assert fraude_.identificadores(CONFIG) == {"consultas_externas": False, "dominios_pix": ["pix-qrcode.caixa.gov.br"]}
    assert fraude_.identificadores(fraude_.carregar())["consultas_externas"] is False

    config = {**copy.deepcopy(CONFIG), "identificadores": {"consultas_externas": True, "dominios_pix": ["pix.exemplo.com.br"]}}
    fraude_.salvar(config, tmp_path / "fraude.json")
    assert fraude_.identificadores(fraude_.carregar(tmp_path / "fraude.json")) == {"consultas_externas": True, "dominios_pix": ["pix.exemplo.com.br"]}

    for invalida, mensagem in (
        ({"consultas_externas": "sim"}, "verdadeiro ou falso"),
        ({"dominios_pix": ["https://pix.exemplo.com.br/cobv"]}, "nomes de domínio"),
        ({"dominios_pix": "pix.exemplo.com.br"}, "nomes de domínio"),
    ):
        with pytest.raises(ValueError, match=mensagem):
            fraude_.validar({**CONFIG, "identificadores": invalida})


# --- tela ---

@pytest.fixture
def arquivos_da_tela(tmp_path, monkeypatch):
    caminhos = {}
    for modulo, atributo in ((catalogo_, "CATALOGO_PATH"), (fraude_, "CONFIGURACAO_PATH")):
        caminhos[atributo] = tmp_path / getattr(modulo, atributo).name
        shutil.copy(getattr(modulo, atributo), caminhos[atributo])
        monkeypatch.setattr(modulo, atributo, caminhos[atributo])
    return caminhos


def test_identificadores_aparecem_na_proposta(arquivos_da_tela):
    documento = DocumentoConvertido(path=Path("contrato.png"), markdown=MARKDOWN)
    llm = FakeLLM([achado("cpf", "123.456.789-09", "CPF do sócio"), achado("cnpj", "12.345.678/0001-90", "CNPJ da empresa"), achado("outro", "35300170563", "NIRE")])
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["documentos"] = [documento]
    at.session_state["resultados"] = [{
        "arquivo": "contrato.png", "document_type": "contrato_social",
        "classificacao": {"document_type": "contrato_social", "justificativa": "Contrato social"},
        "document_information": {},
        "identificadores": identificadores.verificar_documento(llm, documento),
    }]

    at.run()

    assert not at.exception
    assert any(legenda.value == "3 encontrados, 1 com problema." for legenda in at.caption)
    tabela = next(tabela.value for tabela in at.dataframe if "o que é" in tabela.value.columns)
    assert list(tabela["situação"]) == ["✅ confere", "❌ com problema", "— sem verificação"]
    assert list(tabela["o que é"]) == ["CPF do sócio", "CNPJ da empresa", "NIRE"]
    assert "Tipo sem verificador: só registrado." in tabela["verificações"][2]


def test_permitir_consultas_externas_pela_tela(arquivos_da_tela):
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.segmented_control(key="modo").set_value("Desenvolvedor").run()
    assert at.toggle(key="consultas_externas").value is False

    at.toggle(key="consultas_externas").set_value(True)
    at.text_input(key="dominios_pix").set_value("pix-qrcode.caixa.gov.br, Pix.Exemplo.com.br")
    next(widget for widget in at.button if widget.label == "Salvar verificação de identificadores").click()
    at.run()

    assert not at.exception
    salvo = json.loads(arquivos_da_tela["CONFIGURACAO_PATH"].read_text(encoding="utf-8"))
    assert salvo["identificadores"] == {"consultas_externas": True, "dominios_pix": ["pix-qrcode.caixa.gov.br", "pix.exemplo.com.br"]}
    # a tela lista os verificadores registrados, com as informações que cada um aceita
    verificadores_ = next(tabela.value for tabela in at.dataframe if "verificador" in tabela.value.columns)
    linha = verificadores_[verificadores_["verificador"] == "pix_cobranca"].iloc[0]
    assert linha["consulta externa"] == "sim" and "valor_esperado" in linha["informações que aceita"]
