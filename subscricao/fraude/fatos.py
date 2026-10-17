"""
Fatos sobre o texto do documento que são conferidos por código, e não pela LLM: hoje, o dígito
verificador de CPFs e CNPJs. Vão para as prompts de fraude como um bloco pronto, da mesma forma
que o relatório forense.
"""
import re

from ..identificadores.verificadores import cnpj_valido, cpf_valido

# Só entram os números escritos com a pontuação do CPF e do CNPJ: uma sequência solta de 11 ou
# 14 dígitos pode ser telefone, PIS, protocolo ou código de barras
CPF = re.compile(r"(?<![\w./-])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\w/-])")
# O CNPJ pode ser alfanumérico nas 12 primeiras posições
CNPJ = re.compile(r"(?<![\w./-])[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}(?![\w/-])")


def verificar(markdown):
    """CPFs e CNPJs escritos com pontuação no texto e os que têm dígito verificador inválido."""
    cpfs = list(dict.fromkeys(CPF.findall(markdown)))
    cnpjs = list(dict.fromkeys(CNPJ.findall(markdown)))
    return {
        "cpfs": cpfs,
        "cpfs_invalidos": [cpf for cpf in cpfs if not cpf_valido(cpf)],
        "cnpjs": cnpjs,
        "cnpjs_invalidos": [cnpj for cnpj in cnpjs if not cnpj_valido(cnpj)],
    }


def descrever(fatos):
    """Bloco de texto dos fatos, para as prompts."""
    linhas = []
    for nome, encontrados, invalidos in (("CPFs", fatos["cpfs"], fatos["cpfs_invalidos"]), ("CNPJs", fatos["cnpjs"], fatos["cnpjs_invalidos"])):
        if not encontrados:
            linhas.append(f"{nome} com pontuação no markdown: nenhum.")
        elif invalidos:
            linhas.append(f"{nome} com pontuação no markdown: {len(encontrados)}. Com dígito verificador INVÁLIDO: {', '.join(invalidos)}.")
        else:
            linhas.append(f"{nome} com pontuação no markdown: {len(encontrados)}, todos com dígito verificador válido.")
    return " ".join(linhas)
