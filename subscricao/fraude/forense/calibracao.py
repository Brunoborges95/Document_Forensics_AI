"""
Calibração do avaliador forense: como cada sinal se distribui nas páginas autênticas de cada
formato. Com ela o valor de um sinal vira raridade — a fração das páginas autênticas do mesmo
formato que chegam àquele valor — e sinais de escalas diferentes ficam comparáveis. É o que
permite um limiar único de sensibilidade, independente do tipo de documento.

O arquivo calibracao.json é gerado por calibrar.py a partir de uma pasta de documentos autênticos.
"""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

CALIBRACAO_PATH = Path(__file__).with_name("calibracao.json")

# Formato com menos páginas autênticas que isto fica sem calibração (e sem análise)
MINIMO_DE_PAGINAS = 30


def raridade(valores, valor):
    """
    Fração das páginas autênticas em que o sinal chega a `valor`. `valores` são os valores do
    sinal nas páginas autênticas, em ordem crescente. Sinal zerado não é raro.

    A menor raridade possível é 1/(n+1), a de um valor acima de tudo o que se viu: com n páginas
    autênticas não dá para afirmar nada mais raro que isso. Extrapolar a cauda fazia o alarme
    falso medido passar do nominal nas sensibilidades baixas.
    """
    n = len(valores)
    if valor <= 0 or n == 0:
        return 1.0
    acima = n - int(np.searchsorted(valores, valor, side="left"))
    return (acima + 1) / (n + 1)


def raridade_da_pagina(referencia, sinais):
    """
    Raridade da página — a fração das páginas autênticas do formato com algum sinal tão raro
    quanto o mais raro desta — e a raridade de cada sinal. None quando nenhum sinal da página
    tem calibração.
    """
    por_sinal = {
        sinal: raridade(np.asarray(referencia["sinais"][sinal]), valor)
        for sinal, valor in sinais.items() if sinal in referencia["sinais"]
    }
    if not por_sinal:
        return None, {}

    menor = min(por_sinal.values())
    combinado = np.asarray(referencia["combinado"])
    abaixo = int(np.searchsorted(combinado, menor, side="right"))
    return min(1.0, (abaixo + 1) / (len(combinado) + 1)), por_sinal


def montar(paginas):
    """
    Calibração a partir das medidas de páginas autênticas: lista de {"formato", "sinais"}.
    """
    por_formato = defaultdict(list)
    for pagina in paginas:
        if pagina["sinais"]:
            por_formato[pagina["formato"]].append(pagina["sinais"])

    formatos = {}
    for formato, grupo in sorted(por_formato.items()):
        if len(grupo) < MINIMO_DE_PAGINAS:
            continue
        nomes = sorted({sinal for sinais in grupo for sinal in sinais})
        valores = {sinal: sorted(round(float(sinais[sinal]), 3) for sinais in grupo if sinal in sinais) for sinal in nomes}
        ordenados = {sinal: np.asarray(lista) for sinal, lista in valores.items()}
        combinado = sorted(min(raridade(ordenados[sinal], valor) for sinal, valor in sinais.items()) for sinais in grupo)
        formatos[formato] = {"paginas": len(grupo), "sinais": valores, "combinado": [round(p, 5) for p in combinado]}
    return {"formatos": formatos}


def carregar(path=CALIBRACAO_PATH):
    path = Path(path)
    if not path.exists():
        return {"formatos": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def salvar(calibracao, path=CALIBRACAO_PATH):
    Path(path).write_text(json.dumps(calibracao, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
