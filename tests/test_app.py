import json
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from subscricao import catalogo as catalogo_
from subscricao.conversao import DocumentoConvertido
from subscricao.fraude import configuracao as fraude_

from test_validacoes import DADOS_RG

APP = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def catalogo_path(tmp_path, monkeypatch):
    """A tela dos testes trabalha em cópias do catálogo e da configuração de fraude do projeto."""
    path = tmp_path / "catalogo.json"
    shutil.copy(catalogo_.CATALOGO_PATH, path)
    monkeypatch.setattr(catalogo_, "CATALOGO_PATH", path)
    return path


@pytest.fixture
def fraude_path(tmp_path, monkeypatch):
    path = tmp_path / "fraude.json"
    shutil.copy(fraude_.CONFIGURACAO_PATH, path)
    monkeypatch.setattr(fraude_, "CONFIGURACAO_PATH", path)
    return path


def tela(modo="Desenvolvedor"):
    """A tela já no modo pedido. As abas de configuração só existem no modo desenvolvedor."""
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    if modo != at.segmented_control(key="modo").value:
        at.segmented_control(key="modo").set_value(modo).run()
    return at


def ler(path):
    return json.loads(path.read_text(encoding="utf-8"))


def botao(at, label):
    return next(widget for widget in at.button if widget.label == label)


def novo_tipo(at, nome, descricao):
    next(widget for widget in at.text_input if widget.label == "Label").input(nome)
    next(widget for widget in at.text_area if widget.placeholder.startswith("Título de eleitor")).input(descricao)
    botao(at, "Adicionar").click()
    return at.run()


# --- modos ---

def test_tela_abre_no_modo_analista_so_com_a_proposta(catalogo_path, fraude_path):
    at = AppTest.from_file(str(APP), default_timeout=60).run()

    assert not at.exception
    assert at.segmented_control(key="modo").value == "Analista"
    assert botao(at, "Classificar e extrair").disabled
    # nada do catálogo nem da configuração de fraude pode ser alterado neste modo
    assert not at.tabs
    assert [widget.label for widget in at.button] == ["Classificar e extrair"]
    assert [widget.label for widget in at.text_area] == ["JSON da ficha de cadastro"]
    assert not at.checkbox and not at.radio and not at.selectbox and not at.slider


def test_trocar_de_modo_nao_perde_a_proposta(catalogo_path, fraude_path):
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["documentos"] = [DocumentoConvertido(path=Path("rg.png"), markdown="## RG")]
    at.session_state["resultados"] = [{
        "arquivo": "rg.png",
        "document_type": "rg",
        "classificacao": {"document_type": "rg", "justificativa": "Carteira de identidade"},
        "document_information": {"textual": DADOS_RG},
    }]
    at.run()
    ficha = lambda: next(widget for widget in at.text_area if widget.label == "JSON da ficha de cadastro")
    ficha().set_value('{"nome": "MARIA"}').run()

    at.segmented_control(key="modo").set_value("Desenvolvedor").run()

    assert not at.exception
    assert {"Proposta", "Tipos de documento e campos", "Fraude"} <= {tab.label for tab in at.tabs}
    assert ficha().value == '{"nome": "MARIA"}'
    assert any("rg.png" in str(elemento.value) for elemento in at.markdown)

    at.segmented_control(key="modo").set_value("Analista").run()

    assert not at.exception
    assert "Fraude" not in [tab.label for tab in at.tabs]
    assert ficha().value == '{"nome": "MARIA"}'
    assert any("rg.png" in str(elemento.value) for elemento in at.markdown)


# --- catálogo ---

def test_tela_abre_com_as_abas(catalogo_path, fraude_path):
    at = tela()

    assert not at.exception
    assert [tab.label for tab in at.tabs] == ["Proposta", "Tipos de documento e campos", "Regras de negócio", "Fraude"]
    # sem documentos enviados não há o que classificar
    assert botao(at, "Classificar e extrair").disabled
    assert at.radio(key="tipo_selecionado").options == list(ler(catalogo_path))
    assert not at.warning


def test_adicionar_tipo_de_documento_pela_tela(catalogo_path, fraude_path):
    at = novo_tipo(tela(), "titulo_eleitor", "Título de eleitor")

    assert not at.exception
    assert ler(catalogo_path)["titulo_eleitor"] == {
        "descricao": "Título de eleitor",
        "risco": "MEDIO",
        "instrucoes": {"textual": "", "visual": ""},
        "instrucoes_fraude": {"orquestrador": "", "textual": "", "visual": "", "metadados": ""},
        "campos": [],
    }
    # o tipo novo já aparece selecionado para receber os campos
    assert at.radio(key="tipo_selecionado").value == "titulo_eleitor"


def test_tipo_de_documento_invalido_nao_e_salvo(catalogo_path, fraude_path):
    antes = catalogo_path.read_text(encoding="utf-8")

    at = novo_tipo(tela(), "nota fiscal", "Nota fiscal de serviço")

    assert "não é um nome válido de tipo de documento" in at.error[0].value
    assert catalogo_path.read_text(encoding="utf-8") == antes


def test_aviso_quando_o_catalogo_nao_extrai_um_campo_validado(catalogo_path, fraude_path):
    catalogo = ler(catalogo_path)
    catalogo["rg"]["campos"] = [campo for campo in catalogo["rg"]["campos"] if campo["nome"] != "cpf"]
    catalogo_path.write_text(json.dumps(catalogo, ensure_ascii=False), encoding="utf-8")

    at = tela()

    assert "validacao_cpf (rg) espera ['cpf'] do documento 'rg'." in at.warning[0].value


# --- fraude ---

def test_configurar_risco_e_instrucoes_de_fraude_do_documento(catalogo_path, fraude_path):
    antes = ler(catalogo_path)["rg"]
    at = tela()

    at.selectbox(key="risco_rg").set_value("ALTO")
    at.text_area(key="fraude_rg_orquestrador").input("Não aplique a regra de documento múltiplo a frente e verso.")
    botao(at, "Salvar").click()
    at.run()

    assert not at.exception
    depois = ler(catalogo_path)["rg"]
    assert depois["risco"] == "ALTO"
    assert depois["instrucoes_fraude"]["orquestrador"] == "Não aplique a regra de documento múltiplo a frente e verso."
    # o restante do documento não muda ao salvar
    assert depois["campos"] == antes["campos"]
    assert depois["instrucoes"] == antes["instrucoes"]
    # e o arquivo esperado, que ficou em branco, não vai para o catálogo
    assert "arquivo_esperado" not in depois


def test_configurar_o_arquivo_esperado_do_documento(catalogo_path, fraude_path):
    at = tela()

    at.multiselect(key="formatos_rg").set_value(["foto", "digitalizacao"])
    at.text_input(key="programas_rg").input("iText,  PDFium ,")
    at.checkbox(key="assinatura_rg").check()
    at.text_area(key="certificados_rg").input("AB" * 32)
    botao(at, "Salvar").click()
    at.run()

    assert not at.exception
    assert ler(catalogo_path)["rg"]["arquivo_esperado"] == {
        "formatos": ["foto", "digitalizacao"], "programas": ["iText", "PDFium"], "assinatura_digital": True, "certificados": ["ab" * 32],
    }


def test_arquivo_esperado_invalido_nao_e_salvo(catalogo_path, fraude_path):
    antes = catalogo_path.read_text(encoding="utf-8")
    at = tela()

    at.checkbox(key="assinatura_rg").check()
    at.text_area(key="certificados_rg").input("15e5b3")
    botao(at, "Salvar").click()
    at.run()

    assert "impressão digital SHA-256" in at.error[0].value
    assert catalogo_path.read_text(encoding="utf-8") == antes


def test_arquivo_esperado_do_catalogo_aparece_na_tela_e_sobrevive_ao_salvar(catalogo_path, fraude_path):
    antes = ler(catalogo_path)["ctps"]
    at = tela()

    at.radio(key="tipo_selecionado").set_value("ctps").run()

    assert at.text_input(key="programas_ctps").value == ", ".join(antes["arquivo_esperado"]["programas"])
    assert at.checkbox(key="assinatura_ctps").value is True
    assert at.text_area(key="certificados_ctps").value == "\n".join(antes["arquivo_esperado"]["certificados"])
    assert at.multiselect(key="formatos_ctps").value == []

    botao(at, "Salvar").click()
    at.run()

    assert not at.exception
    assert ler(catalogo_path)["ctps"] == antes


def test_configurar_a_severidade_das_validacoes_do_arquivo(catalogo_path, fraude_path):
    at = tela()
    assert at.selectbox(key="severidade_assinatura_integra").value == "CRÍTICA"
    assert at.selectbox(key="severidade_programa_de_edicao").value == "INFORMATIVA"

    at.selectbox(key="severidade_assinatura_esperada").set_value("BAIXA")
    at.selectbox(key="severidade_programa_esperado").set_value("INFORMATIVA")
    botao(at, "Salvar validações do arquivo").click()
    at.run()

    assert not at.exception
    forense = ler(fraude_path)["forense"]
    assert forense["validacoes"]["assinatura_esperada"] == "BAIXA"
    assert forense["validacoes"]["programa_esperado"] == "INFORMATIVA"
    assert forense["validacoes"]["assinatura_integra"] == "CRÍTICA"
    # a sensibilidade do avaliador forense não muda ao salvar as validações
    assert forense["sensibilidade"] == 8


def test_configurar_avaliadores_de_um_risco(catalogo_path, fraude_path):
    at = tela()
    assert at.checkbox(key="avaliador_MEDIO_metadados").value is False

    at.checkbox(key="avaliador_MEDIO_metadados").check()
    at.checkbox(key="avaliador_ALTO_visual").uncheck()
    botao(at, "Salvar avaliadores").click()
    at.run()

    assert not at.exception
    riscos = ler(fraude_path)["riscos"]
    assert riscos["MEDIO"]["avaliadores"] == ["textual", "visual", "metadados"]
    assert riscos["ALTO"]["avaliadores"] == ["textual", "metadados"]
    assert riscos["BAIXO"]["avaliadores"] == ["textual"]
    assert riscos["NULO"]["avaliadores"] == []


def test_configurar_regras_de_decisao(catalogo_path, fraude_path):
    antes = ler(fraude_path)["riscos"]
    at = tela()
    assert at.number_input(key="multiplicador_MEDIO").value == 0.5

    at.number_input(key="multiplicador_MEDIO").set_value(0.8)
    botao(at, "Salvar regras de decisão").click()
    at.run()

    assert not at.exception
    riscos = ler(fraude_path)["riscos"]
    assert riscos["MEDIO"]["decisao"] == {"multiplicador": 0.8, "regras": [{"criticas": 1}, {"moderadas": 3}]}
    # as regras dos outros níveis e o restante da configuração não mudam ao salvar
    assert riscos["ALTO"]["decisao"] == {"multiplicador": 1.0, "regras": [{"criticas": 1}, {"moderadas": 2}, {"moderadas": 1, "baixas": 3}]}
    assert riscos["NULO"]["decisao"] == {"multiplicador": 0.0, "regras": []}
    assert {risco: valor["avaliadores"] for risco, valor in riscos.items()} == {risco: valor["avaliadores"] for risco, valor in antes.items()}


def test_instrucoes_gerais_e_por_risco_e_previa(catalogo_path, fraude_path):
    at = tela()

    at.text_area(key="instrucoes_fraude_geral_orquestrador").input("Considere 2026 como ano corrente.")
    botao(at, "Salvar instruções").click()
    at.run()

    at.radio(key="escopo_instrucoes").set_value("MEDIO").run()
    at.text_area(key="instrucoes_fraude_MEDIO_orquestrador").input("Exija ao menos 3 flags moderadas.")
    botao(at, "Salvar instruções").click()
    at.run()

    assert not at.exception
    config = ler(fraude_path)
    assert config["instrucoes"]["orquestrador"] == "Considere 2026 como ano corrente."
    assert config["riscos"]["MEDIO"]["instrucoes"]["orquestrador"] == "Exija ao menos 3 flags moderadas."
    assert config["riscos"]["ALTO"]["instrucoes"]["orquestrador"] == ""

    # a prévia mostra o bloco que vai para o orquestrador de um documento de risco médio
    at.selectbox(key="previa_documento").set_value("contrato_social").run()
    bloco = at.code[-1].value
    assert "Para todos os documentos:\nConsidere 2026 como ano corrente." in bloco
    assert "Para documentos de risco MEDIO:\nExija ao menos 3 flags moderadas." in bloco
    # junto com a prompt completa do orquestrador desse nível de risco
    assert "documentos de MÉDIO RISCO" in bloco and "2.3) DECISÃO:" in bloco

    # e avisa quando um avaliador não roda para o risco do documento
    at.selectbox(key="previa_prompt").set_value("metadados").run()
    assert any("não roda para documentos de risco médio" in info.value for info in at.info)


def test_resultado_da_analise_de_fraude_na_proposta(catalogo_path, fraude_path):
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["documentos"] = [DocumentoConvertido(path=Path("rg.png"), markdown="## RG")]
    at.session_state["resultados"] = [{
        "arquivo": "rg.png",
        "document_type": "rg",
        "classificacao": {"document_type": "rg", "justificativa": "Carteira de identidade"},
        "document_information": {"textual": DADOS_RG},
        "fraude": {
            "nivel_risco": "BAIXO",
            "metadata": {"creator": "", "producer": ""},
            "output_Textual_Evaluator": "",
            "output_Visual_Evaluator": "",
            "output_Metadata_Evaluator": "",
            "output_Evaluator": {
                "status_fraude": "SUSPEITO", "fraud_score": 3.0, "reasoning_summary": "CPF com dígitos a menos.",
                "decisao": {"contagem": {"criticas": 1, "moderadas": 0, "baixas": 0}, "regra": "críticas ≥ 1"},
                "flags": [{"category": "TEXTO", "severity": "CRÍTICA", "source": "ORCHESTRATOR", "description": "CPF com 10 dígitos", "evidence": "frente do RG"}],
                "valid": False, "fraud_errors": "INCORRETO",
            },
        },
    }]

    at.run()

    assert not at.exception
    metricas = {metrica.label: metrica.value for metrica in at.metric}
    assert metricas == {"Situação": "🚩 Suspeito", "Fraud score": "3.0", "Nível de risco do documento": "Baixo"}
    assert any("CPF com dígitos a menos." in str(elemento.value) for elemento in at.markdown)
    assert any("Flags: 1 críticas, 0 moderadas, 0 baixas · regra atendida: críticas ≥ 1" in legenda.value for legenda in at.caption)


def test_validacoes_do_arquivo_no_resultado_da_proposta(catalogo_path, fraude_path):
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["documentos"] = [DocumentoConvertido(path=Path("ctps.pdf"), markdown="## CTPS")]
    at.session_state["resultados"] = [{
        "arquivo": "ctps.pdf",
        "document_type": "ctps",
        "classificacao": {"document_type": "ctps", "justificativa": "Carteira de trabalho digital"},
        "document_information": {},
        "fraude": {
            "nivel_risco": "ALTO",
            "metadata": {"creator": "", "producer": "Microsoft® Word 2016"},
            "forense": {
                "nivel": "BAIXO", "pontuacao": 0, "formatos": ["pdf_digital"], "alcance": "normal", "relatorio": "Formato do arquivo: pdf_digital.",
                "validacoes": [
                    {"validacao": "assinatura_integra", "titulo": "Assinatura digital íntegra", "situacao": "NAO_SE_APLICA",
                     "detalhe": "O PDF não tem assinatura digital.", "dados": {}, "severidade": "CRÍTICA", "grupo": None},
                    {"validacao": "gerado_por_ia", "titulo": "Sem marca de geração por IA", "situacao": "APROVADA",
                     "detalhe": "Nenhuma marca de geração por IA nos metadados.", "dados": {}, "severidade": "CRÍTICA", "grupo": None},
                    {"validacao": "programa_esperado", "titulo": "Programa gerador esperado para o tipo", "situacao": "REPROVADA",
                     "detalhe": "O PDF foi gerado por Microsoft® Word 2016; o tipo de documento espera iText.", "dados": {}, "severidade": "MODERADA",
                     "grupo": "arquivo_esperado"},
                ],
            },
            "output_Textual_Evaluator": "",
            "output_Visual_Evaluator": "",
            "output_Metadata_Evaluator": "",
            "output_Evaluator": {
                "status_fraude": "AUTÊNTICO", "fraud_score": 1.0, "reasoning_summary": "O arquivo não veio do emissor esperado.",
                "decisao": {"contagem": {"criticas": 0, "moderadas": 1, "baixas": 0}, "regra": None},
                "flags": [{"category": "CONTEXTO", "severity": "MODERADA", "source": "VALIDACAO_DO_ARQUIVO",
                           "description": "Arquivo fora do esperado para o tipo de documento: programa gerador fora do esperado",
                           "evidence": "O PDF foi gerado por Microsoft® Word 2016; o tipo de documento espera iText."}],
                "valid": True, "fraud_errors": "OK",
            },
        },
    }]

    at.run()

    assert not at.exception
    assert any("Validações do arquivo: 2 conferidas, 1 reprovada(s)." in legenda.value for legenda in at.caption)
    tabela = next(tabela.value for tabela in at.dataframe if "validação" in tabela.value.columns)
    # a reprovada vem primeiro, com a severidade da flag que ela gera
    assert tabela.to_dict("records")[0] == {
        "situação": "❌ reprovada", "validação": "Programa gerador esperado para o tipo", "flag": "moderada",
        "detalhe": "O PDF foi gerado por Microsoft® Word 2016; o tipo de documento espera iText.",
    }
    assert list(tabela["situação"]) == ["❌ reprovada", "✅ aprovada", "— não se aplica"]


