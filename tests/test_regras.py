import sys

import pytest

from subscricao import validacoes
from subscricao.validacoes import FICHA_CADASTRO, VALIDACOES, carregar_validacoes, validate
from subscricao.validacoes.ValidateDocument import validacao
from subscricao.validacoes.regras import booleano, data_igual, data_recente, igualdade, similaridade

from test_validacoes import DADOS_CONTRATO_SOCIAL, DADOS_RG, FICHA, erro, resultados


@pytest.fixture
def cnh(monkeypatch):
    """Tipo de documento usado só nos testes, com os mesmos dados do RG."""
    monkeypatch.setitem(VALIDACOES, "cnh", {})
    return {FICHA_CADASTRO: FICHA, "cnh": DADOS_RG}


# --- regras prontas ---

def test_regra_pronta_registra_uma_validacao_com_o_nome_do_campo(cnh):
    similaridade("cnh", "nome", limiar=90)
    igualdade("cnh", "cpf")
    data_igual("cnh", "data_nascimento")
    data_recente("cnh", "data_expedicao", anos=10)

    assert list(VALIDACOES["cnh"]) == ["validacao_nome", "validacao_cpf", "validacao_data_nascimento", "validacao_data_expedicao"]
    assert VALIDACOES["cnh"]["validacao_nome"].campos == {"ficha_cadastro": ["nome"], "cnh": ["nome"]}
    assert VALIDACOES["cnh"]["validacao_data_expedicao"].campos == {"cnh": ["data_expedicao"]}

    validations = validate("cnh", cnh)["subscription_validations"]
    assert all(v["valid"] for v in validations.values())


def test_regras_prontas_dao_o_mesmo_resultado_das_validacoes_da_referencia(cnh):
    similaridade("cnh", "nome", limiar=90)
    igualdade("cnh", "cpf")
    data_igual("cnh", "data_nascimento")
    data_recente("cnh", "data_expedicao", anos=10)

    for dados in (
        DADOS_RG,
        {**DADOS_RG, "nome": "Carlos Pereira Lima", "cpf": "987.654.321-00", "data_nascimento": "15-01-1990"},
        {**DADOS_RG, "data_nascimento": "31-02-1990", "data_expedicao": "Not Found"},
        {**DADOS_RG, "data_expedicao": "01-01-2001"},
    ):
        da_referencia = validate("rg", {FICHA_CADASTRO: FICHA, "rg": dados})["subscription_validations"]
        das_regras = validate("cnh", {FICHA_CADASTRO: FICHA, "cnh": dados})["subscription_validations"]

        for nome in ("validacao_nome", "validacao_cpf", "validacao_data_nascimento", "validacao_data_expedicao"):
            assert das_regras[nome] == da_referencia[nome], nome


def test_regras_de_cnpj_e_booleano_dao_o_mesmo_resultado_do_contrato_social(monkeypatch):
    monkeypatch.setitem(VALIDACOES, "estatuto", {})
    igualdade("estatuto", "cnpj", caracteres=r'[a-zA-Z0-9]')
    similaridade("estatuto", "razao_social", limiar=80)
    booleano("estatuto", "ha_assinatura", confianca="confianca_assinatura", descricao="descricao_assinatura")
    booleano("estatuto", "sem_valor_certidao", confianca="confianca_sem_valor_certidao", descricao="descricao_sem_valor_certidao", esperado=False)
    booleano("estatuto", "ha_quadro_societario", confianca="confianca_quadro_societario", descricao="descricao_quadro_societario")

    for dados in (
        DADOS_CONTRATO_SOCIAL,
        {**DADOS_CONTRATO_SOCIAL, "cnpj": "99.999.999/0001-99", "ha_assinatura": False, "sem_valor_certidao": True, "ha_quadro_societario": False},
    ):
        da_referencia = resultados(validate("contrato_social", {FICHA_CADASTRO: FICHA, "contrato_social": dados}))
        output = validate("estatuto", {FICHA_CADASTRO: FICHA, "estatuto": dados})
        das_regras = resultados(output)

        # a regra booleano é visual por padrão; as demais são textuais
        assert {nome for nome, v in das_regras.items() if v["tipo"] == "visual"} == {
            "validacao_ha_assinatura", "validacao_sem_valor_certidao", "validacao_ha_quadro_societario",
        }
        for nome in das_regras:
            assert das_regras[nome] == da_referencia[nome], nome


def test_regra_pronta_espera_a_ficha_de_cadastro(cnh):
    igualdade("cnh", "cpf")
    data_recente("cnh", "data_expedicao", anos=10)

    validations = validate("cnh", {"cnh": DADOS_RG})["subscription_validations"]

    assert erro(validations["validacao_cpf"]) == "ESPERAR_DOCUMENTOS"
    assert validations["validacao_data_expedicao"]["valid"] is True


def test_validacao_com_nome_repetido_no_mesmo_documento(cnh):
    igualdade("cnh", "cpf")

    with pytest.raises(ValueError, match="Já existe uma validação 'validacao_cpf' para o documento 'cnh'"):
        @validacao("cnh", campos={"cnh": ["cpf"]})
        def validacao_cpf(cnh):
            return {"valid": True}


# --- arquivos de validação ---

@pytest.fixture
def pasta_de_validacoes(tmp_path, monkeypatch):
    """Acrescenta uma pasta temporária às pastas de onde as validações são carregadas."""
    monkeypatch.setattr(validacoes, "__path__", [*validacoes.__path__, str(tmp_path)])
    yield tmp_path

    monkeypatch.undo()
    for name in [name for name in sys.modules if name.startswith("subscricao.validacoes.") and name.endswith("_teste_validate")]:
        del sys.modules[name]
    carregar_validacoes()


def test_arquivo_novo_e_carregado_sem_registro_manual(pasta_de_validacoes):
    (pasta_de_validacoes / "cnh_teste_validate.py").write_text(
        'from .regras import igualdade, similaridade\n'
        'from .ValidateDocument import validacao\n'
        '\n'
        'similaridade("cnh", "nome", limiar=90)\n'
        'igualdade("cnh", "cpf")\n'
        '\n'
        '@validacao("cnh", campos={"cnh": ["numero_rg"]})\n'
        'def validacao_numero(cnh):\n'
        '    return {"valid": len(cnh.numero_rg) > 5, "target": "numero_rg"}\n',
        encoding="utf-8",
    )

    assert carregar_validacoes(apenas_se_alterado=True) is True

    assert list(VALIDACOES["cnh"]) == ["validacao_nome", "validacao_cpf", "validacao_numero"]
    validations = validate("cnh", {FICHA_CADASTRO: FICHA, "cnh": DADOS_RG})["subscription_validations"]
    assert all(v["valid"] for v in validations.values())
    # as validações dos outros arquivos continuam registradas, uma vez só
    assert len(VALIDACOES["rg"]) == 5
    assert len(VALIDACOES["contrato_social"]) == 9
    # sem mudança nos arquivos, nada é recarregado
    assert carregar_validacoes(apenas_se_alterado=True) is False


def test_arquivo_alterado_e_recarregado(pasta_de_validacoes):
    arquivo = pasta_de_validacoes / "cnh_teste_validate.py"
    arquivo.write_text('from .regras import igualdade, similaridade\n\nsimilaridade("cnh", "nome", limiar=90)\nigualdade("cnh", "cpf")\n', encoding="utf-8")
    carregar_validacoes()
    # similaridade de 96,67 com o nome extraído
    documentos = {FICHA_CADASTRO: {**FICHA, "nome": "MARIA DA SILVA SOUSA"}, "cnh": DADOS_RG}
    assert validate("cnh", documentos)["subscription_validations"]["validacao_nome"]["valid"] is True

    # limiar mais rígido e uma regra a menos
    arquivo.write_text('from .regras import similaridade\n\nsimilaridade("cnh", "nome", limiar=99.5)\n', encoding="utf-8")

    assert carregar_validacoes(apenas_se_alterado=True) is True
    assert list(VALIDACOES["cnh"]) == ["validacao_nome"]
    assert validate("cnh", documentos)["subscription_validations"]["validacao_nome"]["valid"] is False

    arquivo.unlink()
    assert carregar_validacoes(apenas_se_alterado=True) is True
    assert "cnh" not in VALIDACOES


def test_regras_prontas_sao_recarregadas_antes_dos_arquivos_de_validacao(monkeypatch):
    recarregados = []
    reload = validacoes.importlib.reload
    monkeypatch.setattr(validacoes.importlib, "reload", lambda module: recarregados.append(module.__name__.rsplit(".", 1)[-1]) or reload(module))

    carregar_validacoes()

    assert recarregados == ["regras", "contrato_social_validate", "rg_validate"]
    assert len(VALIDACOES["rg"]) == 5
    assert len(VALIDACOES["contrato_social"]) == 9


def test_erro_em_um_arquivo_de_validacao_aparece_ao_carregar(pasta_de_validacoes):
    (pasta_de_validacoes / "cnh_teste_validate.py").write_text('from .regras import similaridade\n\nsimilaridade("cnh", "nome"\n', encoding="utf-8")

    with pytest.raises(SyntaxError):
        carregar_validacoes(apenas_se_alterado=True)

    # enquanto o arquivo não for corrigido, a carga é tentada de novo
    with pytest.raises(SyntaxError):
        carregar_validacoes(apenas_se_alterado=True)
