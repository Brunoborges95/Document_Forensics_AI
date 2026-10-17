"""
Medidas forenses nos pixels de uma página. As duas se apoiam no ruído do papel fotografado ou
digitalizado, que existe em quase todo pixel e nunca se repete:

    campo_liso      campo reescrito por cima da imagem. O editor pinta um retângulo com a cor do
                    papel e digita o texto novo; o retângulo não tem ruído. Compara, em cada
                    janela do tamanho de um campo, a fração de pixels com ruído fora dos traços do
                    texto com a da moldura ao redor da janela.
    copia_interna   copy-move: trecho copiado de outro ponto da mesma página. Pontos de interesse
                    (SIFT) casados com os da própria página, agrupados pelo deslocamento comum e
                    confirmados pela correlação do ruído entre os dois trechos: letras iguais se
                    repetem em qualquer documento, o ruído ao redor delas não.

Sem ruído não há o que comparar, e por isso nenhuma se aplica a print de tela nem a página em
preto e branco puro. As medidas por bloco da referência (ELA, ruído, nitidez, tom do fundo e
grade JPEG) ficaram de fora: nas adulterações sintéticas do estudo nenhuma reagiu a um campo
adulterado, e o ELA dispara em qualquer JPEG que só foi regravado.
"""
import os

import cv2
import numpy as np

# Sinais medidos nos pixels
SINAIS = ("campo_liso", "copia_interna")

# Altura de uma linha de texto, como fração do lado maior da página
ALTURA_DA_LINHA = 0.012

# campo_liso: escalas examinadas, em alturas de linha; janela de um campo e moldura ao redor
# dela (largura, altura), também em alturas de linha
ESCALAS = (1, 2)
CAMPO = (4, 1)
MOLDURA = (6, 3)
# somado às frações comparadas, para que uma janela quase sem ruído não gere razão infinita
PISO = 0.05

# copia_interna: pontos de interesse por página, vizinhos consultados por ponto, distância máxima
# entre descritores (norma do SIFT) e mínimo de pares com o mesmo deslocamento
MAXIMO_DE_PONTOS = 20000
VIZINHOS = 4
DISTANCIA_DE_DESCRITOR = 120.0
MINIMO_DE_PARES = 4
PASSO_DO_DESLOCAMENTO = 4
GRUPOS_EXAMINADOS = 15
MINIMO_DE_PIXELS = 150

_torch = None


def gpu():
    """
    O torch com CUDA, quando disponível, ou False. O OpenCV do pip não traz CUDA e o OpenCL dele
    não rende nestas operações; o passo caro (casar descritores) vai para a GPU pelo torch, cerca
    de 30 vezes mais rápido que na CPU. FORENSE_GPU=0 desliga.
    """
    global _torch
    if _torch is None:
        _torch = False
        if os.environ.get("FORENSE_GPU", "1") != "0":
            try:
                import torch
                if torch.cuda.is_available():
                    _torch = torch
            except Exception:
                pass
    return _torch


def _linha(cinza):
    return max(8, int(round(max(cinza.shape) * ALTURA_DA_LINHA)))


def _tracos(cinza):
    """Traços do texto: os pixels de gradiente forte."""
    gx = cv2.Sobel(cinza, cv2.CV_32F, 1, 0, ksize=3) / 8
    gy = cv2.Sobel(cinza, cv2.CV_32F, 0, 1, ksize=3) / 8
    gradiente = np.sqrt(gx * gx + gy * gy)
    tracos = (gradiente >= max(6.0, 0.25 * float(np.percentile(gradiente, 99)))).astype(np.uint8)
    # fora dos traços e da vizinhança imediata deles, onde fica a suavização das letras
    liso = cv2.dilate(tracos, np.ones((3, 3), np.uint8)) == 0
    return tracos.astype(np.float32), liso


def campo_liso(cinza, tracos, liso):
    """
    Maior contraste, em log2, entre a fração de pixels com ruído ao redor de uma janela de texto
    e dentro dela, e a posição dessa janela em fração da página (x, y a partir do canto superior
    esquerdo). Zero quando não há janela a comparar.
    """
    liso = liso.astype(np.float32)
    # pixel com ruído: difere da mediana dos vizinhos
    com_ruido = (cv2.absdiff(cinza, cv2.medianBlur(cinza, 3)) > 0).astype(np.float32) * liso

    maior, regiao = 0.0, None
    for escala in ESCALAS:
        linha = escala * _linha(cinza)
        campo = (CAMPO[0] * linha, CAMPO[1] * linha)
        moldura = (MOLDURA[0] * linha, MOLDURA[1] * linha)
        passo = max(2, linha // 2)

        def soma(a, janela):
            return cv2.boxFilter(a, -1, janela, normalize=False)[::passo, ::passo]

        ruido_dentro, lisos_dentro = soma(com_ruido, campo), soma(liso, campo)
        ruido_fora, lisos_fora = soma(com_ruido, moldura) - ruido_dentro, soma(liso, moldura) - lisos_dentro

        area = campo[0] * campo[1]
        # a janela precisa ter texto, fundo para medir e moldura com fundo para comparar
        validos = (soma(tracos, campo) >= 0.03 * area) & (lisos_dentro >= 0.3 * area) & (lisos_fora >= 0.6 * area)
        if validos.sum() < 30:
            continue

        dentro = ruido_dentro / np.maximum(lisos_dentro, 1)
        fora = ruido_fora / np.maximum(lisos_fora, 1)
        contraste = np.where(validos, np.log2((fora + PISO) / (dentro + PISO)), -np.inf)
        y, x = np.unravel_index(int(np.argmax(contraste)), contraste.shape)
        if contraste[y, x] > maior:
            maior = float(contraste[y, x])
            regiao = (round(float((x + 0.5) / contraste.shape[1]), 3), round(float((y + 0.5) / contraste.shape[0]), 3))

    return round(maior, 2), regiao


def vizinhos_proximos(descritores, k):
    """Distâncias e índices dos k descritores mais próximos de cada descritor (o primeiro é ele mesmo)."""
    torch = gpu()
    if torch:
        d = torch.from_numpy(descritores).cuda()
        distancias, indices = [], []
        for parte in d.split(4096):
            proximos = torch.cdist(parte, d).topk(k, largest=False)
            distancias.append(proximos.values)
            indices.append(proximos.indices)
        return torch.cat(distancias).cpu().numpy(), torch.cat(indices).cpu().numpy()

    pares = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=48)).knnMatch(descritores, descritores, k=k)
    distancias = np.array([[par.distance for par in p] + [np.inf] * (k - len(p)) for p in pares], np.float32)
    indices = np.array([[par.trainIdx for par in p] + [-1] * (k - len(p)) for p in pares], np.int64)
    return distancias, indices


def copia_interna(cinza, liso):
    """
    Maior correlação do ruído entre dois trechos da página que têm o mesmo conteúdo, e a posição
    dos dois trechos em fração da página. Zero quando nenhum trecho se repete.
    """
    h, w = cinza.shape
    linha = _linha(cinza)
    pontos, descritores = cv2.SIFT_create(nfeatures=MAXIMO_DE_PONTOS, contrastThreshold=0.02).detectAndCompute(cinza, None)
    if descritores is None or len(pontos) < 50:
        return 0.0, None
    xy = np.array([ponto.pt for ponto in pontos], np.float32)
    distancias, indices = vizinhos_proximos(descritores, VIZINHOS)

    origem = np.repeat(np.arange(len(xy)), VIZINHOS)
    destino = indices.ravel()
    iguais = (distancias.ravel() <= DISTANCIA_DE_DESCRITOR) & (destino >= 0) & (destino != origem)
    origem, destino = origem[iguais], destino[iguais]
    deslocamento = xy[destino] - xy[origem]
    # longe o bastante para não ser o próprio trecho, e cada par numa direção só
    longe = np.hypot(deslocamento[:, 0], deslocamento[:, 1]) >= 2 * linha
    direcao = (deslocamento[:, 0] > 0) | ((deslocamento[:, 0] == 0) & (deslocamento[:, 1] > 0))
    origem, deslocamento = origem[longe & direcao], deslocamento[longe & direcao]
    if len(origem) < MINIMO_DE_PARES:
        return 0.0, None

    # o trecho copiado desloca todos os seus pontos do mesmo tanto
    _, grupo_do_par, pares_no_grupo = np.unique(np.round(deslocamento / PASSO_DO_DESLOCAMENTO).astype(np.int64), axis=0, return_inverse=True, return_counts=True)
    grupo_do_par = grupo_do_par.ravel()
    residuo = cinza.astype(np.float32) - cv2.medianBlur(cinza, 3).astype(np.float32)

    melhor, regiao = 0.0, None
    for grupo in np.argsort(-pares_no_grupo)[:GRUPOS_EXAMINADOS]:
        if pares_no_grupo[grupo] < MINIMO_DE_PARES:
            break
        membros = np.nonzero(grupo_do_par == grupo)[0][:2000]
        p = xy[origem[membros]]
        # o trecho copiado é compacto: ficam os pontos ao redor do mais povoado
        perto = (np.abs(p[:, None, 0] - p[None, :, 0]) <= 6 * linha) & (np.abs(p[:, None, 1] - p[None, :, 1]) <= 2 * linha)
        nucleo = membros[perto[int(np.argmax(perto.sum(axis=1)))]]
        if len(nucleo) < MINIMO_DE_PARES:
            continue

        p = xy[origem[nucleo]]
        dx, dy = (int(d) for d in np.round(np.median(deslocamento[nucleo], axis=0)))
        x0, y0 = int(max(p[:, 0].min() - linha / 2, 0)), int(max(p[:, 1].min() - linha / 2, 0))
        x1, y1 = int(min(p[:, 0].max() + linha / 2, w)), int(min(p[:, 1].max() + linha / 2, h))

        # letras iguais dão descritores iguais; só a cópia traz o mesmo ruído no fundo
        correlacao = 0.0
        for ay in (dy - 1, dy, dy + 1):
            for ax in (dx - 1, dx, dx + 1):
                if x0 + ax < 0 or y0 + ay < 0 or x1 + ax > w or y1 + ay > h:
                    continue
                fundo = liso[y0:y1, x0:x1] & liso[y0 + ay:y1 + ay, x0 + ax:x1 + ax]
                if fundo.sum() < MINIMO_DE_PIXELS:
                    continue
                a, b = residuo[y0:y1, x0:x1][fundo], residuo[y0 + ay:y1 + ay, x0 + ax:x1 + ax][fundo]
                if a.std() >= 0.3 and b.std() >= 0.3:
                    correlacao = max(correlacao, float(np.corrcoef(a, b)[0, 1]))

        if correlacao > melhor:
            melhor = correlacao
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            regiao = [(round(cx / w, 3), round(cy / h, 3)), (round((cx + dx) / w, 3), round((cy + dy) / h, 3))]

    return round(melhor, 3), regiao


def medir(rgb, sinais=SINAIS):
    """
    Sinais forenses da página de imagem e a posição, em fração da página, da região apontada por
    cada um (duas posições no copia_interna: os dois trechos iguais).
    """
    cinza = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    tracos, liso = _tracos(cinza)

    valores, regioes = {}, {}
    for sinal in sinais:
        valor, regiao = campo_liso(cinza, tracos, liso) if sinal == "campo_liso" else copia_interna(cinza, liso)
        valores[sinal] = valor
        if regiao:
            regioes[sinal] = regiao
    return valores, regioes
