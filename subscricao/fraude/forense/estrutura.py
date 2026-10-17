"""
Medidas forenses na estrutura de uma página de PDF. Em PDF gerado por software não há ruído nem
compressão a examinar: a página é desenhada a partir de objetos (textos, formas, imagens), e é
neles que uma edição deixa rastro. Em página digitalizada dentro de PDF, o rastro é o que foi
desenhado por cima da imagem.

Cada medida retorna o valor do sinal e exemplos do que foi encontrado, para o relatório.
"""
import re
from collections import Counter, defaultdict

import pypdfium2.raw as raw

from .formato import descreve_posicao

# Sinais do texto vetorial, medidos nas páginas de PDF gerado por software
SINAIS_DE_TEXTO = ("texto_substituido", "texto_oculto", "fontes_raras", "fonte_nao_embutida", "fonte_duplicada",
                   "linha_desalinhada", "tamanho_destoante")

# Sinais do que foi desenhado sobre a imagem, medidos nas páginas de PDF que são uma imagem
SINAIS_DE_SOBREPOSICAO = ("texto_sobre_imagem", "forma_sobre_imagem", "imagem_sobre_imagem")

SINAIS = SINAIS_DE_TEXTO + SINAIS_DE_SOBREPOSICAO + ("anotacoes_de_edicao",)

# Fontes de símbolos e de códigos de barras: usadas em poucos caracteres por natureza
FONTES_DE_SIMBOLOS = ("symbol", "wingding", "webding", "dingbat", "barcode", "code128", "code39", "qrcode", "i2of5", "interleaved")

# Anotações que desenham conteúdo por cima da página
ANOTACOES_DE_EDICAO = {
    raw.FPDF_ANNOT_FREETEXT: "caixa de texto", raw.FPDF_ANNOT_STAMP: "carimbo", raw.FPDF_ANNOT_INK: "traço à mão",
    raw.FPDF_ANNOT_SQUARE: "retângulo", raw.FPDF_ANNOT_REDACT: "tarja",
}

MAXIMO_DE_EXEMPLOS = 4


def _area(caixa):
    return max(0.0, caixa[2] - caixa[0]) * max(0.0, caixa[3] - caixa[1])


def _intersecao(a, b):
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def _coberto(texto, forma):
    """
    Fração do trecho de texto escondida pela forma. Conta o trecho quase todo coberto e também o
    coberto em parte por uma forma da altura da linha: o rótulo e o valor de um campo costumam
    vir no mesmo trecho, e quem adultera cobre só o valor. Sublinhados e riscos, mais finos que a
    linha, não contam.
    """
    caixa, area = texto["caixa"], _area(texto["caixa"])
    if area <= 0:
        return 0.0
    fracao = _intersecao(caixa, forma["caixa"]) / area
    altura = (min(caixa[3], forma["caixa"][3]) - max(caixa[1], forma["caixa"][1])) / (caixa[3] - caixa[1])
    return fracao if fracao >= 0.8 or (fracao >= 0.2 and altura >= 0.8) else 0.0


def _onde(caixa, objetos):
    # as coordenadas do PDF partem do canto inferior esquerdo
    x = (caixa[0] + caixa[2]) / 2 / (objetos["largura"] or 1)
    y = 1 - (caixa[1] + caixa[3]) / 2 / (objetos["altura"] or 1)
    return descreve_posicao(x, y)


def _trecho(textos):
    return " ".join(texto["texto"].strip() for texto in textos)[:60]


def sobreposicoes(objetos):
    """
    Texto escondido por uma forma opaca desenhada depois dele e, quando há texto novo desenhado
    por cima da mesma forma, a substituição completa: é o que fazem os editores que "apagam" com um
    retângulo e escrevem por cima. Retorna (caracteres substituídos, caracteres ocultos) e os
    exemplos de cada um.
    """
    area_da_pagina = objetos["largura"] * objetos["altura"]
    visiveis = [texto for texto in objetos["textos"] if texto["visivel"] and texto["texto"].strip()]
    substituidos = ocultos = 0
    exemplos = {"texto_substituido": [], "texto_oculto": []}

    for forma in objetos["formas"]:
        # fundos de página e de seção não escondem texto: o texto vem depois deles
        if not forma["opaca"] or _area(forma["caixa"]) > 0.5 * area_da_pagina:
            continue
        escondidos = [texto for texto in visiveis if texto["ordem"] < forma["ordem"] and _coberto(texto, forma)]
        if not escondidos:
            continue
        caracteres = sum(round(len(texto["texto"].strip()) * _coberto(texto, forma)) for texto in escondidos)
        por_cima = [texto for texto in visiveis if texto["ordem"] > forma["ordem"] and _coberto(texto, forma)]
        if por_cima:
            substituidos += caracteres
            exemplos["texto_substituido"].append(f"'{_trecho(escondidos)}' coberto e reescrito como '{_trecho(por_cima)}' ({_onde(forma['caixa'], objetos)})")
        else:
            ocultos += caracteres
            exemplos["texto_oculto"].append(f"'{_trecho(escondidos)}' coberto por uma forma ({_onde(forma['caixa'], objetos)})")

    return (substituidos, ocultos), exemplos


def _familia(nome):
    """
    Nome da fonte sem o prefixo de subconjunto e sem as grafias que mudam de um gerador para
    outro: ArialMT, Arial e ABCDEF+ArialMT são a mesma fonte; Arial,Bold e Arial-BoldMT também.
    """
    nome = re.sub(r"[\s,_\-]", "", nome.split("+")[-1].lower())
    return re.sub(r"(psmt|mt|ps)(?=bold|italic|oblique|$)", "", nome)


def _raiz(nome):
    """Família da fonte sem o estilo: Arial-BoldMT e Arial,Italic têm a raiz de Arial."""
    return re.sub(r"bold|italic|oblique|black|light|medium|semi|demi|regular|narrow|condensed", "", _familia(nome))


def fontes(objetos):
    """
    Fontes usadas em poucos caracteres e fontes não embutidas no meio de fontes embutidas. Um
    valor reescrito num editor costuma sair em outra fonte, muitas vezes uma padrão do sistema,
    porque a fonte original do arquivo só traz os caracteres que o documento já usava.
    Retorna (caracteres em fontes raras, caracteres em fonte não embutida minoritária) e exemplos.
    """
    por_fonte, embutida, trechos = Counter(), {}, defaultdict(list)
    for texto in objetos["textos"]:
        if texto["visivel"] and texto["fonte"]:
            # só letras e números: marcadores e separadores costumam vir em fonte própria
            por_fonte[texto["fonte"]] += sum(c.isalnum() for c in texto["texto"])
            embutida[texto["fonte"]] = texto["embutida"]
            trechos[texto["fonte"]].append(texto)

    exemplos = {"fontes_raras": [], "fonte_nao_embutida": []}
    total = sum(por_fonte.values())
    if total < 200:
        return (0, 0), exemplos

    # o negrito ou o itálico de uma fonte comum na página não conta como fonte rara
    comuns = {_raiz(fonte) for fonte, n in por_fonte.items() if n >= 0.02 * total}
    raras = 0
    for fonte, n in por_fonte.items():
        if 0 < n < 0.02 * total and _raiz(fonte) not in comuns and not any(simbolo in fonte.lower() for simbolo in FONTES_DE_SIMBOLOS):
            raras += n
            exemplos["fontes_raras"].append(f"'{_trecho(trechos[fonte])}' em {fonte}")

    nao_embutidos = sum(n for fonte, n in por_fonte.items() if not embutida[fonte])
    minoritaria = nao_embutidos if 0 < nao_embutidos < 0.2 * total else 0
    if minoritaria:
        for fonte, n in por_fonte.items():
            if n and not embutida[fonte]:
                exemplos["fonte_nao_embutida"].append(f"'{_trecho(trechos[fonte])}' em {fonte}, não embutida")

    return (raras, minoritaria), exemplos


def fontes_duplicadas(objetos):
    """
    Caracteres escritos numa segunda versão de uma fonte que a página já tem: outro subconjunto
    embutido, a versão não embutida ao lado da embutida ou o mesmo tipo com a grafia de outro
    gerador. O programa que gera o documento usa uma versão de cada fonte; o editor que reescreve
    um trecho acrescenta a sua.
    """
    versoes, trechos = defaultdict(Counter), defaultdict(list)
    for texto in objetos["textos"]:
        if texto["visivel"] and texto["recurso"]:
            versao = (texto["recurso"], texto["embutida"])
            versoes[_familia(texto["recurso"])][versao] += len(texto["texto"].strip())
            trechos[versao].append(texto)

    duplicados, exemplos = 0, []
    for contagem in versoes.values():
        usadas = [(n, versao) for versao, n in contagem.items() if n > 0]
        if len(usadas) > 1:
            principal = max(usadas)[1]
            for n, versao in usadas:
                if versao != principal:
                    duplicados += n
                    exemplos.append(f"'{_trecho(trechos[versao])}' em {versao[0]}, enquanto o restante usa {principal[0]}")
    return duplicados, {"fonte_duplicada": exemplos}


def alinhamento(objetos):
    """
    Trechos com a linha de base levemente deslocada em relação à própria linha. Geradores de
    documento posicionam a linha inteira com o mesmo valor; o trecho inserido à mão raramente
    coincide.
    """
    linhas = defaultdict(list)
    for texto in objetos["textos"]:
        if texto["visivel"] and texto["horizontal"] and texto["tamanho"] > 0 and texto["texto"].strip():
            # trechos cuja linha de base cai na mesma faixa de meia altura de fonte
            linhas[round(texto["base"][1] / max(texto["tamanho"] * 0.5, 1))].append(texto)

    desalinhados, exemplos = 0, []
    for trechos in linhas.values():
        if len(trechos) < 3:
            continue
        base = Counter(round(texto["base"][1], 1) for texto in trechos).most_common(1)[0][0]
        tamanho = Counter(texto["tamanho"] for texto in trechos).most_common(1)[0][0]

        for texto in trechos:
            mesmo_tamanho = abs(texto["tamanho"] - tamanho) <= 0.02 * tamanho
            desvio = abs(texto["base"][1] - base)
            # deslocamento pequeno demais para ser sobrescrito ou subscrito
            if mesmo_tamanho and 0.3 <= desvio <= 0.2 * tamanho:
                desalinhados += 1
                exemplos.append(f"'{_trecho([texto])}' {desvio:.1f} pt fora da linha ({_onde(texto['caixa'], objetos)})")

    return desalinhados, {"linha_desalinhada": exemplos}


def tamanhos_destoantes(objetos):
    """
    Trechos em tamanho de fonte quase igual, mas não igual, a um tamanho muito mais usado na
    página (11,4 no meio de um documento em 11). Quem reescreve um trecho acerta o tamanho no
    olho.
    """
    trechos = [texto for texto in objetos["textos"] if texto["visivel"] and texto["tamanho"] > 0 and texto["texto"].strip()]
    por_tamanho = Counter()
    for texto in trechos:
        por_tamanho[texto["tamanho"]] += len(texto["texto"].strip())

    destoantes, exemplos = 0, []
    for texto in trechos:
        tamanho = texto["tamanho"]
        parecidos = [(n, outro) for outro, n in por_tamanho.items() if 0.01 * outro < abs(outro - tamanho) <= 0.08 * outro]
        if parecidos and max(parecidos)[0] >= 10 * por_tamanho[tamanho]:
            destoantes += 1
            exemplos.append(f"'{_trecho([texto])}' em tamanho {tamanho:g}, ao lado de texto em {max(parecidos)[1]:g}")
    return destoantes, {"tamanho_destoante": exemplos}


def sobre_imagem(objetos):
    """
    O que foi desenhado por cima da imagem que ocupa a página: texto vetorial visível (a camada
    de OCR de um PDF pesquisável é invisível e não conta), formas opacas pequenas e imagens
    menores. É o que deixa o editor de PDF usado sobre um documento digitalizado.
    Retorna (caracteres de texto, formas, imagens) e exemplos.
    """
    exemplos = {sinal: [] for sinal in SINAIS_DE_SOBREPOSICAO}
    area_da_pagina = objetos["largura"] * objetos["altura"]
    de_pagina = [imagem for imagem in objetos["imagens"] if _area(imagem["caixa"]) >= 0.6 * area_da_pagina]
    if not de_pagina:
        return (0, 0, 0), exemplos
    fundo = min(de_pagina, key=lambda imagem: imagem["ordem"])

    def por_cima(objeto):
        return objeto["ordem"] > fundo["ordem"] and _intersecao(objeto["caixa"], fundo["caixa"]) > 0

    textos = [texto for texto in objetos["textos"] if texto["visivel"] and texto["texto"].strip() and por_cima(texto)]
    caracteres = sum(len(texto["texto"].strip()) for texto in textos)
    exemplos["texto_sobre_imagem"] = [f"'{_trecho([texto])}' ({_onde(texto['caixa'], objetos)})" for texto in textos]

    # do tamanho de um campo até um quinto da página: nem ponto de sujeira, nem fundo
    formas = [forma for forma in objetos["formas"]
              if forma["opaca"] and por_cima(forma) and 0.0002 * area_da_pagina <= _area(forma["caixa"]) <= 0.2 * area_da_pagina]
    exemplos["forma_sobre_imagem"] = [f"forma de cor {forma['cor']} ({_onde(forma['caixa'], objetos)})" for forma in formas]

    imagens = [imagem for imagem in objetos["imagens"]
               if imagem is not fundo and por_cima(imagem) and 0.0002 * area_da_pagina <= _area(imagem["caixa"]) <= 0.3 * area_da_pagina]
    exemplos["imagem_sobre_imagem"] = [f"imagem de {imagem['px'][0]}x{imagem['px'][1]} px ({_onde(imagem['caixa'], objetos)})" for imagem in imagens]

    return (caracteres, len(formas), len(imagens)), exemplos


def anotacoes(objetos):
    """Anotações que desenham conteúdo por cima da página."""
    nomes = [ANOTACOES_DE_EDICAO[subtipo] for subtipo in objetos["anotacoes"] if subtipo in ANOTACOES_DE_EDICAO]
    return len(nomes), {"anotacoes_de_edicao": [f"{n} x {nome}" for nome, n in Counter(nomes).items()]}


def medir(objetos):
    """
    Sinais forenses estruturais da página de PDF e exemplos do que cada um encontrou.
    """
    (substituido, oculto), exemplos = sobreposicoes(objetos)
    (raras, nao_embutida), outros = fontes(objetos)
    exemplos.update(outros)

    sinais = {"texto_substituido": substituido, "texto_oculto": oculto, "fontes_raras": raras, "fonte_nao_embutida": nao_embutida}
    for sinal, medida in (("fonte_duplicada", fontes_duplicadas), ("linha_desalinhada", alinhamento),
                          ("tamanho_destoante", tamanhos_destoantes), ("anotacoes_de_edicao", anotacoes)):
        sinais[sinal], outros = medida(objetos)
        exemplos.update(outros)

    (texto, formas, imagens), outros = sobre_imagem(objetos)
    sinais.update({"texto_sobre_imagem": texto, "forma_sobre_imagem": formas, "imagem_sobre_imagem": imagens})
    exemplos.update(outros)

    return sinais, {sinal: lista[:MAXIMO_DE_EXEMPLOS] for sinal, lista in exemplos.items() if lista}
