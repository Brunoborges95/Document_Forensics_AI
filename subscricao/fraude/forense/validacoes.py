"""
Validações do arquivo: conferências de sim ou não feitas por código sobre o arquivo recebido
(assinatura digital, programa gerador, formato, datas dos metadados, marcas de geração por IA).

Ficam ao lado dos sinais do avaliador (avaliador.py). Os sinais medem rastro de edição e viram
nível pela raridade entre autênticos; as validações têm critério fixo e não dependem de
calibração. Três delas dependem do tipo de documento: comparam o arquivo com o que o catálogo
espera do tipo ("arquivo_esperado": formatos, programas geradores e assinatura digital). As
demais valem para qualquer documento.

Cada validação é uma função registrada com @validacao. Ela recebe o Arquivo e devolve
aprovada(...), reprovada(...), nao_se_aplica(...) ou nao_conferida(...). A reprovada vira flag
da análise de fraude, com a severidade configurada em fraude.json (forense.validacoes).
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path

from PIL import Image

from .avaliador import FORMATOS as ROTULOS_DOS_FORMATOS
from .formato import FORMATOS_DE_IMAGEM

logger = logging.getLogger(__name__)

# Situação de uma validação
APROVADA = "APROVADA"
REPROVADA = "REPROVADA"
# a validação não tem o que conferir neste arquivo ou neste tipo de documento
NAO_SE_APLICA = "NAO_SE_APLICA"
# não deu para conferir: biblioteca que falta, arquivo que não abre
NAO_CONFERIDA = "NAO_CONFERIDA"

# Severidade da flag de uma validação reprovada, com os nomes que as regras de decisão usam. A
# informativa não vira flag: vai só para o resultado e para o orquestrador, que a avalia pelas
# regras da prompt
CRITICA, MODERADA, BAIXA, INFORMATIVA = "CRÍTICA", "MODERADA", "BAIXA", "INFORMATIVA"
SEVERIDADES = (CRITICA, MODERADA, BAIXA, INFORMATIVA)

# Fonte das flags que saem daqui, ao lado das fontes das flags do orquestrador
FONTE = "VALIDACAO_DO_ARQUIVO"

# As validações que comparam o arquivo com o esperado para o tipo de documento descrevem o mesmo
# fato (o arquivo não é o que o emissor entrega) e por isso viram uma flag só. A flag é crítica:
# o arquivo fora do esperado torna o documento suspeito sozinho, por decisão de quem opera a POC
# (13/10/2026), com o alarme falso medido no README
ARQUIVO_ESPERADO = "arquivo_esperado"

# Tolerância nas comparações de datas dos metadados, que carregam fuso horário
TOLERANCIA_DE_DATA = timedelta(days=1)

# Valores com que o padrão IPTC (usado nos metadados XMP e nas credenciais de conteúdo C2PA)
# declara a origem de uma imagem: gerada por modelo de IA, ou editada com um
GERADO_POR_IA = b"digitalsourcetype/trainedAlgorithmicMedia"
EDITADO_COM_IA = b"digitalsourcetype/compositeWithTrainedAlgorithmicMedia"

# Programas de edição gráfica, procurados no programa gravado nos metadados
EDITORES_GRAFICOS = (
    "photoshop", "illustrator", "indesign", "gimp", "coreldraw", "corel photo", "inkscape", "affinity", "canva", "figma",
    "pixlr", "photopea", "photoscape", "paint.net", "picsart", "snapseed", "pixelmator", "krita", "lightroom",
)

# nome -> validação, na ordem em que aparecem no resultado
VALIDACOES = {}


def validacao(nome, titulo, problema, severidade, grupo=None, categoria="CONTEXTO"):
    """
    Marca uma função como validação do arquivo.

    - titulo: o que precisa ser verdade para a validação ser aprovada
    - problema: o que a flag diz quando ela é reprovada
    - severidade: a severidade padrão dessa flag (fraude.json pode trocar)
    - grupo: validações do mesmo grupo viram uma flag só, com a maior severidade entre elas
    - categoria: a categoria da flag, entre as do orquestrador
    """
    def decorator(func):
        if nome in VALIDACOES:
            raise ValueError(f"Já existe uma validação do arquivo chamada '{nome}'.")
        func.titulo, func.problema, func.severidade, func.grupo, func.categoria = titulo, problema, severidade, grupo, categoria
        VALIDACOES[nome] = func
        return func

    return decorator


def aprovada(detalhe, **dados):
    return {"situacao": APROVADA, "detalhe": detalhe, "dados": dados}


def reprovada(detalhe, **dados):
    return {"situacao": REPROVADA, "detalhe": detalhe, "dados": dados}


def nao_se_aplica(detalhe, **dados):
    return {"situacao": NAO_SE_APLICA, "detalhe": detalhe, "dados": dados}


def nao_conferida(detalhe, **dados):
    return {"situacao": NAO_CONFERIDA, "detalhe": detalhe, "dados": dados}


class Arquivo:
    """
    O que as validações enxergam do arquivo. O que custa para ler (os bytes, as assinaturas, os
    metadados da imagem) só é lido se alguma validação pedir.

    - formatos: os formatos das páginas, vindos do avaliador forense
    - metadados: os metadados do PDF (metadados.py)
    - esperado: o "arquivo_esperado" do tipo de documento no catálogo
    """

    def __init__(self, path, formatos=None, metadados=None, esperado=None, agora=None):
        self.path = Path(path)
        self.formatos = list(formatos or [])
        self.metadados = metadados or {}
        self.esperado = esperado or {}
        self.agora = agora or datetime.now(timezone.utc)

    @property
    def eh_pdf(self):
        return self.path.suffix.lower() == ".pdf"

    @cached_property
    def dados(self):
        return self.path.read_bytes()

    @cached_property
    def _leitura_das_assinaturas(self):
        # sem /ByteRange não há assinatura a ler
        if not self.eh_pdf or b"/ByteRange" not in self.dados:
            return [], None
        from . import assinatura

        try:
            return assinatura.ler(self.path), None
        except ModuleNotFoundError:
            raise
        except Exception as e:
            return [], f"{type(e).__name__}: {e}"

    @property
    def assinaturas(self):
        """Assinaturas digitais do PDF (assinatura.py)."""
        return self._leitura_das_assinaturas[0]

    @property
    def erro_das_assinaturas(self):
        """Por que as assinaturas do PDF não puderam ser lidas, ou None."""
        return self._leitura_das_assinaturas[1]

    @cached_property
    def programas(self):
        """Programas gravados nos metadados do arquivo: [(onde está gravado, programa)]."""
        if self.eh_pdf:
            candidatos = [("Producer", self.metadados.get("producer")), ("Creator", self.metadados.get("creator"))]
        else:
            candidatos = []
            try:
                with Image.open(self.path) as imagem:
                    candidatos.append(("EXIF Software", imagem.getexif().get(0x0131)))
                    candidatos.append(("Software", imagem.info.get("Software")))
            except Exception:
                logger.debug(f"Metadados de imagem ilegíveis em {self.path}", exc_info=True)
            ferramenta = re.search(rb"CreatorTool(?:>|=[\"'])\s*([^<\"']{1,80})", self.dados)
            if ferramenta:
                candidatos.append(("XMP CreatorTool", ferramenta.group(1).decode("utf-8", "replace")))
        return [(onde, str(programa).strip()) for onde, programa in candidatos if programa and str(programa).strip()]

    @cached_property
    def textos_da_imagem(self):
        """Blocos de texto gravados em um arquivo de imagem (os do PNG, por exemplo)."""
        if self.eh_pdf:
            return {}
        try:
            with Image.open(self.path) as imagem:
                return {str(chave): valor for chave, valor in imagem.info.items() if isinstance(valor, str)}
        except Exception:
            return {}


def _lista(itens):
    return ", ".join(itens)


def _quem_assinou(assinatura):
    # a impressão digital vai inteira: é ela que o catálogo lista como certificado aceito
    return f"{assinatura['assinante'] or 'assinante sem nome'} (certificado {assinatura['certificado']})"


# ---------------------------------------------------------------------------------------------
# Validações que valem para qualquer documento
# ---------------------------------------------------------------------------------------------

@validacao("assinatura_integra", "Assinatura digital íntegra", "assinatura digital quebrada: o conteúdo foi alterado depois de assinado", CRITICA)
def assinatura_integra(arquivo):
    """
    Em PDF com assinatura digital, o conteúdo coberto por cada assinatura continua o mesmo de
    quando foi assinado. Não confere a cadeia de confiança do certificado.
    """
    if not arquivo.eh_pdf:
        return nao_se_aplica("Arquivo de imagem não carrega assinatura digital.")
    if b"/ByteRange" not in arquivo.dados:
        return nao_se_aplica("O PDF não tem assinatura digital.")

    if arquivo.erro_das_assinaturas:
        return nao_conferida(f"As assinaturas do PDF não puderam ser lidas: {arquivo.erro_das_assinaturas}")
    assinaturas = arquivo.assinaturas
    if not assinaturas:
        return nao_se_aplica(
            "O PDF traz restos de uma assinatura digital que não existe mais como assinatura, o que é comum em arquivo juntado ou regravado.",
        )

    quebradas = [a for a in assinaturas if "erro" not in a and not (a["intacta"] and a["valida"])]
    if quebradas:
        return reprovada(
            f"O conteúdo coberto pela assinatura de {_lista(_quem_assinou(a) for a in quebradas)} não é mais o que foi assinado: "
            "o arquivo foi alterado depois da assinatura.",
            assinaturas=assinaturas,
        )

    conferidas = [a for a in assinaturas if "erro" not in a]
    if not conferidas:
        return nao_conferida(f"Nenhuma assinatura pôde ser conferida: {assinaturas[0]['erro']}", assinaturas=assinaturas)

    detalhe = f"{len(conferidas)} assinatura(s) íntegra(s): {_lista(_quem_assinou(a) for a in conferidas)}."
    if len(conferidas) < len(assinaturas):
        detalhe += f" {len(assinaturas) - len(conferidas)} não pôde(puderam) ser conferida(s)."
    if not any(a["cobre_o_arquivo"] for a in conferidas):
        detalhe += " Há conteúdo acrescentado depois da última assinatura, o que é comum em plataformas de assinatura e não invalida as anteriores."
    return aprovada(detalhe, assinaturas=assinaturas)


def _data(valor):
    """Data de metadado como metadados.data_legivel a escreve; o que não seguir o formato fica sem data."""
    for formato in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            lida = datetime.strptime(valor or "", formato)
        except ValueError:
            continue
        return lida if lida.tzinfo else lida.replace(tzinfo=timezone.utc)
    return None


@validacao("datas_dos_metadados", "Datas dos metadados possíveis", "datas impossíveis nos metadados do arquivo", MODERADA, categoria="TEMPORAL")
def datas_dos_metadados(arquivo):
    """
    As datas de criação e de modificação gravadas no PDF não estão no futuro, e a modificação
    não é anterior à criação. A comparação com as datas escritas no documento é da LLM.
    """
    if not arquivo.eh_pdf:
        return nao_se_aplica("Só os metadados de PDF são conferidos.")

    criacao, modificacao = _data(arquivo.metadados.get("creationDate")), _data(arquivo.metadados.get("modDate"))
    if criacao is None and modificacao is None:
        return nao_se_aplica("O PDF não tem datas legíveis nos metadados.")

    problemas = []
    for nome, data in (("criação", criacao), ("modificação", modificacao)):
        if data is not None and data > arquivo.agora + TOLERANCIA_DE_DATA:
            problemas.append(f"a data de {nome} ({data:%d/%m/%Y}) está no futuro")
    if criacao is not None and modificacao is not None and modificacao < criacao - TOLERANCIA_DE_DATA:
        problemas.append(f"a modificação ({modificacao:%d/%m/%Y}) é anterior à criação ({criacao:%d/%m/%Y})")

    if problemas:
        return reprovada(f"Nos metadados do PDF, {' e '.join(problemas)}.")
    return aprovada("As datas de criação e de modificação do PDF são possíveis.")


def _gerador_de_imagem(textos):
    """Programa gerador de imagem por IA que deixou o seu bloco de texto no arquivo, ou None."""
    if "Steps:" in textos.get("parameters", ""):
        return "Stable Diffusion (bloco 'parameters')"
    if any('"class_type"' in textos.get(chave, "") for chave in ("prompt", "workflow")):
        return "ComfyUI (bloco de fluxo de geração)"
    if any(chave in textos for chave in ("invokeai_metadata", "sd-metadata", "dream")):
        return "InvokeAI (bloco de metadados de geração)"
    if "novelai" in textos.get("Software", "").lower():
        return "NovelAI (bloco 'Software')"
    return None


SEM_MARCA = "A ausência da marca não prova nada: ela some com um print de tela ou com uma regravação do arquivo."


@validacao("gerado_por_ia", "Sem marca de geração por IA", "o arquivo declara ter sido gerado por IA", CRITICA)
def gerado_por_ia(arquivo):
    """
    O arquivo não traz, nos metadados ou nas credenciais de conteúdo (C2PA), a declaração de que
    a imagem foi gerada por modelo de IA, nem o bloco de texto que os geradores gravam.
    """
    if GERADO_POR_IA in arquivo.dados:
        return reprovada("Os metadados do arquivo declaram a imagem como gerada por modelo de IA (origem digital 'trainedAlgorithmicMedia').")
    gerador = _gerador_de_imagem(arquivo.textos_da_imagem)
    if gerador:
        return reprovada(f"O arquivo traz o bloco de texto de um gerador de imagens por IA: {gerador}.")

    detalhe = f"Nenhuma marca de geração por IA nos metadados. {SEM_MARCA}"
    if b"c2pa" in arquivo.dados:
        detalhe = f"O arquivo traz credenciais de conteúdo (C2PA) que não declaram geração por IA. {SEM_MARCA}"
    return aprovada(detalhe)


@validacao("editado_com_ia", "Sem marca de edição com IA", "o arquivo declara ter sido editado com IA", MODERADA)
def editado_com_ia(arquivo):
    """
    O arquivo não traz, nos metadados ou nas credenciais de conteúdo (C2PA), a declaração de que
    a imagem foi alterada com ferramenta de IA (apagar, preencher ou trocar partes).
    """
    if EDITADO_COM_IA in arquivo.dados:
        return reprovada("Os metadados do arquivo declaram a imagem como editada com modelo de IA (origem digital 'compositeWithTrainedAlgorithmicMedia').")
    return aprovada(f"Nenhuma marca de edição com IA nos metadados. {SEM_MARCA}")


@validacao("programa_de_edicao", "Sem programa de edição gráfica nos metadados", "programa de edição gráfica nos metadados do arquivo", INFORMATIVA)
def programa_de_edicao(arquivo):
    """
    O programa gravado nos metadados (Producer e Creator do PDF; EXIF e XMP da imagem) não é um
    editor gráfico, como Photoshop, GIMP ou Canva.
    """
    if not arquivo.programas:
        return nao_se_aplica("O arquivo não informa nenhum programa nos metadados.")

    editores = [f"{programa} ({onde})" for onde, programa in arquivo.programas if any(editor in programa.lower() for editor in EDITORES_GRAFICOS)]
    if editores:
        return reprovada(f"Programa de edição gráfica nos metadados: {_lista(editores)}.")
    return aprovada(f"Nenhum programa de edição gráfica nos metadados ({_lista(programa for _, programa in arquivo.programas)}).")


# ---------------------------------------------------------------------------------------------
# Validações que comparam o arquivo com o esperado para o tipo de documento (catálogo)
# ---------------------------------------------------------------------------------------------

def _pdf_so_de_imagem(arquivo):
    """
    O PDF é só imagem: papel digitalizado, foto ou print guardado em PDF. Nele não há programa do
    emissor nem assinatura digital a conferir. Se o tipo de documento não aceita chegar assim,
    quem reprova é o formato esperado.
    """
    return bool(arquivo.formatos) and all(formato in FORMATOS_DE_IMAGEM for formato in arquivo.formatos)


@validacao("formato_esperado", "Formato de arquivo esperado para o tipo", "formato de arquivo fora do esperado", CRITICA, grupo=ARQUIVO_ESPERADO)
def formato_esperado(arquivo):
    """
    Todas as páginas chegaram em um dos formatos que o tipo de documento espera (por exemplo, um
    documento que nasce digital chegar como PDF gerado por software, e não como foto ou print).
    """
    esperados = arquivo.esperado.get("formatos") or []
    if not esperados:
        return nao_se_aplica("O tipo de documento não define formatos esperados.")
    if not arquivo.formatos:
        return nao_conferida("O formato do arquivo não foi identificado.")

    def rotulos(formatos):
        return _lista(ROTULOS_DOS_FORMATOS.get(formato, formato) for formato in formatos)

    fora = [formato for formato in arquivo.formatos if formato not in esperados]
    if fora:
        return reprovada(f"O arquivo chegou como {rotulos(fora)}; o tipo de documento espera {rotulos(esperados)}.")
    return aprovada(f"O arquivo chegou como {rotulos(arquivo.formatos)}, formato esperado para o tipo.")


@validacao("programa_esperado", "Programa gerador esperado para o tipo", "programa gerador fora do esperado", CRITICA, grupo=ARQUIVO_ESPERADO)
def programa_esperado(arquivo):
    """
    O programa que gerou o PDF (Producer ou Creator) é um dos que o tipo de documento espera.
    Não vale para PDF que é só imagem. O nome do programa é gravado por quem gera o arquivo: a
    validação pega o documento refeito sem cuidado, não o que foi feito para enganar.
    """
    esperados = arquivo.esperado.get("programas") or []
    if not esperados:
        return nao_se_aplica("O tipo de documento não define programas geradores esperados.")
    if not arquivo.eh_pdf:
        return nao_se_aplica("Só PDF informa o programa gerador.")
    if not arquivo.formatos:
        return nao_conferida("O formato do arquivo não foi identificado: não dá para saber se o PDF é só imagem.")
    if _pdf_so_de_imagem(arquivo):
        return nao_se_aplica("O PDF é só imagem (digitalização, foto ou print): o programa gravado nele é o que o digitalizou, não o do emissor.")

    if not arquivo.programas:
        return reprovada(f"O PDF não informa o programa que o gerou; o tipo de documento espera {_lista(esperados)}.")

    descricao = " | ".join(programa for _, programa in arquivo.programas)
    for esperado in esperados:
        if esperado.lower() in descricao.lower():
            return aprovada(f"O programa gerador está na lista do tipo: {descricao}.")
    return reprovada(f"O PDF foi gerado por {descricao}; o tipo de documento espera {_lista(esperados)}.")


@validacao("assinatura_esperada", "Assinatura digital esperada para o tipo", "sem a assinatura digital esperada", CRITICA, grupo=ARQUIVO_ESPERADO)
def assinatura_esperada(arquivo):
    """
    O PDF tem a assinatura digital com que o tipo de documento é emitido e, quando o catálogo
    lista os certificados aceitos, ela é de um deles. Não vale para PDF que é só imagem. A
    integridade é de assinatura_integra.
    """
    if not arquivo.esperado.get("assinatura_digital"):
        return nao_se_aplica("O tipo de documento não espera assinatura digital.")
    if not arquivo.eh_pdf:
        return nao_se_aplica("Arquivo de imagem não carrega assinatura digital.")
    if not arquivo.formatos:
        return nao_conferida("O formato do arquivo não foi identificado: não dá para saber se o PDF é só imagem.")
    if _pdf_so_de_imagem(arquivo):
        return nao_se_aplica("O PDF é só imagem (digitalização, foto ou print): a assinatura digital só existe no arquivo original do emissor.")

    if arquivo.erro_das_assinaturas:
        return nao_conferida(f"As assinaturas do PDF não puderam ser lidas: {arquivo.erro_das_assinaturas}")
    assinaturas = [a for a in arquivo.assinaturas if "erro" not in a]
    if not assinaturas:
        if arquivo.assinaturas:
            return nao_conferida(f"A assinatura do PDF não pôde ser conferida: {arquivo.assinaturas[0]['erro']}")
        return reprovada("O tipo de documento é emitido com assinatura digital e este PDF não tem: não é o arquivo original do emissor.")

    aceitos = {certificado.lower() for certificado in arquivo.esperado.get("certificados") or []}
    if not aceitos:
        return aprovada(f"PDF com assinatura digital de {_lista(_quem_assinou(a) for a in assinaturas)}.", assinaturas=assinaturas)

    reconhecidas = [a for a in assinaturas if a["certificado"] in aceitos]
    if reconhecidas:
        return aprovada(f"PDF assinado com certificado aceito para o tipo: {_lista(_quem_assinou(a) for a in reconhecidas)}.", assinaturas=assinaturas)
    return reprovada(
        f"O PDF foi assinado por {_lista(_quem_assinou(a) for a in assinaturas)}, com certificado que não está entre os aceitos para o tipo.",
        assinaturas=assinaturas,
    )


# ---------------------------------------------------------------------------------------------
# Execução e uso do resultado
# ---------------------------------------------------------------------------------------------

def validar(arquivo, severidades=None):
    """
    Roda as validações sobre o arquivo. `severidades` é {nome: severidade} da configuração; a
    que faltar usa a padrão da validação. Retorna, na ordem de VALIDACOES, um resultado por
    validação: nome, título, situação, detalhe, dados, severidade e grupo.
    """
    if not arquivo.path.is_file():
        return []

    severidades = severidades or {}
    resultados = []
    for nome, funcao in VALIDACOES.items():
        try:
            resultado = funcao(arquivo)
        except ModuleNotFoundError as e:
            resultado = nao_conferida(f"Falta instalar a biblioteca '{e.name}' para esta validação.")
        except Exception as e:
            logger.exception(f"Erro na validação do arquivo {nome}")
            resultado = nao_conferida(f"A validação falhou: {type(e).__name__}: {e}")
        resultados.append({
            "validacao": nome, "titulo": funcao.titulo, **resultado,
            "severidade": severidades.get(nome, funcao.severidade), "grupo": funcao.grupo,
        })
    return resultados


def flags(validacoes):
    """
    Flags das validações reprovadas, no formato das flags do orquestrador. As informativas não
    viram flag. As reprovadas de um mesmo grupo viram uma flag só, com a maior severidade.
    """
    ordem = (CRITICA, MODERADA, BAIXA)
    grupos = {}
    for resultado in validacoes:
        if resultado["situacao"] == REPROVADA and resultado["severidade"] in ordem:
            grupos.setdefault(resultado["grupo"] or resultado["validacao"], []).append(resultado)

    resultado = []
    for grupo, membros in grupos.items():
        problemas = _lista(VALIDACOES[membro["validacao"]].problema for membro in membros)
        resultado.append({
            "category": VALIDACOES[membros[0]["validacao"]].categoria,
            "severity": min((membro["severidade"] for membro in membros), key=ordem.index),
            "source": FONTE,
            "description": f"Arquivo fora do esperado para o tipo de documento: {problemas}" if grupo == ARQUIVO_ESPERADO else problemas[0].upper() + problemas[1:],
            "evidence": " ".join(membro["detalhe"] for membro in membros),
        })
    return resultado


def descrever(validacoes, contadas=True):
    """
    Bloco de texto das validações reprovadas, para a prompt do orquestrador. As aprovadas não
    vão: uma conferência que não achou problema não deve pesar a favor do documento. `contadas`
    diz se as reprovadas com severidade viram flag neste nível de risco.
    """
    linhas = []
    for resultado in validacoes:
        if resultado["situacao"] != REPROVADA:
            continue
        flag = contadas and resultado["severidade"] != INFORMATIVA
        marca = f"flag {resultado['severidade']} já contada" if flag else "informativa"
        linhas.append(f"      • {resultado['titulo']}: REPROVADA ({marca}). {resultado['detalhe']}")

    if not linhas:
        return "nenhuma."
    return "\n" + "\n".join(linhas)
