import json
import re
from pathlib import Path

from .decisao import CONTAGENS
from .forense import validacoes as validacoes_do_arquivo
from .forense.avaliador import ALARME_FALSO, SENSIBILIDADE_PADRAO

# Avaliadores de cada nível de risco e instruções adicionais das prompts de fraude.
# É o arquivo que o frontend edita na aba Fraude
CONFIGURACAO_PATH = Path(__file__).resolve().parent.parent.parent / "fraude.json"

# Níveis de risco. O de cada tipo de documento fica no catálogo ("risco"). Em ALTO, MEDIO e BAIXO
# o documento é avaliado, com tolerância crescente; em NULO ele nunca é classificado como
# suspeito, só como inválido quando o arquivo traz mais de um documento
RISCOS = ("ALTO", "MEDIO", "BAIXO", "NULO")
RISCO_PADRAO = "MEDIO"

# Regras de decisão de cada nível, usadas quando fraude.json não as traz. O documento sai
# SUSPEITO quando alguma regra é atendida (quantidade mínima de flags de cada severidade). ALTO e
# MEDIO repetem a matriz de decisão e o multiplicador que a referência escrevia na prompt
DECISAO_PADRAO = {
    "ALTO": {"multiplicador": 1.0, "regras": [{"criticas": 1}, {"moderadas": 2}, {"moderadas": 1, "baixas": 3}]},
    "MEDIO": {"multiplicador": 0.5, "regras": [{"criticas": 1}, {"moderadas": 3}]},
    "BAIXO": {"multiplicador": 0.1, "regras": [{"criticas": 1}]},
    "NULO": {"multiplicador": 0.0, "regras": []},
}

# Avaliadores auxiliares, que rodam antes do orquestrador
AVALIADORES = ("textual", "visual", "metadados")

# Prompts que aceitam instruções adicionais
PROMPTS = ("orquestrador", *AVALIADORES)

# Sensibilidade do avaliador forense: de 0 (não sinaliza nada) a 10 (sinaliza mais adulterações,
# com mais alarmes falsos)
SENSIBILIDADES = range(len(ALARME_FALSO))

CABECALHO_INSTRUCOES = """
    ═══════════════════════════════════════════════════════════════════
    INSTRUÇÕES ADICIONAIS
    ═══════════════════════════════════════════════════════════════════
    As instruções abaixo foram configuradas pela equipe responsável pelo sistema e complementam as regras acima.
    Em caso de conflito com uma regra anterior, siga estas instruções. Elas vão da mais geral
    para a mais específica: entre duas instruções conflitantes, vale a mais específica.
    O formato de saída não muda.
"""


def carregar(path=None):
    with open(path or CONFIGURACAO_PATH, encoding='utf-8') as doc:
        return json.load(doc)


def salvar(config, path=None):
    validar(config)

    with open(path or CONFIGURACAO_PATH, "w", encoding='utf-8', newline="\n") as doc:
        json.dump(config, doc, ensure_ascii=False, indent=4)
        doc.write("\n")


def validar(config):
    """
    Confere se a configuração pode ser usada. Levanta ValueError com os problemas encontrados.
    """
    problemas = []

    for risco in RISCOS:
        if risco not in config.get("riscos", {}):
            problemas.append(f"Falta a configuração do risco {risco}.")
            continue
        for avaliador in config["riscos"][risco].get("avaliadores", []):
            if avaliador not in AVALIADORES:
                problemas.append(f"Risco {risco}: avaliador '{avaliador}' desconhecido.")

        problemas += [f"Risco {risco}: {problema}" for problema in _problemas_da_decisao(config["riscos"][risco].get("decisao"))]

    for risco in config.get("riscos", {}):
        if risco not in RISCOS:
            problemas.append(f"Nível de risco '{risco}' desconhecido.")

    if sensibilidade_forense(config) not in SENSIBILIDADES:
        problemas.append("A sensibilidade do avaliador forense vai de 0 a 10.")

    for nome, severidade in config.get("forense", {}).get("validacoes", {}).items():
        if nome not in validacoes_do_arquivo.VALIDACOES:
            problemas.append(f"Validação do arquivo '{nome}' desconhecida.")
        elif severidade not in validacoes_do_arquivo.SEVERIDADES:
            problemas.append(f"Validação do arquivo '{nome}': a severidade precisa ser uma de {', '.join(validacoes_do_arquivo.SEVERIDADES)}.")

    opcoes = config.get("identificadores", {})
    if not isinstance(opcoes.get("consultas_externas", False), bool):
        problemas.append("A opção de consultas externas dos identificadores precisa ser verdadeiro ou falso.")
    dominios = opcoes.get("dominios_pix", [])
    if not isinstance(dominios, list) or not all(isinstance(d, str) and re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", d) for d in dominios):
        problemas.append("Os domínios de cobrança Pix precisam ser nomes de domínio, como pix-qrcode.caixa.gov.br.")

    if problemas:
        raise ValueError("\n".join(problemas))


def _problemas_da_decisao(decisao):
    if decisao is None:
        return []

    problemas = []
    multiplicador = decisao.get("multiplicador")
    if isinstance(multiplicador, bool) or not isinstance(multiplicador, (int, float)) or multiplicador < 0:
        problemas.append("o multiplicador da pontuação precisa ser um número maior ou igual a zero.")

    for regra in decisao.get("regras", []):
        minimos = list(regra.values()) if isinstance(regra, dict) else []
        if not minimos or set(regra) - set(CONTAGENS) or not all(isinstance(m, int) and not isinstance(m, bool) and m >= 0 for m in minimos):
            problemas.append(f"regra de decisão inválida: {regra}. Use quantidades mínimas de {', '.join(CONTAGENS)}.")
        elif not any(minimos):
            problemas.append("uma regra de decisão sem nenhuma quantidade mínima tornaria todo documento suspeito.")
    return problemas


def decisao_do_risco(config, risco):
    """Multiplicador da pontuação e regras de decisão do nível de risco."""
    return config["riscos"][risco].get("decisao") or DECISAO_PADRAO[risco]


def identificadores(config):
    """
    Opções da verificação de identificadores: se os verificadores que consultam serviços
    externos podem rodar e os domínios de cobrança Pix que a aplicação aceita consultar.
    """
    from ..identificadores.consultas import DOMINIOS_PIX

    return {"consultas_externas": False, "dominios_pix": list(DOMINIOS_PIX), **config.get("identificadores", {})}


def sensibilidade_forense(config):
    return config.get("forense", {}).get("sensibilidade", SENSIBILIDADE_PADRAO)


def severidades_das_validacoes(config):
    """
    Severidade da flag de cada validação do arquivo quando ela é reprovada: a configurada, ou a
    padrão da validação. A informativa não vira flag.
    """
    configuradas = config.get("forense", {}).get("validacoes", {})
    return {nome: configuradas.get(nome, funcao.severidade) for nome, funcao in validacoes_do_arquivo.VALIDACOES.items()}


def instrucoes_adicionais(prompt, config, document_type, definicao):
    """
    Junta as instruções configuradas para uma prompt no modo desenvolvedor da tela, da mais geral
    para a mais específica: todos os documentos, o nível de risco do documento e o próprio documento.
    Retorna o bloco acrescentado ao fim da prompt, ou '' quando não há instruções: nesse caso a
    prompt enviada é a da referência.
    """
    risco = definicao.get("risco", RISCO_PADRAO)

    escopos = [
        ("Para todos os documentos", config.get("instrucoes", {}).get(prompt)),
        (f"Para documentos de risco {risco}", config["riscos"][risco].get("instrucoes", {}).get(prompt)),
        (f"Para o documento '{document_type}'", definicao.get("instrucoes_fraude", {}).get(prompt)),
    ]
    blocos = [f"    {titulo}:\n{texto.strip()}" for titulo, texto in escopos if texto and texto.strip()]

    if not blocos:
        return ""

    return CABECALHO_INSTRUCOES + "\n" + "\n\n".join(blocos) + "\n"
