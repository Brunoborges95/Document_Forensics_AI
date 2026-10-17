"""
Decisão da análise de fraude. O orquestrador entrega as flags, cada uma com a sua severidade; a
pontuação e o status saem daqui, pelas regras de decisão do nível de risco (fraude.json). Na
referência essa conta era feita pela própria LLM, com a matriz escrita na prompt.
"""

# Pesos das severidades no fraud score, como na referência
PESOS = {"CRÍTICA": 3.0, "MODERADA": 1.0, "BAIXA": 0.2}

# Nome da contagem de cada severidade nas regras de decisão
CONTAGENS = {"criticas": "CRÍTICA", "moderadas": "MODERADA", "baixas": "BAIXA"}

ROTULOS = {"criticas": "críticas", "moderadas": "moderadas", "baixas": "baixas"}

AUTENTICO, SUSPEITO, INVALIDO = "AUTÊNTICO", "SUSPEITO", "INVÁLIDO"

# Arquivo com mais de um documento: a mesma flag e a mesma pontuação que a referência devolvia
SCORE_INVALIDO = 10.0


def flag_de_multiplos_documentos(quantidade):
    return {
        "category": "CONTEXTO",
        "severity": "CRÍTICA",
        "source": "ORCHESTRATOR",
        "description": "Múltiplos documentos distintos no mesmo arquivo",
        "evidence": f"Detectados: {quantidade} documentos",
    }


def descreve_regra(regra):
    return " e ".join(f"{ROTULOS[nome]} ≥ {minimo}" for nome, minimo in regra.items() if minimo)


def decidir(flags, multiplos_documentos, decisao):
    """
    Status e pontuação a partir das flags. `decisao` é a configuração do nível de risco:
    'multiplicador' da pontuação e 'regras', cada uma com a quantidade mínima de flags de cada
    severidade. O documento sai SUSPEITO quando alguma regra é atendida; sem regras, nunca sai.
    """
    contagem = {nome: sum(flag.get("severity") == severidade for flag in flags) for nome, severidade in CONTAGENS.items()}

    if multiplos_documentos:
        return {"status_fraude": INVALIDO, "fraud_score": SCORE_INVALIDO, "contagem": contagem, "regra": "mais de um documento no arquivo"}

    bruto = sum(PESOS[severidade] * contagem[nome] for nome, severidade in CONTAGENS.items())
    atendida = next(
        (regra for regra in decisao["regras"] if all(contagem[nome] >= minimo for nome, minimo in regra.items())),
        None,
    )

    return {
        "status_fraude": SUSPEITO if atendida else AUTENTICO,
        "fraud_score": round(min(10.0, bruto * decisao["multiplicador"]), 2),
        "contagem": contagem,
        "regra": descreve_regra(atendida) if atendida else None,
    }
