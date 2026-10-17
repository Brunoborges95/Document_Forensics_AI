"""
Consultas a serviços fora da aplicação, usadas pelos verificadores marcados com
consulta_externa. Cada consulta envia a um terceiro um dado tirado do documento (um CNPJ, o
endereço de uma cobrança): por isso só rodam quando as consultas externas estão ligadas.
"""
import base64
import ipaddress
import json
from urllib.parse import urlsplit

import httpx

TEMPO_LIMITE = 15

# Endereços de cobrança Pix que a aplicação aceita consultar. O endereço vem de dentro do
# documento: sem essa lista, um documento forjado faria a aplicação acessar o endereço que
# quisesse, inclusive os da rede interna. O da Caixa é o das guias do FGTS Digital
DOMINIOS_PIX = ("pix-qrcode.caixa.gov.br",)

# Espelho público da base de CNPJ da Receita Federal. Para volume ou garantia de serviço, o
# caminho é a base aberta da Receita hospedada pela própria aplicação, ou a API do Serpro
CNPJ_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"


class ConsultaIndisponivel(Exception):
    """O serviço não respondeu, ou respondeu algo que não dá para usar."""


class EnderecoNaoPermitido(Exception):
    """O endereço a consultar não é https ou não está entre os domínios permitidos."""


def _get(url, **kwargs):
    try:
        return httpx.get(url, timeout=TEMPO_LIMITE, follow_redirects=False, **kwargs)
    except httpx.HTTPError as e:
        raise ConsultaIndisponivel(f"{type(e).__name__}: {e}") from e


def _url(endereco):
    return endereco if "://" in endereco else f"https://{endereco}"


def endereco_permitido(endereco, dominios):
    """O endereço é https, sem usuário, porta ou IP, e de um dos domínios (ou de um subdomínio deles)?"""
    try:
        partes = urlsplit(_url(endereco))
        host = (partes.hostname or "").lower()
        porta = partes.port
    except ValueError:
        return False

    if partes.scheme != "https" or not host or partes.username or porta not in (None, 443):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return any(host == dominio or host.endswith(f".{dominio}") for dominio in dominios)


def cobranca_pix(endereco, dominios=DOMINIOS_PIX):
    """
    Cobrança de um Pix dinâmico, buscada no endereço que vem no código (o mesmo que o aplicativo
    de quem paga consulta). Retorna {"http": código, "cobranca": dados ou None}: pelo padrão do
    Banco Central, 404 é endereço que não exibe cobrança e 410, cobrança que deixou de existir.

    A resposta é um JWS assinado pela instituição recebedora. A assinatura não é conferida aqui:
    a garantia é a do https com o domínio permitido.
    """
    if not endereco_permitido(endereco, dominios):
        raise EnderecoNaoPermitido(endereco)

    resposta = _get(_url(endereco), headers={"Accept": "application/jose, application/json"})
    if resposta.status_code in (404, 410):
        return {"http": resposta.status_code, "cobranca": None}
    if resposta.status_code != 200:
        raise ConsultaIndisponivel(f"HTTP {resposta.status_code}")

    partes = resposta.text.strip().split(".")
    if len(partes) != 3:
        raise ConsultaIndisponivel("a resposta não é uma cobrança assinada")
    try:
        cobranca = json.loads(base64.urlsafe_b64decode(partes[1] + "=" * (-len(partes[1]) % 4)))
    except (ValueError, UnicodeDecodeError) as e:
        raise ConsultaIndisponivel("não foi possível ler a cobrança") from e
    return {"http": 200, "cobranca": cobranca}


def cadastro_cnpj(cnpj):
    """Cadastro do CNPJ (14 caracteres, sem pontuação) na base da Receita. None quando não existe."""
    resposta = _get(CNPJ_URL.format(cnpj=cnpj))
    if resposta.status_code == 404:
        return None
    if resposta.status_code != 200:
        raise ConsultaIndisponivel(f"HTTP {resposta.status_code}")
    return resposta.json()
