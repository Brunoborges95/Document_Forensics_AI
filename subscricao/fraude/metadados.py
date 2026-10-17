import re
from pathlib import Path

import pypdfium2 as pdfium

# Chaves da referência mais author e title, que a prompt de metadados avalia e a referência não enviava
CHAVES = {
    'creator': "Creator",
    'producer': "Producer",
    'author': "Author",
    'title': "Title",
    'trapped': "Trapped",
    'creationDate': "CreationDate",
    'modDate': "ModDate",
}

# O que as prompts recebem no lugar dos metadados quando o arquivo é uma imagem
SEM_METADADOS = "NÃO SE APLICA: o arquivo é uma imagem e não tem metadados de PDF."


def eh_pdf(path):
    return Path(path).suffix.lower() == ".pdf"


def data_legivel(valor):
    """
    Data de metadado de PDF (D:AAAAMMDDHHmmSS+HH'mm') como 'AAAA-MM-DD HH:mm:SS +HH:mm'.
    O que não seguir o padrão volta como veio.
    """
    partes = re.match(r"^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?\s*(Z|[+-]\d{2}'?\d{2}'?)?", valor or "")
    if not partes:
        return valor

    ano, mes, dia, hora, minuto, segundo, fuso = partes.groups()
    data = f"{ano}-{mes or '01'}-{dia or '01'} {hora or '00'}:{minuto or '00'}:{segundo or '00'}"
    if fuso == "Z":
        return f"{data} +00:00"
    if fuso:
        digitos = fuso.replace("'", "")
        return f"{data} {digitos[:3]}:{digitos[3:]}"
    return data


def extract_metadata_from_pdf(pdf_path):
    """
    Extrai os metadados do PDF.

    Lógica de Retorno:
    - metadata: dicionário com os metadados creator, producer, author, title, trapped, encryption,
      creationDate e modDate. Em arquivo de imagem, todos vêm None.
    """
    metadata = dict.fromkeys(CHAVES)
    # O pdfium não informa o método de criptografia, como fazia o PyMuPDF na referência
    metadata['encryption'] = None

    if eh_pdf(pdf_path):
        pdf = pdfium.PdfDocument(pdf_path)
        try:
            for chave, nome in CHAVES.items():
                metadata[chave] = pdf.get_metadata_value(nome)
        finally:
            pdf.close()

        metadata = {k: v.replace("\x00", "") if isinstance(v, str) else v for k, v in metadata.items()}
        for chave in ('creationDate', 'modDate'):
            metadata[chave] = data_legivel(metadata[chave])

    return metadata
