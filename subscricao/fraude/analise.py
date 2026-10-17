import ast
import dataclasses
import json
import logging
import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field
from pydantic.dataclasses import dataclass

from . import fatos as fatos_
from . import prompts_poc as prompts
from .configuracao import RISCO_PADRAO, decisao_do_risco, instrucoes_adicionais, sensibilidade_forense, severidades_das_validacoes
from .decisao import decidir, flag_de_multiplos_documentos
from .forense import avaliador as forense
from .forense import validacoes as validacoes_
from .metadados import SEM_METADADOS, eh_pdf, extract_metadata_from_pdf

logger = logging.getLogger(__name__)

# Mesmo limite de resposta da referência
MAX_TOKENS = 40000

# Como o nível de risco aparece no resultado ("impact_level"), com a grafia da referência
IMPACTO = {"ALTO": "ALTO", "MEDIO": "MÉDIO", "BAIXO": "BAIXO", "NULO": "NULO"}

# O que o orquestrador recebe no lugar do relatório de um avaliador desligado para o nível de risco
NAO_EXECUTADO = "NÃO EXECUTADO (avaliador desligado para este nível de risco)"

# Origem do texto do markdown, informada às prompts: o texto da camada de texto do PDF é o que
# está gravado no arquivo; o lido por OCR pode ter erros de leitura
ORIGEM_CAMADA_DE_TEXTO = "camada de texto do PDF (texto gravado no arquivo, sem OCR)"
ORIGEM_OCR = "lido por OCR (pode conter erros de leitura)"
ORIGEM_MISTA = "parte da camada de texto do PDF e parte lida por OCR, conforme a página; na dúvida, trate como lido por OCR"


# Resposta do orquestrador. Os campos vêm na ordem em que devem ser preenchidos: as flags, com a
# evidência, antes do resumo. O status e a pontuação não estão aqui: saem de decisao.py

@dataclass
class Flag:
    category: Literal["TEXTO", "LAYOUT", "TEMPORAL", "CONTEXTO"]
    severity: Literal["CRÍTICA", "MODERADA", "BAIXA"]
    source: Literal["ORCHESTRATOR", "TEXTUAL_EVALUATOR", "VISUAL_EVALUATOR", "METADATA_EVALUATOR", "MULTIPLE"]
    description: Annotated[str, Field(description="Descrição técnica objetiva")]
    evidence: Annotated[str, Field(description=(
        "Trecho EXATO do valor + LOCALIZAÇÃO precisa (página, seção e campo) onde ele aparece. "
        "Ex: 'CPF 123.456.789-00 no rodapé da página 2'. Se não conseguir apontar ONDE o valor está "
        "no documento/markdown, NÃO crie esta flag."
    ))]


@dataclass
class Alinhamento:
    textual_status_received: Annotated[str, Field(description="CONSISTENTE | INCONSISTENTE | INVÁLIDO | NÃO EXECUTADO")]
    visual_conclusao_received: Annotated[str, Field(description="LEGÍTIMO | SUSPEITO | PROVÁVEL ADULTERAÇÃO | NÃO EXECUTADO")]
    metadata_conclusao_received: Annotated[str, Field(description="LEGÍTIMO | SUSPEITO | PROVÁVEL ADULTERAÇÃO | NÃO EXECUTADO")]
    all_evaluator_findings_preserved: bool


@dataclass
class RespostaDoOrquestrador:
    document_type: Annotated[str, Field(description="Tipo identificado")]
    multiplos_documentos: Annotated[bool, Field(description="Há mais de um documento distinto no arquivo?")]
    quantidade_documentos: Annotated[int, Field(description="Quantidade de documentos distintos no arquivo")]
    evaluator_alignment: Alinhamento
    flags: list[Flag]
    reasoning_summary: Annotated[str, Field(description="Texto simples, direto e não-técnico")]


def clean_json(raw_string):
    raw_string = raw_string.strip()

    # Tenta extrair o conteúdo entre ```json e ```
    match = re.search(r'```json(.*?)```', raw_string, re.DOTALL)
    if match:
        json_text = match.group(1).strip()
    else:
        json_text = raw_string  # fallback: tenta parsear tudo

    try:
        decoder = json.JSONDecoder()
        obj, idx = decoder.raw_decode(json_text)
        return obj
    except json.JSONDecodeError:
        # fallback para ast.literal_eval, com tratamento extra
        try:
            return ast.literal_eval(json_text)
        except (SyntaxError, ValueError):
            return None


def format_orchestrator_evaluator_output(output):
    formatted_output = output.copy()
    valid = output['status_fraude'] == 'AUTÊNTICO'
    formatted_output['valid'] = valid
    formatted_output['fraud_errors'] = 'OK' if valid else 'INCORRETO'

    return formatted_output


def origem_do_markdown(path, analise_forense):
    """De onde veio o texto do markdown, pelos formatos das páginas que o avaliador forense leu."""
    formatos = set(analise_forense.get("formatos", []))
    if not eh_pdf(path) or "pdf_digital" not in formatos:
        return ORIGEM_OCR
    return ORIGEM_CAMADA_DE_TEXTO if formatos == {"pdf_digital"} else ORIGEM_MISTA


def analisar_fraude(llm, documento, document_type, catalogo, config):
    """
    Análise de fraude de um documento. O nível de risco do tipo de documento (catálogo) define a
    prompt do orquestrador e, pela configuração, quais avaliadores auxiliares rodam antes dele e
    com que regras as flags viram status e pontuação. Todas as chamadas recebem o próprio arquivo.
    """
    definicao = catalogo[document_type]
    nivel_risco = definicao.get("risco", RISCO_PADRAO)
    avaliadores = config["riscos"][nivel_risco].get("avaliadores", [])
    logger.info(f"Fraude: '{document_type}' com risco {nivel_risco}, avaliadores {avaliadores}")

    def evaluate(prompt_name, prompt, output_format=None):
        prompt += instrucoes_adicionais(prompt_name, config, document_type, definicao)
        return llm.call_claude(prompt, output_format, file_path=documento.path, max_tokens=MAX_TOKENS)

    metadata = extract_metadata_from_pdf(documento.path)
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Análise algorítmica do arquivo. No lugar do visual_analysis.py da referência, que tinha
    # limiares por tipo de documento, o avaliador de forense/ depende só do formato do arquivo
    try:
        analise_forense = forense.analisar(documento.path, sensibilidade_forense(config))
        output_forensic_report = analise_forense["relatorio"]
    except Exception as e:
        logger.exception(f"Falha na análise forense de {documento.path}")
        analise_forense = {"nivel": forense.NAO_ANALISAVEL, "erro": f"{type(e).__name__}: {e}"}
        output_forensic_report = ""

    # Validações do arquivo: conferências de sim ou não, sem calibração. As do tipo de documento
    # comparam o arquivo com o "arquivo_esperado" do catálogo. As reprovadas viram flags aqui, por
    # código; sem regras de decisão (risco nulo) nenhuma flag muda o status, e elas só informam
    decisao_do_nivel = decisao_do_risco(config, nivel_risco)
    arquivo = validacoes_.Arquivo(documento.path, analise_forense.get("formatos"), metadata, definicao.get("arquivo_esperado"))
    validacoes = validacoes_.validar(arquivo, severidades_das_validacoes(config))
    analise_forense["validacoes"] = validacoes
    flags_das_validacoes = validacoes_.flags(validacoes) if decisao_do_nivel["regras"] else []
    texto_das_validacoes = validacoes_.descrever(validacoes, contadas=bool(decisao_do_nivel["regras"]))

    # O documento é dado de quem o enviou: não pode fechar a marcação em que o markdown vai
    markdown = documento.markdown.replace("</markdown>", "<\\/markdown>")
    origem_markdown = origem_do_markdown(documento.path, analise_forense)
    fatos = fatos_.verificar(documento.markdown)
    texto_dos_fatos = fatos_.descrever(fatos)

    output_Visual_Evaluator = ""
    output_Textual_Evaluator = ""
    output_Metadata_Evaluator = ""
    # sem avaliador de metadados, o orquestrador recebe os metadados brutos, como na referência
    metadados_final = metadata if eh_pdf(documento.path) else SEM_METADADOS

    if "textual" in avaliadores:
        prompt_Textual_Evaluator = prompts.TEXTUAL.format(
            current_date=current_date, markdown=markdown, origem_markdown=origem_markdown, fatos=texto_dos_fatos
        )
        output_Textual_Evaluator = evaluate("textual", prompt_Textual_Evaluator)

    if "visual" in avaliadores:
        prompt_Visual_Evaluator = prompts.VISUAL.format(
            forensic_report=output_forensic_report
        )
        output_Visual_Evaluator = evaluate("visual", prompt_Visual_Evaluator)

    # uma imagem não tem metadados de PDF a avaliar
    if "metadados" in avaliadores and eh_pdf(documento.path):
        prompt_Metadata_Evaluator = prompts.METADADOS.format(
            current_date=current_date, metadata=metadata
        )
        output_Metadata_Evaluator = evaluate("metadados", prompt_Metadata_Evaluator)
        metadados_final = output_Metadata_Evaluator

    documentos_risco = ", ".join(
        nome for nome, outra in catalogo.items() if outra.get("risco", RISCO_PADRAO) == nivel_risco
    )
    prompt_Orchestrated_Evaluator = prompts.ORQUESTRADOR[nivel_risco].format(
        current_date=current_date,
        Textual_Evaluator=output_Textual_Evaluator or NAO_EXECUTADO,
        markdown=markdown,
        origem_markdown=origem_markdown,
        fatos=texto_dos_fatos,
        validacoes=texto_das_validacoes,
        Visual_Evaluator=output_Visual_Evaluator or NAO_EXECUTADO,
        Metadata_Evaluator=metadados_final,
        documentos_risco=documentos_risco,
    )
    resposta = dataclasses.asdict(evaluate("orquestrador", prompt_Orchestrated_Evaluator, RespostaDoOrquestrador))

    # A pontuação e o status saem das flags, pelas regras de decisão do nível de risco: as do
    # orquestrador e as das validações do arquivo
    if resposta["multiplos_documentos"]:
        flags = [flag_de_multiplos_documentos(resposta["quantidade_documentos"])]
    else:
        flags = resposta["flags"] + flags_das_validacoes
    decisao = decidir(flags, resposta["multiplos_documentos"], decisao_do_nivel)

    orquestrador = format_orchestrator_evaluator_output({
        "document_type": resposta["document_type"],
        "impact_level": IMPACTO[nivel_risco],
        "status_fraude": decisao["status_fraude"],
        "fraud_score": decisao["fraud_score"],
        "decisao": {"contagem": decisao["contagem"], "regra": decisao["regra"]},
        "evaluator_alignment": resposta["evaluator_alignment"],
        "flags": flags,
        "reasoning_summary": resposta["reasoning_summary"],
    })

    return {
        "nivel_risco": nivel_risco,
        "metadata": metadata,
        "forense": analise_forense,
        "origem_markdown": origem_markdown,
        "fatos": fatos,
        "output_Textual_Evaluator": clean_json(output_Textual_Evaluator) or output_Textual_Evaluator,
        "output_Visual_Evaluator": clean_json(output_Visual_Evaluator) or output_Visual_Evaluator,
        "output_Metadata_Evaluator": clean_json(output_Metadata_Evaluator) or output_Metadata_Evaluator,
        "output_Evaluator": orquestrador,
    }
