import ctypes

import cv2
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw
import pytest

from subscricao.conversao import DocumentoConvertido
from subscricao.fraude import configuracao as fraude_
from subscricao.fraude.analise import ORIGEM_CAMADA_DE_TEXTO, analisar_fraude
from subscricao.fraude.forense import avaliador, calibracao, estrutura, raster
from subscricao.fraude.forense.formato import caracteristicas_de_origem, formato_da_imagem, paginas_do_documento

from test_fraude import CATALOGO, CONFIG, FakeLLM, TEXTUAL_CONSISTENTE, VISUAL_LEGITIMO, orquestrador


@pytest.fixture(autouse=True)
def sem_gpu(monkeypatch):
    # o casamento de descritores na CPU dá o mesmo resultado e não depende da máquina
    monkeypatch.setattr(raster, "_torch", False)


def pagina_com_texto(ruido, altura=900, largura=700, semente=0):
    """Página clara com linhas de texto e, se pedido, ruído de papel."""
    rng = np.random.default_rng(semente)
    pagina = np.full((altura, largura), 225, np.uint8)
    for linha in range(18):
        texto = "".join(rng.choice(list("ABCDEFGHJKLMNPRSTUVXZ0123456789 "), size=38))
        cv2.putText(pagina, texto, (30, 60 + 45 * linha), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 40, 2, cv2.LINE_AA)
    pagina = pagina.astype(np.float32)
    if ruido:
        pagina = cv2.GaussianBlur(pagina, (0, 0), 0.8) + rng.normal(0, ruido, pagina.shape)
    return cv2.cvtColor(np.clip(pagina, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2RGB)


def perto(regiao, x, y, tolerancia=0.12):
    return abs(regiao[0] - x) <= tolerancia and abs(regiao[1] - y) <= tolerancia


# --- formato ---

def test_formato_de_imagens_sinteticas():
    limpa = pagina_com_texto(ruido=0)
    assert formato_da_imagem(caracteristicas_de_origem(limpa)) in ("imagem_limpa", "captura_de_tela")

    bitonal = np.where(limpa > 128, 255, 0).astype(np.uint8)
    assert formato_da_imagem(caracteristicas_de_origem(bitonal)) == "bitonal"

    com_ruido = pagina_com_texto(ruido=4)
    assert formato_da_imagem(caracteristicas_de_origem(com_ruido)) in ("digitalizacao", "foto")


# --- pixels ---

def test_campo_reescrito_sobre_papel_com_ruido():
    original = pagina_com_texto(ruido=4)
    adulterada = original.copy()
    # o editor pinta o campo com a cor do papel e digita por cima
    adulterada[365:400, 200:420] = 225
    cv2.putText(adulterada, "9876543210", (205, 392), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 40), 2, cv2.LINE_AA)

    antes, _ = raster.medir(original, ("campo_liso",))
    depois, regioes = raster.medir(adulterada, ("campo_liso",))

    assert depois["campo_liso"] > antes["campo_liso"] + 1
    assert perto(regioes["campo_liso"], 310 / 700, 382 / 900)


def test_trecho_copiado_de_outro_ponto_da_pagina():
    original = pagina_com_texto(ruido=4)
    adulterada = original.copy()
    adulterada[500:535, 300:520] = original[185:220, 60:280]

    antes, _ = raster.medir(original, ("copia_interna",))
    depois, regioes = raster.medir(adulterada, ("copia_interna",))

    # letras iguais se repetem na página original, mas o ruído ao redor delas não
    assert antes["copia_interna"] < 0.5
    assert depois["copia_interna"] > 0.9
    assert any(perto(regiao, 410 / 700, 517 / 900) for regiao in regioes["copia_interna"])
    assert any(perto(regiao, 170 / 700, 202 / 900) for regiao in regioes["copia_interna"])


def test_pagina_sem_ruido_nao_tem_copia_a_confirmar():
    limpa = pagina_com_texto(ruido=0)
    limpa[500:535, 300:520] = limpa[185:220, 60:280]

    sinais, _ = raster.medir(limpa, ("copia_interna",))

    assert sinais["copia_interna"] == 0


# --- estrutura do PDF ---

def texto(conteudo, ordem, caixa, fonte="ABCDEF+Arial", embutida=True, tamanho=10.0, visivel=True):
    return {"ordem": ordem, "caixa": caixa, "texto": conteudo, "fonte": fonte.split("+")[-1], "recurso": fonte, "embutida": embutida,
            "tamanho": tamanho, "base": (caixa[0], caixa[1]), "horizontal": True, "visivel": visivel}


def objetos(textos=(), formas=(), imagens=(), anotacoes=()):
    return {"largura": 600, "altura": 800, "textos": list(textos), "formas": list(formas), "imagens": list(imagens), "anotacoes": list(anotacoes)}


CORPO = [texto("Declaramos para os devidos fins que o beneficiario abaixo " * 2, i, (50, 700 - 20 * i, 550, 712 - 20 * i)) for i in range(4)]


def test_texto_coberto_e_reescrito():
    pagina = objetos(
        textos=CORPO + [texto("R$ 1.200,00", 10, (100, 300, 180, 312)), texto("R$ 4.360,00", 12, (100, 300, 180, 312))],
        formas=[{"ordem": 11, "caixa": (98, 298, 182, 314), "cor": (255, 255, 255), "opaca": True}],
    )

    sinais, exemplos = estrutura.medir(pagina)

    assert sinais["texto_substituido"] == len("R$ 1.200,00")
    assert sinais["texto_oculto"] == 0
    assert "R$ 1.200,00" in exemplos["texto_substituido"][0] and "R$ 4.360,00" in exemplos["texto_substituido"][0]


def test_texto_apenas_coberto():
    pagina = objetos(
        textos=CORPO + [texto("01/02/2020", 10, (100, 300, 180, 312))],
        formas=[{"ordem": 11, "caixa": (98, 298, 182, 314), "cor": (255, 255, 255), "opaca": True}],
    )

    sinais, _ = estrutura.medir(pagina)

    assert (sinais["texto_substituido"], sinais["texto_oculto"]) == (0, len("01/02/2020"))


def test_fundo_de_pagina_nao_esconde_texto():
    fundo = {"ordem": 99, "caixa": (0, 0, 600, 800), "cor": (255, 255, 255), "opaca": True}

    sinais, _ = estrutura.medir(objetos(textos=CORPO, formas=[fundo]))

    assert sinais["texto_oculto"] == 0


def test_fontes_do_trecho_reescrito():
    pagina = objetos(textos=CORPO + [
        # mesma fonte em outro subconjunto, fonte padrão não embutida e tamanho quase igual
        texto("30 DE ABRIL", 10, (100, 300, 180, 312), fonte="GHIJKL+Arial"),
        texto("4360", 11, (100, 280, 140, 292), fonte="Helvetica", embutida=False),
        texto("2025", 12, (100, 260, 140, 272), tamanho=10.4),
    ])

    sinais, exemplos = estrutura.medir(pagina)

    assert sinais["fonte_duplicada"] == len("30 DE ABRIL")
    assert sinais["fonte_nao_embutida"] == 4 and sinais["fontes_raras"] == 4
    assert sinais["tamanho_destoante"] == 1
    assert "GHIJKL+Arial" in exemplos["fonte_duplicada"][0]


def test_negrito_da_fonte_comum_e_simbolos_nao_sao_fontes_raras():
    pagina = objetos(textos=CORPO + [
        texto("Total", 10, (100, 300, 140, 312), fonte="ABCDEF+Arial-Bold"),
        texto("abc", 11, (100, 280, 140, 292), fonte="SymbolMT"),
    ])

    sinais, _ = estrutura.medir(pagina)

    assert sinais["fontes_raras"] == 0


def test_documento_sem_edicao_nao_tem_sinais():
    sinais, exemplos = estrutura.medir(objetos(textos=CORPO))

    assert not any(sinais.values()) and exemplos == {}


def test_edicoes_sobre_pagina_digitalizada():
    pagina = objetos(
        imagens=[{"ordem": 0, "caixa": (0, 0, 600, 800), "px": (1654, 2339)}, {"ordem": 3, "caixa": (300, 100, 420, 140), "px": (240, 80)}],
        textos=[texto("camada de OCR", 1, (50, 700, 300, 712), visivel=False), texto("12.345.678/0001-90", 2, (100, 300, 260, 312))],
        formas=[{"ordem": 4, "caixa": (100, 500, 260, 520), "cor": (255, 255, 255), "opaca": True}],
        anotacoes=[raw.FPDF_ANNOT_FREETEXT, raw.FPDF_ANNOT_LINK],
    )

    sinais, exemplos = estrutura.medir(pagina)

    # a camada de OCR é invisível e não conta; o link não desenha conteúdo
    assert sinais["texto_sobre_imagem"] == len("12.345.678/0001-90")
    assert (sinais["forma_sobre_imagem"], sinais["imagem_sobre_imagem"], sinais["anotacoes_de_edicao"]) == (1, 1, 1)
    assert "parte inferior" in exemplos["imagem_sobre_imagem"][0]


# --- calibração e sensibilidade ---

def calibracao_de_teste(paginas=200):
    rng = np.random.default_rng(1)
    return calibracao.montar([
        {"formato": "pdf_digital", "sinais": {"texto_substituido": 0, "fonte_duplicada": int(rng.integers(0, 20))}} for _ in range(paginas)
    ])


def pagina_medida(**sinais):
    return {"pagina": 1, "formato": "pdf_digital", "em_pdf": True, "sinais": sinais, "regioes": {}, "exemplos": {"texto_substituido": ["'1.200,00' coberto e reescrito como '4.360,00'"]}}


def test_raridade():
    valores = np.arange(1, 100, dtype=float)

    assert calibracao.raridade(valores, 0) == 1.0
    assert calibracao.raridade(valores, 90) == pytest.approx(11 / 100)
    # acima de tudo o que se viu: não dá para afirmar nada mais raro que 1/(n+1)
    assert calibracao.raridade(valores, 1e6) == pytest.approx(1 / 100)


def test_formato_com_poucas_paginas_fica_sem_calibracao():
    assert "pdf_digital" not in calibracao_de_teste(paginas=calibracao.MINIMO_DE_PAGINAS - 1)["formatos"]


def test_sensibilidade_decide_o_nivel():
    referencia = calibracao_de_teste()
    adulterada = [pagina_medida(texto_substituido=11, fonte_duplicada=3)]

    niveis = [avaliador.avaliar(adulterada, sensibilidade, referencia)["nivel"] for sensibilidade in range(11)]

    # mais raro que as 200 páginas autênticas: 1/201 = 0,5%
    assert niveis[0] == avaliador.BAIXO and niveis[1] == avaliador.BAIXO
    assert niveis[2] == avaliador.MODERADO and niveis[6] == avaliador.ALTO
    assert [avaliador.avaliar([pagina_medida(texto_substituido=0, fonte_duplicada=3)], s, referencia)["nivel"] for s in (0, 6, 10)] == [avaliador.BAIXO] * 3


def test_alarme_falso_acompanha_a_sensibilidade():
    referencia = calibracao_de_teste(paginas=400)
    rng = np.random.default_rng(2)
    autenticas = [[pagina_medida(texto_substituido=0, fonte_duplicada=int(rng.integers(0, 20)))] for _ in range(400)]

    for sensibilidade in (0, 4, 6, 8, 10):
        sinalizadas = np.mean([avaliador.avaliar(paginas, sensibilidade, referencia)["nivel"] != avaliador.BAIXO for paginas in autenticas])
        assert sinalizadas <= avaliador.ALARME_FALSO[sensibilidade] + 0.03


def test_relatorio_traz_nivel_flags_e_alcance():
    resultado = avaliador.avaliar([pagina_medida(texto_substituido=11, fonte_duplicada=3)], 6, calibracao_de_teste())

    assert resultado["nivel"] == avaliador.ALTO and 7 <= resultado["pontuacao"] <= 10
    assert "NÍVEL DE SUSPEIÇÃO: ALTO" in resultado["relatorio"]
    assert "texto_substituido" in resultado["relatorio"] and "'1.200,00' coberto e reescrito como '4.360,00'" in resultado["relatorio"]
    assert "não detecta documento refeito na origem" in resultado["relatorio"]


def test_formato_sem_medida_nao_e_analisavel():
    paginas = [{"pagina": 1, "formato": "captura_de_tela", "em_pdf": False, "sinais": {}, "regioes": {}, "exemplos": {}}]

    resultado = avaliador.avaliar(paginas, 6, calibracao_de_teste())

    assert resultado["nivel"] == avaliador.NAO_ANALISAVEL and resultado["pontuacao"] is None
    assert "NÍVEL DE SUSPEIÇÃO: N/A" in resultado["relatorio"]


def calibracao_de_imagens():
    rng = np.random.default_rng(3)
    return calibracao.montar(
        [{"formato": "captura_de_tela", "sinais": {"texto_sobre_imagem": 0, "anotacoes_de_edicao": 0}} for _ in range(60)]
        + [{"formato": "imagem_limpa", "sinais": {"copia_interna": round(float(rng.uniform(0, 0.5)), 3)}} for _ in range(60)]
    )


def pagina_de_imagem(formato, **sinais):
    return {"pagina": 1, "formato": formato, "em_pdf": True, "sinais": sinais, "regioes": {}, "exemplos": {}}


def test_print_de_tela_em_pdf_sem_nada_por_cima_nao_e_analisavel():
    referencia = calibracao_de_imagens()

    # nada da página pode ser medido e nada foi desenhado por cima: "baixo" seria ler como sem problemas o que é sem medida
    sem_medida = avaliador.avaliar([pagina_de_imagem("captura_de_tela", texto_sobre_imagem=0, anotacoes_de_edicao=0)], 8, referencia)
    assert sem_medida["nivel"] == avaliador.NAO_ANALISAVEL and sem_medida["pontuacao"] is None
    assert sem_medida["alcance"] == avaliador.SEM_ALCANCE
    assert "NÍVEL DE SUSPEIÇÃO: N/A" in sem_medida["relatorio"]

    # com texto digitado por cima da imagem, há o que avaliar
    com_texto = avaliador.avaliar([pagina_de_imagem("captura_de_tela", texto_sobre_imagem=40, anotacoes_de_edicao=0)], 8, referencia)
    assert com_texto["nivel"] in (avaliador.MODERADO, avaliador.ALTO)
    assert com_texto["paginas"][0]["flags"][0]["sinal"] == "texto_sobre_imagem"


def test_alcance_da_analise_acompanha_o_formato():
    limitado = avaliador.avaliar([pagina_de_imagem("imagem_limpa", copia_interna=0.1)], 8, calibracao_de_imagens())
    assert limitado["nivel"] == avaliador.BAIXO and limitado["alcance"] == avaliador.ALCANCE_LIMITADO
    assert "Alcance limitado" in limitado["relatorio"]

    normal = avaliador.avaliar([pagina_medida(texto_substituido=0, fonte_duplicada=3)], 8, calibracao_de_teste())
    assert normal["alcance"] == avaliador.ALCANCE_NORMAL and "Alcance limitado" not in normal["relatorio"]

    # em documento com páginas de formatos diferentes, vale o melhor alcance entre as analisadas
    misto = avaliador.avaliar(
        [pagina_medida(texto_substituido=0, fonte_duplicada=3), pagina_de_imagem("captura_de_tela", texto_sobre_imagem=0)],
        8, {"formatos": {**calibracao_de_teste()["formatos"], **calibracao_de_imagens()["formatos"]}},
    )
    assert misto["alcance"] == avaliador.ALCANCE_NORMAL and [pagina["nivel"] for pagina in misto["paginas"]] == [avaliador.BAIXO, avaliador.NAO_ANALISAVEL]


@pytest.mark.parametrize("p, alarme_falso, nivel, faixa", [
    (0.9, 0.05, avaliador.BAIXO, range(0, 4)),
    (0.06, 0.05, avaliador.BAIXO, range(0, 4)),
    (0.03, 0.05, avaliador.MODERADO, range(4, 7)),
    (0.011, 0.05, avaliador.MODERADO, range(4, 7)),
    (0.009, 0.05, avaliador.ALTO, range(7, 11)),
    (1e-6, 0.05, avaliador.ALTO, range(7, 11)),
    (1e-6, 0.0, avaliador.BAIXO, range(0, 4)),
])
def test_faixas_de_pontuacao_da_prompt_visual(p, alarme_falso, nivel, faixa):
    assert avaliador.nivel_e_pontuacao(p, alarme_falso)[0] == nivel
    assert avaliador.nivel_e_pontuacao(p, alarme_falso)[1] in faixa


def test_calibracao_do_projeto_cobre_os_formatos():
    referencia = calibracao.carregar()

    assert {"pdf_digital", "foto", "digitalizacao", "imagem_limpa"} <= set(referencia["formatos"])
    for formato in referencia["formatos"].values():
        assert formato["paginas"] >= calibracao.MINIMO_DE_PAGINAS


# --- do arquivo ao relatório ---

def pdf_com_texto(path, adulterar):
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(595, 842)

    def escreve(conteudo, x, y):
        obj = raw.FPDFPageObj_NewTextObj(doc.raw, b"Helvetica", ctypes.c_float(11))
        dados = (conteudo + "\x00").encode("utf-16-le")
        raw.FPDFText_SetText(obj, ctypes.cast(ctypes.create_string_buffer(dados, len(dados)), ctypes.POINTER(ctypes.c_ushort)))
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y)
        raw.FPDFPage_InsertObject(page.raw, obj)

    for linha in range(8):
        escreve("Declaramos para os devidos fins que o beneficiario esteve ativo no plano", 50, 780 - 20 * linha)
    escreve("Valor: 1.200,00", 50, 600)
    if adulterar:
        forma = raw.FPDFPageObj_CreateNewRect(85, 597, 80, 14)
        raw.FPDFPageObj_SetFillColor(forma, 255, 255, 255, 255)
        raw.FPDFPath_SetDrawMode(forma, raw.FPDF_FILLMODE_ALTERNATE, 0)
        raw.FPDFPage_InsertObject(page.raw, forma)
        escreve("4.360,00", 88, 600)
    raw.FPDFPage_GenerateContent(page.raw)
    doc.save(path)
    doc.close()
    return path


def test_pdf_editado_depois_de_gerado(tmp_path):
    original = pdf_com_texto(tmp_path / "original.pdf", adulterar=False)
    adulterado = pdf_com_texto(tmp_path / "adulterado.pdf", adulterar=True)

    assert [pagina.formato for pagina in paginas_do_documento(original)] == ["pdf_digital"]
    assert avaliador.analisar(original)["nivel"] == avaliador.BAIXO

    resultado = avaliador.analisar(adulterado, sensibilidade=8)
    assert resultado["nivel"] in (avaliador.MODERADO, avaliador.ALTO)
    assert resultado["paginas"][0]["flags"][0]["sinal"] in ("texto_substituido", "texto_oculto")
    assert avaliador.analisar(adulterado, sensibilidade=0)["nivel"] == avaliador.BAIXO


def test_relatorio_forense_vai_para_o_avaliador_visual(tmp_path):
    adulterado = pdf_com_texto(tmp_path / "adulterado.pdf", adulterar=True)
    llm = FakeLLM(TEXTUAL_CONSISTENTE, VISUAL_LEGITIMO, orquestrador())
    documento = DocumentoConvertido(path=adulterado, markdown="## TEXTO DO DOCUMENTO")

    fraude = analisar_fraude(llm, documento, "contrato_social", CATALOGO, CONFIG)

    visual = llm.calls[1]["prompt"]
    assert fraude["forense"]["formatos"] == ["pdf_digital"]
    assert fraude["forense"]["relatorio"] in visual
    # o relatório traz o ponto e o texto de cada flag, que a prompt visual manda conferir
    assert "texto_substituido" in visual and "CONFERÊNCIA DAS FLAGS DO RELATÓRIO" in visual
    # em PDF gerado por software, o markdown é o texto gravado no arquivo, e as prompts são avisadas
    assert fraude["origem_markdown"] == ORIGEM_CAMADA_DE_TEXTO
    assert f"- Origem do texto do markdown: {ORIGEM_CAMADA_DE_TEXTO}" in llm.calls[0]["prompt"]


# --- configuração ---

def test_sensibilidade_na_configuracao(tmp_path):
    assert fraude_.sensibilidade_forense({}) == fraude_.SENSIBILIDADE_PADRAO

    config = {**CONFIG, "forense": {"sensibilidade": 9}}
    fraude_.salvar(config, tmp_path / "fraude.json")
    assert fraude_.sensibilidade_forense(fraude_.carregar(tmp_path / "fraude.json")) == 9

    with pytest.raises(ValueError, match="0 a 10"):
        fraude_.validar({**CONFIG, "forense": {"sensibilidade": 11}})
