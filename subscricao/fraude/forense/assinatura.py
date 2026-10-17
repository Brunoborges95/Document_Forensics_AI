"""
Assinaturas digitais de um PDF, lidas e conferidas sem acessar a rede (pyHanko).

O que é conferido: se o conteúdo coberto por cada assinatura continua o mesmo (o resumo do
conteúdo bate com o que foi assinado e a assinatura bate com o certificado) e qual certificado
assinou. O que NÃO é conferido: a cadeia de confiança do certificado (ICP-Brasil ou outra), a
validade e a revogação. Uma assinatura íntegra diz que o arquivo não mudou depois de assinado,
não diz quem é o dono do certificado: qualquer pessoa cria um certificado com o nome que quiser.
Por isso a comparação com o emissor esperado é pela impressão digital do certificado.
"""
import hashlib
import logging


def _nome(nome):
    """Nome comum ou organização do certificado, sem o CPF ou CNPJ que o ICP-Brasil escreve depois do nome."""
    dados = nome.native
    valor = dados.get("common_name") or dados.get("organization_name") or ""
    if isinstance(valor, list):
        valor = valor[0]
    return str(valor).split(":")[0].strip()


def ler(path):
    """
    Assinaturas do PDF, na ordem em que estão no arquivo. De cada uma: 'assinante' e 'emissor'
    (nomes do certificado), 'certificado' (SHA-256 do certificado), 'data' informada por quem
    assinou, 'intacta' (o conteúdo coberto não mudou), 'valida' (a assinatura bate com o
    certificado), 'cobre_o_arquivo' (nada foi acrescentado depois dela) e 'alteracao' (o tipo do
    que foi acrescentado). A que não pôde ser conferida vem só com 'erro'.

    Levanta ModuleNotFoundError se o pyHanko não estiver instalado.
    """
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko.sign.validation.status import SignatureCoverageLevel
    from pyhanko_certvalidator import ValidationContext

    # sem as raízes de confiança, o pyHanko registra como erro cada cadeia que não consegue montar
    for nome in ("pyhanko", "pyhanko_certvalidator"):
        logging.getLogger(nome).setLevel(logging.CRITICAL)

    contexto = ValidationContext(allow_fetching=False)
    assinaturas = []

    with open(path, "rb") as arquivo:
        leitor = PdfFileReader(arquivo, strict=False)
        if leitor.encrypted:
            # PDFs protegidos só contra edição (a CTPS digital é um) abrem com a senha vazia
            leitor.decrypt(b"")

        for embutida in leitor.embedded_signatures:
            try:
                status = validate_pdf_signature(embutida, contexto)
                certificado = status.signing_cert
                assinaturas.append({
                    "assinante": _nome(certificado.subject),
                    "emissor": _nome(certificado.issuer),
                    "certificado": hashlib.sha256(certificado.dump()).hexdigest(),
                    "data": status.signer_reported_dt.isoformat() if status.signer_reported_dt else None,
                    "intacta": bool(status.intact),
                    "valida": bool(status.valid),
                    "cobre_o_arquivo": status.coverage == SignatureCoverageLevel.ENTIRE_FILE,
                    "alteracao": status.modification_level.name if status.modification_level is not None else None,
                })
            except Exception as e:
                assinaturas.append({"erro": f"{type(e).__name__}: {e}"[:200]})

    return assinaturas
