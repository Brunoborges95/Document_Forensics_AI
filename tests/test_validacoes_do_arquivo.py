import copy
import datetime
import hashlib

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from subscricao import catalogo as catalogo_
from subscricao.conversao import DocumentoConvertido
from subscricao.fraude import configuracao as fraude_
from subscricao.fraude.analise import analisar_fraude
from subscricao.fraude.forense import validacoes as v

from test_fraude import CATALOGO, CONFIG, MODERADA, METADADOS_SUSPEITO, TEXTUAL_CONSISTENTE, VISUAL_LEGITIMO, FakeLLM, orquestrador, pdf_em_branco

AGORA = datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.timezone.utc)

ITEXT = {"producer": "iText 2.1.7 by 1T3XT", "creator": "Carteira Digital"}
WORD = {"producer": "Microsoft® Word 2016", "creator": "Microsoft® Word 2016"}


def resultados(path, formatos=("pdf_digital",), metadados=None, esperado=None, severidades=None):
    return v.validar(v.Arquivo(path, formatos, metadados, esperado, agora=AGORA), severidades)


def resultado(nome, path, **argumentos):
    return next(r for r in resultados(path, **argumentos) if r["validacao"] == nome)


def situacao(nome, path, **argumentos):
    return resultado(nome, path, **argumentos)["situacao"]


@pytest.fixture
def pdf(tmp_path):
    return pdf_em_branco(tmp_path / "documento.pdf")


@pytest.fixture
def imagem(tmp_path):
    path = tmp_path / "documento.png"
    Image.new("RGB", (40, 30), "white").save(path)
    return path


@pytest.fixture(scope="module")
def assinados(tmp_path_factory):
    """Um PDF assinado com um certificado criado para o teste, e o mesmo PDF alterado depois de assinado."""
    pytest.importorskip("pyhanko")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers

    pasta = tmp_path_factory.mktemp("assinados")
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # o ICP-Brasil escreve o CNPJ depois do nome; ele não deve aparecer no resultado
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EMISSOR DE TESTE:12345678000199")])
    hoje = datetime.datetime.now(datetime.timezone.utc)
    certificado = (
        x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(hoje - datetime.timedelta(days=1)).not_valid_after(hoje + datetime.timedelta(days=30)).sign(chave, hashes.SHA256())
    )
    (pasta / "chave.pem").write_bytes(chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (pasta / "certificado.pem").write_bytes(certificado.public_bytes(serialization.Encoding.PEM))

    limpo = pdf_em_branco(pasta / "limpo.pdf")
    signer = signers.SimpleSigner.load(str(pasta / "chave.pem"), str(pasta / "certificado.pem"))
    with open(limpo, "rb") as entrada:
        assinado = signers.sign_pdf(IncrementalPdfFileWriter(entrada, strict=False), signers.PdfSignatureMetadata(field_name="Assinatura"), signer=signer).getvalue()
    (pasta / "assinado.pdf").write_bytes(assinado)
    # troca a largura da página, que está no trecho coberto pela assinatura
    assert assinado.find(b"595") < assinado.find(b"/ByteRange")
    (pasta / "alterado.pdf").write_bytes(assinado.replace(b"595", b"596", 1))

    return {
        "assinado": pasta / "assinado.pdf", "alterado": pasta / "alterado.pdf",
        "certificado": hashlib.sha256(certificado.public_bytes(serialization.Encoding.DER)).hexdigest(),
    }


# --- assinatura digital ---

def test_assinatura_integra(assinados):
    integra = resultado("assinatura_integra", assinados["assinado"])

    assert integra["situacao"] == v.APROVADA
    assert "1 assinatura(s) íntegra(s): EMISSOR DE TESTE" in integra["detalhe"]
    # o resultado traz o certificado, que é o que o catálogo lista como aceito
    assert integra["dados"]["assinaturas"][0]["certificado"] == assinados["certificado"]
    assert integra["dados"]["assinaturas"][0]["assinante"] == "EMISSOR DE TESTE"
    assert v.flags(resultados(assinados["assinado"])) == []


def test_pdf_alterado_depois_de_assinado(assinados):
    validacoes = resultados(assinados["alterado"])
    quebrada = next(r for r in validacoes if r["validacao"] == "assinatura_integra")

    assert quebrada["situacao"] == v.REPROVADA
    assert "foi alterado depois da assinatura" in quebrada["detalhe"]
    assert v.flags(validacoes) == [{
        "category": "CONTEXTO", "severity": "CRÍTICA", "source": "VALIDACAO_DO_ARQUIVO",
        "description": "Assinatura digital quebrada: o conteúdo foi alterado depois de assinado", "evidence": quebrada["detalhe"],
    }]


def test_sem_assinatura_nao_ha_integridade_a_conferir(pdf, imagem):
    assert situacao("assinatura_integra", pdf) == v.NAO_SE_APLICA
    assert situacao("assinatura_integra", imagem, formatos=("foto",)) == v.NAO_SE_APLICA


def test_assinatura_esperada_para_o_tipo(pdf, imagem, assinados):
    espera = {"assinatura_digital": True}

    assert situacao("assinatura_esperada", pdf) == v.NAO_SE_APLICA
    sem_assinatura = resultado("assinatura_esperada", pdf, esperado=espera)
    assert sem_assinatura["situacao"] == v.REPROVADA and "não é o arquivo original do emissor" in sem_assinatura["detalhe"]
    assert situacao("assinatura_esperada", assinados["assinado"], esperado=espera) == v.APROVADA
    # a imagem não tem como carregar a assinatura: quem a pega é o formato esperado
    assert situacao("assinatura_esperada", imagem, formatos=("foto",), esperado=espera) == v.NAO_SE_APLICA
    # nem o papel digitalizado e guardado em PDF, como a carteira de trabalho física
    digitalizado = resultado("assinatura_esperada", pdf, formatos=("digitalizacao", "foto"), esperado=espera)
    assert digitalizado["situacao"] == v.NAO_SE_APLICA and "só imagem" in digitalizado["detalhe"]
    # já o PDF que tem página gerada por software é conferido
    assert situacao("assinatura_esperada", pdf, formatos=("digitalizacao", "pdf_digital"), esperado=espera) == v.REPROVADA
    assert situacao("assinatura_esperada", pdf, formatos=(), esperado=espera) == v.NAO_CONFERIDA


def test_assinatura_precisa_ser_de_um_certificado_aceito(assinados):
    aceito = {"assinatura_digital": True, "certificados": [assinados["certificado"].upper()]}
    outro = {"assinatura_digital": True, "certificados": ["ab" * 32]}

    assert situacao("assinatura_esperada", assinados["assinado"], esperado=aceito) == v.APROVADA
    recusada = resultado("assinatura_esperada", assinados["assinado"], esperado=outro)
    assert recusada["situacao"] == v.REPROVADA
    assert "certificado que não está entre os aceitos" in recusada["detalhe"]


# --- programa gerador e formato esperados ---

def test_programa_esperado_para_o_tipo(pdf, imagem):
    espera = {"programas": ["itext", "PDFium"]}

    assert situacao("programa_esperado", pdf, metadados=ITEXT) == v.NAO_SE_APLICA
    assert situacao("programa_esperado", pdf, metadados=ITEXT, esperado=espera) == v.APROVADA
    fora = resultado("programa_esperado", pdf, metadados=WORD, esperado=espera)
    assert fora["situacao"] == v.REPROVADA and "Microsoft® Word 2016" in fora["detalhe"] and "itext, PDFium" in fora["detalhe"]
    # quem não informa o programa também está fora do esperado
    sem_programa = resultado("programa_esperado", pdf, metadados={"producer": "", "creator": None}, esperado=espera)
    assert sem_programa["situacao"] == v.REPROVADA and "não informa o programa" in sem_programa["detalhe"]
    assert situacao("programa_esperado", imagem, formatos=("foto",), esperado=espera) == v.NAO_SE_APLICA
    # no PDF que é só imagem, o programa gravado é o do scanner, e não há o que comparar
    digitalizado = resultado("programa_esperado", pdf, formatos=("imagem_limpa",), metadados={"producer": "Epson Scan 2"}, esperado=espera)
    assert digitalizado["situacao"] == v.NAO_SE_APLICA and "só imagem" in digitalizado["detalhe"]
    assert situacao("programa_esperado", pdf, formatos=("pdf_sem_texto",), metadados=WORD, esperado=espera) == v.REPROVADA
    assert situacao("programa_esperado", pdf, formatos=(), metadados=WORD, esperado=espera) == v.NAO_CONFERIDA


def test_formato_esperado_para_o_tipo(pdf):
    espera = {"formatos": ["pdf_digital"]}

    assert situacao("formato_esperado", pdf) == v.NAO_SE_APLICA
    assert situacao("formato_esperado", pdf, esperado=espera) == v.APROVADA
    fora = resultado("formato_esperado", pdf, formatos=("captura_de_tela", "pdf_digital"), esperado=espera)
    assert fora["situacao"] == v.REPROVADA
    assert fora["detalhe"] == "O arquivo chegou como print de tela; o tipo de documento espera PDF gerado por software."
    assert situacao("formato_esperado", pdf, formatos=(), esperado=espera) == v.NAO_CONFERIDA


def test_validacoes_do_tipo_viram_uma_flag_so(pdf):
    espera = {"programas": ["iText"], "assinatura_digital": True, "formatos": ["pdf_digital"]}
    validacoes = resultados(pdf, metadados=WORD, esperado=espera)

    assert {r["validacao"] for r in validacoes if r["situacao"] == v.REPROVADA} == {"programa_esperado", "assinatura_esperada"}
    flag, = v.flags(validacoes)
    # o arquivo fora do esperado sai como flag crítica: decide sozinho
    assert flag["severity"] == "CRÍTICA" and flag["source"] == "VALIDACAO_DO_ARQUIVO"
    assert flag["description"] == "Arquivo fora do esperado para o tipo de documento: programa gerador fora do esperado, sem a assinatura digital esperada"
    assert "Microsoft® Word 2016" in flag["evidence"] and "não tem" in flag["evidence"]

    # vale a maior severidade entre as reprovadas do grupo, e a informativa não vira flag
    mais_branda = resultados(pdf, metadados=WORD, esperado=espera, severidades={"assinatura_esperada": "MODERADA", "programa_esperado": "BAIXA"})
    assert [flag["severity"] for flag in v.flags(mais_branda)] == ["MODERADA"]
    informativas = resultados(pdf, metadados=WORD, esperado=espera, severidades={"assinatura_esperada": "INFORMATIVA", "programa_esperado": "INFORMATIVA"})
    assert v.flags(informativas) == []


def test_as_validacoes_do_tipo_sao_criticas_por_padrao():
    do_tipo = {nome: funcao.severidade for nome, funcao in v.VALIDACOES.items() if funcao.grupo == v.ARQUIVO_ESPERADO}

    assert do_tipo == {"formato_esperado": "CRÍTICA", "programa_esperado": "CRÍTICA", "assinatura_esperada": "CRÍTICA"}


# --- datas dos metadados ---

@pytest.mark.parametrize("criacao, modificacao, esperada, trecho", [
    ("2026-10-01 10:00:00 -03:00", "2026-10-01 10:00:05 -03:00", v.APROVADA, "são possíveis"),
    # o fuso pode adiantar a data em algumas horas
    ("2026-10-14 08:00:00 +00:00", None, v.APROVADA, "são possíveis"),
    ("2027-01-05 10:00:00 -03:00", None, v.REPROVADA, "a data de criação (05/01/2027) está no futuro"),
    ("2026-10-01 10:00:00 -03:00", "2026-09-20 10:00:00 -03:00", v.REPROVADA, "a modificação (20/09/2026) é anterior à criação (01/10/2026)"),
    # o que não é data legível fica sem conferência, como as datas zeradas de alguns geradores
    ("03/11/2023 13:33:52", None, v.NAO_SE_APLICA, "não tem datas legíveis"),
    (None, None, v.NAO_SE_APLICA, "não tem datas legíveis"),
])
def test_datas_dos_metadados(pdf, criacao, modificacao, esperada, trecho):
    datas = resultado("datas_dos_metadados", pdf, metadados={"creationDate": criacao, "modDate": modificacao})

    assert datas["situacao"] == esperada
    assert trecho in datas["detalhe"]


def test_flag_de_data_impossivel_e_temporal(pdf):
    flag, = v.flags(resultados(pdf, metadados={"creationDate": "2027-01-05 10:00:00 -03:00"}))

    assert (flag["category"], flag["severity"]) == ("TEMPORAL", "MODERADA")


# --- marcas de IA e de edição gráfica ---

def test_arquivo_sem_marca_de_ia(imagem):
    gerado = resultado("gerado_por_ia", imagem, formatos=("foto",))

    assert gerado["situacao"] == v.APROVADA
    # aprovar não é dizer que a imagem não foi gerada
    assert "A ausência da marca não prova nada" in gerado["detalhe"]
    assert situacao("editado_com_ia", imagem, formatos=("foto",)) == v.APROVADA


def test_imagem_declarada_como_gerada_por_ia(tmp_path):
    path = tmp_path / "gerada.jpg"
    Image.new("RGB", (40, 30), "white").save(path)
    path.write_bytes(path.read_bytes() + b'<x:xmpmeta Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"/>')

    validacoes = resultados(path, formatos=("foto",))

    assert {r["validacao"]: r["situacao"] for r in validacoes if r["validacao"].endswith("_ia")} == {"gerado_por_ia": v.REPROVADA, "editado_com_ia": v.APROVADA}
    flag, = v.flags(validacoes)
    assert (flag["severity"], flag["description"]) == ("CRÍTICA", "O arquivo declara ter sido gerado por IA")


def test_imagem_declarada_como_editada_com_ia(tmp_path):
    path = tmp_path / "editada.jpg"
    Image.new("RGB", (40, 30), "white").save(path)
    path.write_bytes(path.read_bytes() + b"http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia")

    validacoes = resultados(path, formatos=("foto",))

    assert {r["validacao"]: r["situacao"] for r in validacoes if r["validacao"].endswith("_ia")} == {"gerado_por_ia": v.APROVADA, "editado_com_ia": v.REPROVADA}
    assert [flag["severity"] for flag in v.flags(validacoes)] == ["MODERADA"]


def test_bloco_de_texto_de_gerador_de_imagem(tmp_path):
    path = tmp_path / "gerada.png"
    blocos = PngInfo()
    blocos.add_text("parameters", "carteira de identidade\nSteps: 30, Sampler: Euler a, CFG scale: 7")
    Image.new("RGB", (40, 30), "white").save(path, pnginfo=blocos)

    gerado = resultado("gerado_por_ia", path, formatos=("imagem_limpa",))

    assert gerado["situacao"] == v.REPROVADA and "Stable Diffusion" in gerado["detalhe"]


def test_programa_de_edicao_grafica_so_informa(tmp_path, pdf, imagem):
    path = tmp_path / "editada.jpg"
    exif = Image.Exif()
    exif[0x0131] = "Adobe Photoshop 25.0 (Windows)"
    Image.new("RGB", (40, 30), "white").save(path, exif=exif)

    validacoes = resultados(path, formatos=("foto",))
    edicao = next(r for r in validacoes if r["validacao"] == "programa_de_edicao")

    assert edicao["situacao"] == v.REPROVADA and edicao["severidade"] == "INFORMATIVA"
    assert edicao["detalhe"] == "Programa de edição gráfica nos metadados: Adobe Photoshop 25.0 (Windows) (EXIF Software)."
    # a regra do médio e do baixo risco sobre software de edição é do orquestrador: aqui não sai flag
    assert v.flags(validacoes) == []
    assert "(informativa)" in v.descrever(validacoes)

    assert situacao("programa_de_edicao", pdf, metadados={"producer": "Canva", "creator": "Canva"}) == v.REPROVADA
    assert situacao("programa_de_edicao", pdf, metadados=ITEXT) == v.APROVADA
    assert situacao("programa_de_edicao", imagem, formatos=("foto",)) == v.NAO_SE_APLICA


# --- execução ---

def test_arquivo_que_nao_existe_nao_tem_validacoes(tmp_path):
    assert resultados(tmp_path / "nao_existe.pdf") == []


def test_validacao_que_falha_fica_como_nao_conferida(pdf, monkeypatch):
    def com_erro(arquivo):
        raise ValueError("arquivo estranho")

    def sem_biblioteca(arquivo):
        raise ModuleNotFoundError("No module named 'pyhanko'", name="pyhanko")

    for nome, funcao in (("datas_dos_metadados", com_erro), ("assinatura_integra", sem_biblioteca)):
        original = v.VALIDACOES[nome]
        for atributo in ("titulo", "problema", "severidade", "grupo", "categoria"):
            setattr(funcao, atributo, getattr(original, atributo))
        monkeypatch.setitem(v.VALIDACOES, nome, funcao)

    validacoes = {r["validacao"]: r for r in resultados(pdf)}

    assert validacoes["datas_dos_metadados"]["situacao"] == v.NAO_CONFERIDA
    assert validacoes["datas_dos_metadados"]["detalhe"] == "A validação falhou: ValueError: arquivo estranho"
    assert validacoes["assinatura_integra"]["detalhe"] == "Falta instalar a biblioteca 'pyhanko' para esta validação."
    # as outras rodam normalmente, e o que não foi conferido não vira flag
    assert validacoes["gerado_por_ia"]["situacao"] == v.APROVADA
    assert v.flags(list(validacoes.values())) == []


def test_texto_das_validacoes_para_o_orquestrador(pdf):
    validacoes = resultados(pdf, metadados=WORD, esperado={"programas": ["iText"]})

    texto = v.descrever(validacoes)
    assert texto.startswith("\n      • Programa gerador esperado para o tipo: REPROVADA (flag CRÍTICA já contada). O PDF foi gerado por Microsoft® Word 2016")
    # só as reprovadas vão para a prompt: a aprovada não deve pesar a favor do documento
    assert texto.count("•") == 1 and "APROVADA" not in texto and "geração por IA" not in texto
    # no nível de risco sem regras de decisão nenhuma flag é contada
    assert "REPROVADA (informativa)" in v.descrever(validacoes, contadas=False)
    assert v.descrever(resultados(pdf)) == "nenhuma."
    assert v.descrever([]) == "nenhuma."


# --- configuração e catálogo ---

def test_severidade_das_validacoes_vem_da_configuracao():
    padrao = fraude_.severidades_das_validacoes(CONFIG)
    assert padrao == {nome: funcao.severidade for nome, funcao in v.VALIDACOES.items()}
    assert padrao["assinatura_integra"] == "CRÍTICA" and padrao["programa_de_edicao"] == "INFORMATIVA"

    config = {**CONFIG, "forense": {"validacoes": {"programa_esperado": "MODERADA"}}}
    assert fraude_.severidades_das_validacoes(config)["programa_esperado"] == "MODERADA"
    assert fraude_.severidades_das_validacoes(config)["formato_esperado"] == "CRÍTICA"
    fraude_.validar(config)

    # a configuração do projeto traz a severidade de todas as validações, para a tela editar
    assert set(fraude_.carregar()["forense"]["validacoes"]) == set(v.VALIDACOES)


@pytest.mark.parametrize("validacoes, mensagem", [
    ({"programa_esperado": "ALTA"}, "Validação do arquivo 'programa_esperado': a severidade precisa ser uma de CRÍTICA, MODERADA, BAIXA, INFORMATIVA."),
    ({"validacao_que_nao_existe": "BAIXA"}, "Validação do arquivo 'validacao_que_nao_existe' desconhecida."),
])
def test_severidade_invalida_na_configuracao(validacoes, mensagem):
    with pytest.raises(ValueError, match=mensagem):
        fraude_.validar({**CONFIG, "forense": {"validacoes": validacoes}})


@pytest.mark.parametrize("esperado, mensagem", [
    ({"formatos": ["pdf"]}, "formato de arquivo desconhecido: pdf"),
    ({"programas": "iText"}, "'programas' do arquivo esperado precisa ser uma lista de textos"),
    ({"assinatura_digital": "sim"}, "'assinatura_digital' do arquivo esperado precisa ser verdadeiro ou falso"),
    ({"assinatura_digital": True, "certificados": ["15e5b3"]}, "impressão digital SHA-256"),
    ({"certificados": ["ab" * 32]}, "os certificados aceitos só valem quando o tipo espera assinatura digital"),
    ({"programa": ["iText"]}, "opção 'programa' desconhecida no arquivo esperado"),
])
def test_arquivo_esperado_invalido_no_catalogo(esperado, mensagem):
    catalogo = copy.deepcopy(CATALOGO)
    catalogo["carta_permanencia"]["arquivo_esperado"] = esperado

    with pytest.raises(ValueError, match=mensagem):
        catalogo_.validar(catalogo)


def test_arquivo_esperado_valido_no_catalogo():
    catalogo = copy.deepcopy(CATALOGO)
    catalogo["carta_permanencia"]["arquivo_esperado"] = {"formatos": ["pdf_digital"], "programas": ["iText"], "assinatura_digital": True, "certificados": ["ab" * 32]}

    catalogo_.validar(catalogo)


# --- na análise de fraude ---

CATALOGO_COM_ESPERADO = {
    **CATALOGO,
    "carta_permanencia": {**CATALOGO["carta_permanencia"], "arquivo_esperado": {"programas": ["iText"]}},
    "rg": {**CATALOGO["rg"], "arquivo_esperado": {"programas": ["iText"]}},
}


def test_validacao_reprovada_entra_na_decisao(pdf):
    # o orquestrador não aponta nada: a validação do arquivo decide sozinha
    llm = FakeLLM(TEXTUAL_CONSISTENTE, VISUAL_LEGITIMO, METADADOS_SUSPEITO, orquestrador())
    doc = DocumentoConvertido(path=pdf, markdown="## TEXTO DO DOCUMENTO")

    resultado_ = analisar_fraude(llm, doc, "carta_permanencia", CATALOGO_COM_ESPERADO, CONFIG)

    # o resultado da análise forense traz a situação de cada validação
    validacoes = {r["validacao"]: r["situacao"] for r in resultado_["forense"]["validacoes"]}
    assert set(validacoes) == set(v.VALIDACOES)
    assert validacoes["programa_esperado"] == v.REPROVADA and validacoes["formato_esperado"] == v.NAO_SE_APLICA

    # a flag crítica da validação basta para o documento sair suspeito
    saida = resultado_["output_Evaluator"]
    assert [(flag["source"], flag["severity"]) for flag in saida["flags"]] == [("VALIDACAO_DO_ARQUIVO", "CRÍTICA")]
    assert saida["status_fraude"] == "SUSPEITO" and saida["decisao"]["regra"] == "críticas ≥ 1"
    assert saida["fraud_score"] == 3.0

    # e o orquestrador é avisado de que ela já foi contada
    prompt = llm.calls[-1]["prompt"]
    assert "- Validações do arquivo reprovadas (conferidas por código): \n      • Programa gerador esperado para o tipo: REPROVADA (flag CRÍTICA já contada)." in prompt
    assert "NÃO gere outra flag\n      para o mesmo fato" in prompt
    assert "APROVADA" not in prompt


def test_flag_moderada_da_validacao_se_soma_as_do_orquestrador(pdf):
    # com a severidade trocada para moderada na configuração, a validação precisa de outro indício
    config = {**CONFIG, "forense": {"validacoes": {"programa_esperado": "MODERADA"}}}
    doc = DocumentoConvertido(path=pdf, markdown="## TEXTO DO DOCUMENTO")

    def saida(*flags):
        llm = FakeLLM(TEXTUAL_CONSISTENTE, VISUAL_LEGITIMO, METADADOS_SUSPEITO, orquestrador(*flags))
        return analisar_fraude(llm, doc, "carta_permanencia", CATALOGO_COM_ESPERADO, config)["output_Evaluator"]

    assert saida()["status_fraude"] == "AUTÊNTICO"
    com_outra = saida(MODERADA)
    assert [flag["source"] for flag in com_outra["flags"]] == ["VISUAL_EVALUATOR", "VALIDACAO_DO_ARQUIVO"]
    assert com_outra["status_fraude"] == "SUSPEITO" and com_outra["decisao"]["regra"] == "moderadas ≥ 2"


def test_validacao_reprovada_so_informa_no_risco_nulo(pdf):
    llm = FakeLLM(orquestrador())
    doc = DocumentoConvertido(path=pdf, markdown="## TEXTO DO DOCUMENTO")

    resultado_ = analisar_fraude(llm, doc, "rg", CATALOGO_COM_ESPERADO, CONFIG)

    assert next(r for r in resultado_["forense"]["validacoes"] if r["validacao"] == "programa_esperado")["situacao"] == v.REPROVADA
    assert resultado_["output_Evaluator"]["flags"] == []
    assert resultado_["output_Evaluator"]["status_fraude"] == "AUTÊNTICO"
    assert "Programa gerador esperado para o tipo: REPROVADA (informativa)." in llm.calls[0]["prompt"]


def test_arquivo_com_mais_de_um_documento_fica_so_com_essa_flag(pdf):
    llm = FakeLLM(TEXTUAL_CONSISTENTE, VISUAL_LEGITIMO, METADADOS_SUSPEITO, orquestrador(multiplos_documentos=True, quantidade_documentos=2))
    doc = DocumentoConvertido(path=pdf, markdown="## TEXTO DO DOCUMENTO")

    saida = analisar_fraude(llm, doc, "carta_permanencia", CATALOGO_COM_ESPERADO, CONFIG)["output_Evaluator"]

    assert saida["status_fraude"] == "INVÁLIDO"
    assert [flag["description"] for flag in saida["flags"]] == ["Múltiplos documentos distintos no mesmo arquivo"]
