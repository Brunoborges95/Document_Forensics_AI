"""
Avaliador forense genérico: depende só do formato em que o documento chegou (formato.py), não do
tipo de documento. Mede os sinais que fazem sentido em cada formato, transforma cada valor em
raridade entre páginas autênticas do mesmo formato (calibracao.py) e compara a raridade do
documento com um limiar único, a sensibilidade.
"""
import math

from . import calibracao as calibragem
from . import estrutura, raster
from .formato import FORMATOS_DE_IMAGEM, descreve_posicao, paginas_do_documento

# Sensibilidade (0 a 10) -> fração dos documentos autênticos que se aceita sinalizar (MODERADO ou
# ALTO). Em 0 nada é sinalizado; a cada passo o avaliador aceita mais alarmes falsos para deixar
# passar menos adulterações
ALARME_FALSO = (0.0, 0.002, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.20, 0.30)

# A de melhor compromisso no estudo de calibração: daí para cima a detecção das adulterações
# sintéticas quase não cresce e o alarme falso segue subindo (tabela no README)
SENSIBILIDADE_PADRAO = 8

# ALTO: o documento é pelo menos este número de vezes mais raro que o limiar
FATOR_DO_NIVEL_ALTO = 5

# Páginas analisadas por documento
MAX_PAGINAS = 5

BAIXO, MODERADO, ALTO, NAO_ANALISAVEL = "BAIXO", "MODERADO", "ALTO", "N/A"

# Sinais de pixels medidos em cada formato de imagem. Print de tela e preto e branco puro não têm
# ruído de papel a examinar; na imagem limpa só o copy-move tem algum alcance
SINAIS_DE_PIXELS = {
    "foto": ("campo_liso", "copia_interna"),
    "digitalizacao": ("campo_liso", "copia_interna"),
    "imagem_limpa": ("copia_interna",),
}

# Sinais do texto vetorial que entram na pontuação do PDF gerado por software. fontes_raras e
# linha_desalinhada são medidos (estrutura.py) mas ficam de fora: aparecem em um quarto das
# páginas autênticas e, dividindo o limiar com os outros, atrasavam em um nível de sensibilidade
# a detecção dos sinais específicos
SINAIS_DE_TEXTO = tuple(sinal for sinal in estrutura.SINAIS_DE_TEXTO if sinal not in ("fontes_raras", "linha_desalinhada"))

FORMATOS = {
    "pdf_digital": "PDF gerado por software",
    "pdf_sem_texto": "PDF vetorial sem texto",
    "digitalizacao": "papel digitalizado",
    "foto": "fotografia do documento",
    "imagem_limpa": "imagem sem ruído de papel",
    "captura_de_tela": "print de tela",
    "bitonal": "digitalização em preto e branco puro",
}

DESCRICOES = {
    "campo_liso": "campo de texto com o fundo liso no meio de papel com ruído: indício de trecho reescrito por cima da imagem",
    "copia_interna": "dois trechos da página com o mesmo conteúdo e o mesmo ruído: indício de trecho copiado de outro ponto do documento",
    "texto_substituido": "texto coberto por uma forma opaca e reescrito por cima",
    "texto_oculto": "texto escondido sob uma forma opaca",
    "fonte_nao_embutida": "trechos em fonte não embutida no meio de fontes embutidas",
    "fonte_duplicada": "trechos numa segunda versão de uma fonte que a página já usa",
    "tamanho_destoante": "trechos em tamanho de fonte quase igual, mas não igual, ao do restante",
    "texto_sobre_imagem": "texto digitado por cima da imagem do documento",
    "forma_sobre_imagem": "forma opaca desenhada por cima da imagem do documento",
    "imagem_sobre_imagem": "imagem menor colada por cima da imagem do documento",
    "anotacoes_de_edicao": "anotações que desenham conteúdo por cima da página",
}

# O que a análise enxerga e o que não enxerga em cada formato: vai no relatório, para que um
# nível BAIXO não seja lido como atestado de autenticidade
ALCANCE = {
    "pdf_digital": "examina a estrutura do arquivo (fontes, sobreposições, anotações). Detecta edição feita no PDF depois de "
                   "gerado; não detecta documento refeito na origem e exportado de novo, nem PDF reimpresso.",
    "pdf_sem_texto": "as letras estão em curvas ou a página não tem texto; só anotações são examinadas.",
    "digitalizacao": "examina o ruído do papel. Detecta campo reescrito por cima da imagem (se o arquivo não foi regravado com "
                     "perda depois) e trecho copiado de outro ponto da página; não detecta adulteração refeita com ruído nem "
                     "documento adulterado, impresso e digitalizado de novo.",
    "imagem_limpa": "sem ruído de papel, só trecho copiado de outro ponto da página é examinado, e com pouco alcance.",
    "captura_de_tela": "sem ruído de papel, não há medida confiável nos pixels.",
    "bitonal": "com dois tons apenas, não há medida confiável nos pixels.",
}
ALCANCE["foto"] = ALCANCE["digitalizacao"]
ALCANCE_EM_PDF = " O que foi desenhado por cima da imagem dentro do PDF (texto, formas, imagens, anotações) é examinado."

# Formatos em que nada da página em si pode ser medido. Dentro de um PDF, só o que foi desenhado
# por cima dela é examinado: sem nada por cima, a página não foi analisada, e dizer BAIXO seria
# ler como "sem problemas" o que é "sem medida"
SEM_MEDIDA_NA_PAGINA = ("captura_de_tela", "bitonal", "pdf_sem_texto")

# Quanto a análise alcança no documento, pelo melhor formato entre as páginas analisadas
ALCANCE_NORMAL, ALCANCE_LIMITADO, SEM_ALCANCE = "normal", "limitado", "nenhum"
ALCANCE_DO_FORMATO = {
    "pdf_digital": ALCANCE_NORMAL, "digitalizacao": ALCANCE_NORMAL, "foto": ALCANCE_NORMAL,
    "imagem_limpa": ALCANCE_LIMITADO,
    "captura_de_tela": SEM_ALCANCE, "bitonal": SEM_ALCANCE, "pdf_sem_texto": SEM_ALCANCE,
}


def medir_pagina(pagina):
    """Sinais aplicáveis ao formato da página, regiões apontadas e exemplos do que foi encontrado."""
    sinais, regioes, exemplos = {}, {}, {}

    de_pixels = SINAIS_DE_PIXELS.get(pagina.formato, ())
    if de_pixels and pagina.imagem is not None:
        sinais, regioes = raster.medir(pagina.imagem, de_pixels)

    if pagina.objetos:
        medidos, encontrados = estrutura.medir(pagina.objetos)
        nomes = ("anotacoes_de_edicao",)
        if pagina.formato == "pdf_digital":
            nomes += SINAIS_DE_TEXTO
        elif pagina.formato in FORMATOS_DE_IMAGEM:
            nomes += estrutura.SINAIS_DE_SOBREPOSICAO
        for nome in nomes:
            sinais[nome] = medidos[nome]
            if nome in encontrados:
                exemplos[nome] = encontrados[nome]

    return sinais, regioes, exemplos


def medir_documento(path, max_paginas=MAX_PAGINAS):
    """Medidas de cada página analisada do documento."""
    paginas = []
    for pagina in paginas_do_documento(path, max_paginas):
        sinais, regioes, exemplos = medir_pagina(pagina)
        paginas.append({"pagina": pagina.numero, "formato": pagina.formato, "em_pdf": bool(pagina.objetos),
                        "sinais": sinais, "regioes": regioes, "exemplos": exemplos})
    return paginas


def nivel_e_pontuacao(p, alarme_falso):
    """
    Nível de suspeição e pontuação de 0 a 10 a partir da raridade do documento. As faixas da
    pontuação seguem a prompt visual: BAIXO 0-3, MODERADO 4-6, ALTO 7-10.
    """
    if p > alarme_falso:
        referencia = alarme_falso if alarme_falso > 0 else ALARME_FALSO[1]
        return BAIXO, min(3, int(3 * math.log(p) / math.log(referencia))) if p < 1 else 0
    if p > alarme_falso / FATOR_DO_NIVEL_ALTO:
        return MODERADO, 4 + min(2, int(3 * math.log(alarme_falso / p) / math.log(FATOR_DO_NIVEL_ALTO)))
    return ALTO, 7 + min(3, int(3 * math.log10(alarme_falso / FATOR_DO_NIVEL_ALTO / p)))


def _onde(regiao):
    # uma posição (x, y) ou, no copy-move, as posições dos dois trechos
    if isinstance(regiao[0], (int, float)):
        return descreve_posicao(*regiao)
    return " e ".join(descreve_posicao(x, y) for x, y in regiao)


def avaliar(paginas, sensibilidade=SENSIBILIDADE_PADRAO, calibracao=None):
    """
    Nível de suspeição do documento a partir das medidas de medir_documento.
    """
    calibracao = calibracao or calibragem.carregar()
    alarme_falso = ALARME_FALSO[sensibilidade]
    avaliadas = []

    for pagina in paginas:
        referencia = calibracao["formatos"].get(pagina["formato"])
        sem_medida = pagina["formato"] in SEM_MEDIDA_NA_PAGINA and not any(pagina["sinais"].values())
        p, por_sinal = calibragem.raridade_da_pagina(referencia, pagina["sinais"]) if referencia and not sem_medida else (None, {})
        avaliada = {"pagina": pagina["pagina"], "formato": pagina["formato"], "em_pdf": pagina["em_pdf"], "raridade": p, "flags": [], "metricas": {}}
        for sinal, valor in pagina["sinais"].items():
            if sinal not in por_sinal:
                continue
            avaliada["metricas"][sinal] = {"valor": valor, "raridade": round(por_sinal[sinal], 4)}
            if valor > 0 and por_sinal[sinal] <= alarme_falso:
                flag = {"sinal": sinal, "descricao": DESCRICOES[sinal], "valor": valor, "raridade": round(por_sinal[sinal], 4)}
                if sinal in pagina["regioes"]:
                    flag["onde"] = _onde(pagina["regioes"][sinal])
                if sinal in pagina["exemplos"]:
                    flag["exemplos"] = pagina["exemplos"][sinal]
                avaliada["flags"].append(flag)
        if p is None:
            avaliada["nivel"], avaliada["pontuacao"] = NAO_ANALISAVEL, None
        else:
            avaliada["nivel"], avaliada["pontuacao"] = nivel_e_pontuacao(p, alarme_falso)
        avaliadas.append(avaliada)

    analisadas = [pagina for pagina in avaliadas if pagina["raridade"] is not None]
    resultado = {
        "sensibilidade": sensibilidade,
        "alarme_falso": alarme_falso,
        "formatos": sorted({pagina["formato"] for pagina in avaliadas}),
        "paginas": avaliadas,
    }
    if analisadas:
        # com várias páginas, a chance de alguma parecer rara por acaso cresce: corrige pelo número delas
        p = 1 - (1 - min(pagina["raridade"] for pagina in analisadas)) ** len(analisadas)
        resultado["raridade"] = round(p, 5)
        resultado["nivel"], resultado["pontuacao"] = nivel_e_pontuacao(p, alarme_falso)
    else:
        resultado["raridade"] = None
        resultado["nivel"], resultado["pontuacao"] = NAO_ANALISAVEL, None

    alcances = {ALCANCE_DO_FORMATO.get(pagina["formato"], SEM_ALCANCE) for pagina in analisadas}
    resultado["alcance"] = next((alcance for alcance in (ALCANCE_NORMAL, ALCANCE_LIMITADO) if alcance in alcances), SEM_ALCANCE)
    resultado["relatorio"] = relatorio(resultado)
    return resultado


def _percentual(p):
    return f"{100 * p:.1f}%".replace(".", ",")


def relatorio(resultado):
    """
    Relatório técnico em texto, para a prompt do avaliador visual e para o analista.
    """
    formatos = ", ".join(f"{formato} ({FORMATOS[formato]})" for formato in resultado["formatos"])
    linhas = [f"Formato do arquivo: {formatos}. Páginas analisadas: {len(resultado['paginas'])}."]

    if resultado["nivel"] == NAO_ANALISAVEL:
        linhas.append("NÍVEL DE SUSPEIÇÃO: N/A")
        linhas.append("Neste formato não há medida algorítmica confiável: a avaliação fica com a inspeção visual e com os demais avaliadores.")
    else:
        linhas.append(f"NÍVEL DE SUSPEIÇÃO: {resultado['nivel']} (score {resultado['pontuacao']}/10)")
        linhas.append(
            f"Sensibilidade {resultado['sensibilidade']} de 10: {_percentual(resultado['alarme_falso'])} dos documentos autênticos "
            f"recebem MODERADO ou ALTO. Sinais tão raros quanto os deste documento aparecem em {_percentual(resultado['raridade'])} dos autênticos no mesmo formato."
        )

        flags = [(pagina["pagina"], flag) for pagina in resultado["paginas"] for flag in pagina["flags"]]
        linhas.append("Flags:" if flags else "Flags: nenhuma.")
        for numero, flag in flags:
            onde = f" ({flag['onde']})" if "onde" in flag else ""
            linhas.append(f"- Página {numero}, {flag['sinal']}{onde}: {flag['descricao']}. "
                          f"Só {_percentual(flag['raridade'])} das páginas autênticas neste formato chegam a esse valor.")
            for exemplo in flag.get("exemplos", []):
                linhas.append(f"    {exemplo}")

        if resultado.get("alcance") == ALCANCE_LIMITADO:
            linhas.append("Alcance limitado: neste formato quase nada pode ser medido, e o nível diz pouco sobre o documento.")

        linhas.append("Métricas (valor | fração das páginas autênticas com valor igual ou maior):")
        for pagina in resultado["paginas"]:
            metricas = "; ".join(f"{sinal} {m['valor']:g} | {_percentual(m['raridade'])}" for sinal, m in pagina["metricas"].items() if m["valor"] > 0)
            linhas.append(f"- Página {pagina['pagina']} ({pagina['formato']}): {metricas or 'todos os sinais zerados'}")

    linhas.append("Alcance da análise:")
    vistos = set()
    for pagina in resultado["paginas"]:
        chave = (pagina["formato"], pagina["em_pdf"])
        if chave not in vistos:
            vistos.add(chave)
            em_pdf = ALCANCE_EM_PDF if pagina["em_pdf"] and pagina["formato"] in FORMATOS_DE_IMAGEM else ""
            linhas.append(f"- {pagina['formato']}: {ALCANCE[pagina['formato']]}{em_pdf}")
    linhas.append("Nível BAIXO não atesta autenticidade: indica apenas que estas medidas não acharam rastro de edição.")
    return "\n".join(linhas)


def analisar(path, sensibilidade=SENSIBILIDADE_PADRAO, max_paginas=MAX_PAGINAS, calibracao=None):
    """
    Análise forense de um documento (PDF ou imagem): formato de cada página, sinais, nível de
    suspeição pela sensibilidade dada e relatório em texto.
    """
    return avaliar(medir_documento(path, max_paginas), sensibilidade, calibracao)
