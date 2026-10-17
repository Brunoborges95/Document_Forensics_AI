import base64
import copy
import dataclasses
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import TypeAdapter

from subscricao import catalogo as catalogo_, extracao, llm as llm_module, pipeline
from subscricao.conversao import DocumentoConvertido
from subscricao.llm import LLM
from subscricao.validacoes.ValidateDocument import FICHA_CADASTRO, VALIDACOES

from test_validacoes import (
    DADOS_CONTRATO_SOCIAL_TEXTUAL,
    DADOS_CONTRATO_SOCIAL_VISUAL,
    DADOS_RG,
    FICHA,
    erro,
    resultados,
)

TIPO_POR_VALOR = {str: "texto", bool: "booleano", int: "inteiro", dict: "endereco", list: "lista_nome_cpf"}


def campos_de(dados, extracao):
    return [
        {"nome": nome, "tipo": TIPO_POR_VALOR[type(valor)], "extracao": extracao, "descricao": f"Descrição de {nome}"}
        for nome, valor in dados.items()
    ]


# catálogo fixo dos testes, com os mesmos campos do catálogo do projeto (que o frontend pode alterar)
CATALOGO = {
    "rg": {
        "descricao": "Carteira de identidade",
        "instrucoes": {"textual": "O documento é o RG.\nO CPF tem 11 dígitos.", "visual": ""},
        "campos": campos_de(DADOS_RG, "textual"),
    },
    "contrato_social": {
        "descricao": "Contrato social de uma empresa",
        "instrucoes": {"textual": "O documento é um contrato social.", "visual": "Procure assinaturas e selos."},
        "campos": campos_de(DADOS_CONTRATO_SOCIAL_TEXTUAL, "textual") + campos_de(DADOS_CONTRATO_SOCIAL_VISUAL, "visual"),
    },
}


class FakeLLM:
    """Devolve as respostas na ordem, já na estrutura pedida em cada chamada."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.calls = []

    def call_claude(self, prompt, output_format, file_path=None):
        self.calls.append({"prompt": prompt, "output_format": output_format, "file_path": file_path})
        return TypeAdapter(output_format).validate_python(self.respostas.pop(0))


def documento(path="contrato.pdf"):
    return DocumentoConvertido(path=Path(path), markdown="## TEXTO DO DOCUMENTO")


def campos(estrutura):
    return {field.name for field in dataclasses.fields(estrutura)}


# --- catálogo ---

def test_catalogo_do_projeto_atende_as_validacoes():
    catalogo = catalogo_.carregar()

    catalogo_.validar(catalogo)
    # todo campo que uma validação espera é extraído do documento correspondente
    assert catalogo_.pendencias(catalogo) == []
    assert set(VALIDACOES) <= set(catalogo)


def test_estruturas_sao_montadas_a_partir_do_catalogo():
    estruturas_rg = catalogo_.estruturas("rg", CATALOGO["rg"])
    estruturas_contrato = catalogo_.estruturas("contrato_social", CATALOGO["contrato_social"])

    # só existem as extrações que têm campos
    assert set(estruturas_rg) == {"textual"}
    assert set(estruturas_contrato) == {"textual", "visual"}
    assert campos(estruturas_rg["textual"]) == set(DADOS_RG)
    assert campos(estruturas_contrato["visual"]) == set(DADOS_CONTRATO_SOCIAL_VISUAL)

    schema = TypeAdapter(estruturas_contrato["visual"]).json_schema()
    assert schema["properties"]["ha_assinatura"] == {"description": "Descrição de ha_assinatura", "title": "Ha Assinatura", "type": "boolean"}
    assert schema["properties"]["confianca_assinatura"]["type"] == "integer"
    # tipos compostos trazem a própria estrutura
    schema = TypeAdapter(estruturas_contrato["textual"]).json_schema()
    assert set(schema["$defs"]["Endereco"]["properties"]) == {"cep", "rua", "numero", "complemento", "bairro", "cidade", "estado"}


def test_pendencias_quando_o_catalogo_deixa_de_extrair_um_campo_validado():
    catalogo = copy.deepcopy(CATALOGO)
    catalogo["rg"]["campos"] = [campo for campo in catalogo["rg"]["campos"] if campo["nome"] != "cpf"]
    del catalogo["contrato_social"]

    pendencias = catalogo_.pendencias(catalogo)

    assert "validacao_cpf (rg) espera ['cpf'] do documento 'rg'." in pendencias
    assert any(pendencia.startswith("validacao_cnpj (contrato_social)") for pendencia in pendencias)
    assert not any(pendencia.startswith("validacao_nome ") for pendencia in pendencias)


@pytest.mark.parametrize("alteracao, mensagem", [
    (lambda c: c.update({"nota fiscal": {"descricao": "Nota", "campos": []}}), "'nota fiscal' não é um nome válido de tipo"),
    (lambda c: c.update({"outro": {"descricao": "Outro", "campos": []}}), "'outro' não é um nome válido de tipo"),
    (lambda c: c.update({"ficha_cadastro": {"descricao": "Ficha", "campos": []}}), "'ficha_cadastro' não é um nome válido de tipo"),
    (lambda c: c["rg"].update(descricao="  "), "rg: a descrição é usada na classificação"),
    (lambda c: c["rg"]["campos"].append({"nome": "data de emissão", "tipo": "texto", "extracao": "textual"}), "'data de emissão' não é um nome válido de campo"),
    (lambda c: c["rg"]["campos"].append({"nome": "cpf", "tipo": "texto", "extracao": "visual"}), "o campo 'cpf' está repetido"),
    (lambda c: c["rg"]["campos"].append({"nome": "foto", "tipo": "imagem", "extracao": "visual"}), "rg.foto: tipo 'imagem' desconhecido"),
    (lambda c: c["rg"]["campos"].append({"nome": "foto", "tipo": "texto", "extracao": "ocr"}), "rg.foto: extração 'ocr' desconhecida"),
])
def test_catalogo_invalido(alteracao, mensagem):
    catalogo = copy.deepcopy(CATALOGO)
    alteracao(catalogo)

    with pytest.raises(ValueError, match=mensagem):
        catalogo_.validar(catalogo)


def test_salvar_e_carregar_o_catalogo(tmp_path):
    path = tmp_path / "catalogo.json"
    catalogo = copy.deepcopy(CATALOGO)
    catalogo["cnh"] = {
        "descricao": "Carteira Nacional de Habilitação",
        "instrucoes": {"textual": "", "visual": ""},
        "campos": [{"nome": "categoria", "tipo": "texto", "extracao": "textual", "descricao": "Categoria da habilitação"}],
    }

    catalogo_.salvar(catalogo, path)

    assert catalogo_.carregar(path) == catalogo
    # um catálogo inválido não substitui o arquivo
    catalogo["cnh"]["campos"].append({"nome": "categoria", "tipo": "texto", "extracao": "textual"})
    with pytest.raises(ValueError):
        catalogo_.salvar(catalogo, path)
    assert len(catalogo_.carregar(path)["cnh"]["campos"]) == 1


# --- prompt ---

def test_prompt_e_montada_com_instrucoes_e_estrutura_do_catalogo():
    estrutura = catalogo_.estruturas("rg", CATALOGO["rg"])["textual"]

    prompt = extracao.build_prompt("textual", CATALOGO["rg"]["instrucoes"]["textual"], estrutura, "## MARKDOWN")

    assert "Responda 'Not Found' se a informação não estiver disponível." in prompt
    assert "O documento é o RG.\nO CPF tem 11 dígitos.\n<documento>## MARKDOWN</documento>" in prompt
    estrutura_na_prompt = json.loads(prompt.split("<estrutura>")[1].split("</estrutura>")[0])
    assert estrutura_na_prompt["properties"]["nome_mae"] == {"description": "Descrição de nome_mae", "title": "Nome Mae", "type": "string"}


# --- extração ---

def test_rg_passa_apenas_pela_extracao_textual():
    llm = FakeLLM(DADOS_RG)

    document_information = extracao.extrair(llm, "rg", documento("rg.jpeg"), CATALOGO)

    assert document_information == {"textual": DADOS_RG}
    assert len(llm.calls) == 1
    assert llm.calls[0]["file_path"] is None
    assert "<documento>## TEXTO DO DOCUMENTO</documento>" in llm.calls[0]["prompt"]


def test_contrato_social_passa_pela_extracao_textual_e_pela_visual():
    llm = FakeLLM(DADOS_CONTRATO_SOCIAL_TEXTUAL, DADOS_CONTRATO_SOCIAL_VISUAL)
    doc = documento()

    document_information = extracao.extrair(llm, "contrato_social", doc, CATALOGO)

    assert document_information == {"textual": DADOS_CONTRATO_SOCIAL_TEXTUAL, "visual": DADOS_CONTRATO_SOCIAL_VISUAL}

    chamada_textual, chamada_visual = llm.calls
    # a extração textual recebe só o markdown; a visual recebe o markdown e o próprio arquivo
    assert chamada_textual["file_path"] is None
    assert chamada_visual["file_path"] == doc.path
    assert "O documento é um contrato social." in chamada_textual["prompt"]
    assert "Procure assinaturas e selos." in chamada_visual["prompt"]
    assert "<documento>## TEXTO DO DOCUMENTO</documento>" in chamada_visual["prompt"]
    assert campos(chamada_textual["output_format"]) == set(DADOS_CONTRATO_SOCIAL_TEXTUAL)
    assert campos(chamada_visual["output_format"]) == set(DADOS_CONTRATO_SOCIAL_VISUAL)


def test_documento_fora_do_catalogo():
    llm = FakeLLM()

    assert extracao.extrair(llm, "outro", documento(), CATALOGO) == {}
    assert llm.calls == []


def test_tipo_de_documento_criado_no_catalogo_e_classificado_e_extraido(monkeypatch):
    catalogo = copy.deepcopy(CATALOGO)
    catalogo["cnh"] = {
        "descricao": "Carteira Nacional de Habilitação",
        "instrucoes": {"textual": "O documento é uma CNH.", "visual": ""},
        "campos": [
            {"nome": "categoria", "tipo": "texto", "extracao": "textual", "descricao": "Categoria da habilitação"},
            {"nome": "ha_foto", "tipo": "booleano", "extracao": "visual", "descricao": "Há foto do titular?"},
        ],
    }
    llm = FakeLLM({"document_type": "cnh", "justificativa": "É uma CNH"}, {"categoria": "AB"}, {"ha_foto": True})
    monkeypatch.setattr(pipeline, "LLM", lambda: llm)

    [resultado] = pipeline.processar([documento("cnh.png")], FICHA, catalogo)

    schema = TypeAdapter(llm.calls[0]["output_format"]).json_schema()
    assert schema["properties"]["document_type"]["enum"] == ["rg", "contrato_social", "cnh", "outro"]
    assert "- cnh: Carteira Nacional de Habilitação" in llm.calls[0]["prompt"]
    assert resultado["document_information"] == {"textual": {"categoria": "AB"}, "visual": {"ha_foto": True}}
    # ainda não há validações escritas para o tipo novo
    assert resultado["dados_regras_subscricao"] == {"subscription_validations": {}}


# --- arquivo enviado à extração visual ---

def test_arquivo_pdf_e_enviado_como_documento(tmp_path):
    path = tmp_path / "contrato.PDF"
    path.write_bytes(b"%PDF-1.4 conteudo")

    content = LLM().file_content(path)

    assert content["type"] == "document"
    assert content["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(content["source"]["data"]) == b"%PDF-1.4 conteudo"


@pytest.mark.parametrize("nome, formato, media_type", [
    ("rg.jpg", "JPEG", "image/jpeg"),
    ("rg.jpeg", "JPEG", "image/jpeg"),
    ("rg.png", "PNG", "image/png"),
])
def test_arquivo_de_imagem_e_enviado_sem_alteracao(tmp_path, nome, formato, media_type):
    path = tmp_path / nome
    Image.new("RGB", (40, 30), "white").save(path, format=formato)

    content = LLM().file_content(path)

    assert content["type"] == "image"
    assert content["source"]["media_type"] == media_type
    assert base64.standard_b64decode(content["source"]["data"]) == path.read_bytes()


def test_imagem_em_outro_formato_e_convertida_para_jpeg(tmp_path):
    path = tmp_path / "rg.bmp"
    Image.new("RGBA", (40, 30), "white").save(path, format="BMP")

    content = LLM().file_content(path)

    assert content["source"]["media_type"] == "image/jpeg"
    assert Image.open(BytesIO(base64.standard_b64decode(content["source"]["data"]))).format == "JPEG"


def test_imagem_acima_do_limite_e_comprimida(tmp_path, monkeypatch):
    limite = 0.1 * 1024 * 1024
    monkeypatch.setattr(llm_module, "MAX_IMAGE_SIZE_MB", 0.1)
    path = tmp_path / "rg.png"
    Image.effect_noise((600, 600), 80).save(path, format="PNG")
    assert path.stat().st_size > limite

    content = LLM().file_content(path)

    assert content["source"]["media_type"] == "image/jpeg"
    assert len(base64.standard_b64decode(content["source"]["data"])) <= limite


# --- pipeline ---

CLASSIFICACAO_RG = {"document_type": "rg", "justificativa": "Carteira de identidade"}
CLASSIFICACAO_CONTRATO_SOCIAL = {"document_type": "contrato_social", "justificativa": "Contrato social"}


def test_pipeline_rg(monkeypatch):
    llm = FakeLLM(CLASSIFICACAO_RG, DADOS_RG)
    monkeypatch.setattr(pipeline, "LLM", lambda: llm)

    [resultado] = pipeline.processar([documento("rg.jpeg")], FICHA, CATALOGO)

    assert resultado["arquivo"] == "rg.jpeg"
    assert resultado["document_type"] == "rg"
    assert resultado["document_information"] == {"textual": DADOS_RG}
    assert set(resultado["dados_regras_subscricao"]) == {"subscription_validations"}
    assert all(v["valid"] for v in resultados(resultado["dados_regras_subscricao"]).values())
    # a classificação recebe só o markdown e restringe a resposta aos tipos do catálogo
    assert llm.calls[0]["file_path"] is None
    schema = TypeAdapter(llm.calls[0]["output_format"]).json_schema()
    assert schema["properties"]["document_type"]["enum"] == ["rg", "contrato_social", "outro"]


def test_pipeline_com_varios_documentos(monkeypatch):
    llm = FakeLLM(
        CLASSIFICACAO_RG, DADOS_RG,
        CLASSIFICACAO_CONTRATO_SOCIAL, DADOS_CONTRATO_SOCIAL_TEXTUAL, DADOS_CONTRATO_SOCIAL_VISUAL,
    )
    monkeypatch.setattr(pipeline, "LLM", lambda: llm)
    disponiveis = {}
    monkeypatch.setattr(pipeline, "validate", lambda document_type, documentos: disponiveis.setdefault(document_type, documentos))

    resultado_rg, resultado_contrato = pipeline.processar([documento("rg.jpeg"), documento("contrato.pdf")], FICHA, CATALOGO)

    assert [resultado_rg["document_type"], resultado_contrato["document_type"]] == ["rg", "contrato_social"]
    assert set(resultado_contrato["document_information"]) == {"textual", "visual"}
    # cada documento é validado enxergando a ficha de cadastro e todos os documentos da proposta,
    # com os campos das extrações textual e visual juntos
    esperado = {
        FICHA_CADASTRO: FICHA,
        "rg": DADOS_RG,
        "contrato_social": {**DADOS_CONTRATO_SOCIAL_TEXTUAL, **DADOS_CONTRATO_SOCIAL_VISUAL},
    }
    assert disponiveis == {"rg": esperado, "contrato_social": esperado}


def test_pipeline_contrato_social(monkeypatch):
    llm = FakeLLM(CLASSIFICACAO_CONTRATO_SOCIAL, DADOS_CONTRATO_SOCIAL_TEXTUAL, DADOS_CONTRATO_SOCIAL_VISUAL)
    monkeypatch.setattr(pipeline, "LLM", lambda: llm)

    [resultado] = pipeline.processar([documento()], FICHA, CATALOGO)

    validacoes = resultado["dados_regras_subscricao"]
    assert len(validacoes["subscription_validations"]) == 9
    assert all(v["valid"] for v in resultados(validacoes).values())


def test_pipeline_documento_de_outro_tipo(monkeypatch):
    llm = FakeLLM({"document_type": "outro", "justificativa": "É uma nota fiscal"}, CLASSIFICACAO_RG, DADOS_RG)
    monkeypatch.setattr(pipeline, "LLM", lambda: llm)

    outro, rg = pipeline.processar([documento("nota.pdf"), documento("rg.jpeg")], FICHA, CATALOGO)

    # o documento não reconhecido não é extraído nem validado, e não interrompe os demais
    assert outro == {
        "arquivo": "nota.pdf",
        "document_type": "outro",
        "classificacao": {"document_type": "outro", "justificativa": "É uma nota fiscal"},
    }
    assert all(v["valid"] for v in resultados(rg["dados_regras_subscricao"]).values())


def test_validacao_pode_ser_repetida_sem_chamar_a_llm(monkeypatch):
    llm = FakeLLM(CLASSIFICACAO_RG, DADOS_RG)
    monkeypatch.setattr(pipeline, "LLM", lambda: llm)

    extraidos = pipeline.extrair_documentos([documento("rg.jpeg")], CATALOGO)
    assert "dados_regras_subscricao" not in extraidos[0]

    # sem a ficha de cadastro, só roda o que não depende dela
    [resultado] = pipeline.validar_documentos(extraidos)
    validations = resultado["dados_regras_subscricao"]["subscription_validations"]
    assert validations["validacao_data_expedicao"]["valid"] is True
    assert erro(validations["validacao_cpf"]) == "ESPERAR_DOCUMENTOS"

    # com a ficha, as mesmas extrações são validadas de novo
    [resultado] = pipeline.validar_documentos(extraidos, {**FICHA, "cpf": "000.000.000-00"})
    validations = resultado["dados_regras_subscricao"]["subscription_validations"]
    assert validations["validacao_cpf"]["valid"] is False
    assert validations["validacao_nome"]["valid"] is True
    assert len(llm.calls) == 2
