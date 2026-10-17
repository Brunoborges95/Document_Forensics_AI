"""
Formato de cada página de um documento. O avaliador forense depende só do formato em que o
documento chegou, não do tipo de documento:

    pdf_digital        PDF gerado por software: texto vetorial sobre a página
    pdf_sem_texto      PDF vetorial sem texto: letras convertidas em curvas (acontece em alguns
                       "Imprimir em PDF") ou página só com desenho. Não há o que analisar
    digitalizacao      papel digitalizado em scanner ou fotocopiado, com ruído de fundo
    foto               fotografia do documento
    imagem_limpa       imagem com fundo sem ruído: gerada por software ou digitalizada com o
                       fundo limpo pelo scanner (os pixels não permitem distinguir as duas)
    captura_de_tela    print de tela de celular ou computador
    bitonal            digitalização em preto e branco puro (fax, CCITT, JBIG2)

As páginas de PDF dominadas por imagem são tratadas pela imagem que contêm.
"""
import ctypes
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import Image

# Formatos analisados pelos pixels
FORMATOS_DE_IMAGEM = ("digitalizacao", "foto", "imagem_limpa", "captura_de_tela", "bitonal")

# O pdf_digital é analisado pela estrutura do arquivo; o pdf_sem_texto não é analisável
FORMATOS = ("pdf_digital", "pdf_sem_texto") + FORMATOS_DE_IMAGEM

# Uma página de PDF é tratada como imagem quando uma única imagem cobre a maior parte dela ou
# quando ela quase não tem texto vetorial visível e traz uma imagem de tamanho razoável
COBERTURA_DE_PAGINA_INTEIRA = 0.60
MINIMO_DE_CARACTERES_VETORIAIS = 50
LADO_MINIMO_DE_IMAGEM = 150

# Lado maior, em pixels, da imagem analisada
LADO_MAXIMO = 2600

LARGURAS_DE_TELA = {720, 750, 800, 828, 1080, 1125, 1170, 1179, 1206, 1242, 1284, 1290, 1320, 1366, 1440, 1536, 1600, 1920, 2560}


@dataclass
class Pagina:
    numero: int
    formato: str
    # RGB (uint8) das páginas analisadas pelos pixels; None no pdf_digital
    imagem: np.ndarray = None
    # True quando os pixels são os originais de um JPEG, sem reamostragem: só então a grade de
    # compressão pode ser analisada
    jpeg: bool = False
    # características usadas para decidir o formato
    origem: dict = field(default_factory=dict)
    # objetos da página, quando o arquivo é PDF (ver estrutura.py)
    objetos: dict = field(default_factory=dict)


def descreve_posicao(x, y):
    """Posição, em palavras, de um ponto da página dado em frações a partir do canto superior esquerdo."""
    vertical = "parte superior" if y < 1 / 3 else "parte inferior" if y > 2 / 3 else "meio da página"
    horizontal = "à esquerda" if x < 1 / 3 else "à direita" if x > 2 / 3 else "ao centro"
    return f"{vertical}, {horizontal}"


def caracteristicas_de_origem(rgb):
    """
    Mede, nos pixels, o que distingue foto, digitalização, print e imagem gerada por software.
    """
    h, w = rgb.shape[:2]
    # para decidir a origem basta uma amostra por decimação inteira, que não suaviza o ruído
    passo = max(1, max(h, w) // 1600)
    amostra = rgb[::passo, ::passo]
    cinza = cv2.cvtColor(amostra, cv2.COLOR_RGB2GRAY).astype(np.float32)

    # vizinhança 3x3 exatamente constante: só existe em imagem sem ruído de sensor
    kernel = np.ones((3, 3), np.uint8)
    plano_exato = float(np.mean(cv2.dilate(cinza, kernel) == cv2.erode(cinza, kernel)))

    # ruído nas regiões sem borda
    media = cv2.blur(cinza, (5, 5))
    desvio = np.sqrt(np.maximum(cv2.blur(cinza * cinza, (5, 5)) - media * media, 0))
    suave = cv2.GaussianBlur(cinza, (0, 0), 2)
    gradiente = cv2.Sobel(suave, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(suave, cv2.CV_32F, 0, 1) ** 2
    ruido_liso = float(np.median(desvio[gradiente <= np.percentile(gradiente, 60)]))

    # iluminação: variação do brilho do fundo em escala grande, forte em fotos
    fundo = cinza >= np.percentile(cinza, 60)
    borrado = cv2.GaussianBlur(cinza, (0, 0), max(cinza.shape) / 25)
    iluminacao = float(np.percentile(borrado[fundo], 95) - np.percentile(borrado[fundo], 5))
    nivel_fundo = float(np.median(cinza[fundo]))

    # moldura escura: a superfície em que o papel foi fotografado
    borda = max(4, min(cinza.shape) // 40)
    moldura = np.concatenate([cinza[:borda].ravel(), cinza[-borda:].ravel(), cinza[:, :borda].ravel(), cinza[:, -borda:].ravel()])
    moldura_escura = float(np.mean(moldura < nivel_fundo - 60))

    quantizado = (amostra // 8).reshape(-1, 3)
    cores = len(np.unique(quantizado[:: max(1, len(quantizado) // 200000)], axis=0))

    return {
        "plano_exato": round(plano_exato, 3),
        "ruido_liso": round(ruido_liso, 2),
        "iluminacao": round(iluminacao, 1),
        "nivel_fundo": round(nivel_fundo),
        "moldura_escura": round(moldura_escura, 2),
        "cores": cores,
        "proporcao": round(max(h, w) / min(h, w), 2),
        "largura_de_tela": min(h, w) in LARGURAS_DE_TELA,
    }


def formato_da_imagem(origem):
    """
    Formato a partir das características de origem. Regras ajustadas por conferência visual em
    457 imagens de docs/ e docs_fraude_QA/.
    """
    if origem["cores"] <= 4:
        return "bitonal"

    if origem["ruido_liso"] < 0.6 and origem["plano_exato"] >= 0.35:
        tela = origem["proporcao"] >= 1.7 or origem["largura_de_tela"]
        return "captura_de_tela" if tela else "imagem_limpa"

    foto = origem["moldura_escura"] >= 0.12 or origem["nivel_fundo"] < 200 or origem["iluminacao"] >= 45
    return "foto" if foto else "digitalizacao"


def _limita(rgb):
    h, w = rgb.shape[:2]
    if max(h, w) <= LADO_MAXIMO:
        return rgb
    # decimação inteira: reduzir com interpolação apagaria ruído e grade de compressão
    passo = int(np.ceil(max(h, w) / LADO_MAXIMO))
    return np.ascontiguousarray(rgb[::passo, ::passo])


def _pagina_de_imagem(numero, rgb, jpeg, objetos=None):
    reduzida = _limita(rgb)
    origem = caracteristicas_de_origem(reduzida)
    return Pagina(numero, formato_da_imagem(origem), reduzida, jpeg and reduzida is rgb, origem, objetos or {})


def _nome_da_fonte(textobj):
    fonte = raw.FPDFTextObj_GetFont(textobj)
    if not fonte:
        return None, None
    n = raw.FPDFFont_GetBaseFontName(fonte, None, 0)
    buf = ctypes.create_string_buffer(n)
    raw.FPDFFont_GetBaseFontName(fonte, buf, n)
    return buf.value.decode("utf-8", "replace"), bool(raw.FPDFFont_GetIsEmbedded(fonte))


def _texto_do_objeto(textobj, textpage):
    n = raw.FPDFTextObj_GetText(textobj, textpage, None, 0)
    buf = ctypes.create_string_buffer(n)
    raw.FPDFTextObj_GetText(textobj, textpage, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort)), n)
    return buf.raw.decode("utf-16-le", "replace").rstrip("\x00")


def objetos_da_pagina(page):
    """
    Objetos da página do PDF na ordem em que são desenhados: textos (com fonte, tamanho e se são
    visíveis), imagens e formas preenchidas.
    """
    largura, altura = page.get_size()
    textpage = page.get_textpage()
    textos, imagens, formas = [], [], []

    for ordem, obj in enumerate(page.get_objects(max_depth=4)):
        try:
            caixa = obj.get_bounds()
        except Exception:
            continue

        if obj.type == raw.FPDF_PAGEOBJ_TEXT:
            fonte, embutida = _nome_da_fonte(obj.raw)
            tamanho = ctypes.c_float()
            raw.FPDFTextObj_GetFontSize(obj.raw, tamanho)
            a, b, c, d, e, f = obj.get_matrix().get()
            textos.append({
                "ordem": ordem,
                "caixa": caixa,
                "texto": _texto_do_objeto(obj.raw, textpage.raw),
                "fonte": (fonte or "").split("+")[-1],
                # nome como está no arquivo, com o prefixo do subconjunto embutido (ABCDEF+Arial)
                "recurso": fonte or "",
                "embutida": embutida,
                # tamanho efetivo: o da fonte multiplicado pela escala vertical da matriz
                "tamanho": round(float(tamanho.value * np.hypot(c, d)), 2),
                # ponto de origem da linha de base e se o texto está na horizontal
                "base": (round(e, 2), round(f, 2)),
                "horizontal": abs(b) < 1e-3 and abs(c) < 1e-3 and a > 0,
                # modo 3 é texto invisível, usado na camada de OCR de PDFs pesquisáveis
                "visivel": raw.FPDFTextObj_GetTextRenderMode(obj.raw) != 3,
            })

        elif obj.type == raw.FPDF_PAGEOBJ_IMAGE:
            try:
                px = obj.get_px_size()
            except Exception:
                px = (0, 0)
            imagens.append({"ordem": ordem, "caixa": caixa, "px": px, "objeto": obj})

        elif obj.type == raw.FPDF_PAGEOBJ_PATH:
            preenchimento, traco = ctypes.c_int(), ctypes.c_int()
            raw.FPDFPath_GetDrawMode(obj.raw, preenchimento, traco)
            if preenchimento.value:
                r, g, b, a = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
                raw.FPDFPageObj_GetFillColor(obj.raw, r, g, b, a)
                formas.append({"ordem": ordem, "caixa": caixa, "cor": (r.value, g.value, b.value), "opaca": a.value >= 250})

    anotacoes = []
    for i in range(raw.FPDFPage_GetAnnotCount(page.raw)):
        anotacao = raw.FPDFPage_GetAnnot(page.raw, i)
        anotacoes.append(raw.FPDFAnnot_GetSubtype(anotacao))
        raw.FPDFPage_CloseAnnot(anotacao)

    return {"largura": largura, "altura": altura, "textos": textos, "imagens": imagens, "formas": formas, "anotacoes": anotacoes}


def _area(caixa):
    return max(0.0, caixa[2] - caixa[0]) * max(0.0, caixa[3] - caixa[1])


def _imagem_da_pagina(page, objetos):
    """
    Pixels da página tratada como imagem e se eles são os originais de um JPEG. Com uma única
    imagem relevante, usa os pixels dela, sem reamostrar. Com várias (o "Imprimir em PDF" fatia a
    página em faixas), renderiza a página na resolução das imagens.
    """
    imagens = sorted(objetos["imagens"], key=lambda imagem: _area(imagem["caixa"]), reverse=True)
    maior = imagens[0]
    relevantes = [imagem for imagem in imagens if _area(imagem["caixa"]) >= 0.2 * _area(maior["caixa"])]

    if len(relevantes) == 1:
        try:
            rgb = np.asarray(maior["objeto"].get_bitmap(render=False).to_pil().convert("RGB"))
            return rgb, "DCTDecode" in maior["objeto"].get_filters()
        except Exception:
            pass

    largura_pt = max(maior["caixa"][2] - maior["caixa"][0], 1)
    escala = min(max(maior["px"][0] / largura_pt, 1.0), 300 / 72) if maior["px"][0] else 200 / 72
    return np.asarray(page.render(scale=escala).to_pil().convert("RGB")), False


def paginas_do_pdf(path, max_paginas=None):
    doc = pdfium.PdfDocument(path)
    try:
        paginas = []
        for i in range(len(doc) if max_paginas is None else min(len(doc), max_paginas)):
            page = doc[i]
            objetos = objetos_da_pagina(page)
            area = objetos["largura"] * objetos["altura"] or 1
            cobertura = min(1.0, sum(_area(imagem["caixa"]) for imagem in objetos["imagens"]) / area)
            objetos["cobertura_de_imagem"] = round(cobertura, 2)

            caracteres = sum(len(texto["texto"].strip()) for texto in objetos["textos"] if texto["visivel"])
            objetos["caracteres_visiveis"] = caracteres
            maior = max((_area(imagem["caixa"]) / area for imagem in objetos["imagens"]), default=0)
            imagem_razoavel = any(min(imagem["px"]) >= LADO_MINIMO_DE_IMAGEM for imagem in objetos["imagens"])

            if maior >= COBERTURA_DE_PAGINA_INTEIRA or (caracteres < MINIMO_DE_CARACTERES_VETORIAIS and imagem_razoavel):
                rgb, jpeg = _imagem_da_pagina(page, objetos)
                pagina = _pagina_de_imagem(i + 1, rgb, jpeg, objetos)
            else:
                formato = "pdf_digital" if caracteres >= MINIMO_DE_CARACTERES_VETORIAIS else "pdf_sem_texto"
                pagina = Pagina(i + 1, formato, objetos=objetos)

            # os objetos do pdfium só valem com o documento aberto
            for imagem in objetos["imagens"]:
                imagem.pop("objeto", None)
            paginas.append(pagina)
        return paginas
    finally:
        doc.close()


def paginas_do_documento(path, max_paginas=None):
    """
    Páginas do documento (PDF ou imagem), cada uma com seu formato.
    """
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return paginas_do_pdf(path, max_paginas)

    with Image.open(path) as imagem:
        jpeg = imagem.format == "JPEG"
        rgb = np.asarray(imagem.convert("RGB"))
    return [_pagina_de_imagem(1, rgb, jpeg)]
