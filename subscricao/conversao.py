from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import OCR_LANG


@dataclass
class DocumentoConvertido:
    path: Path  # arquivo original (PDF ou imagem), enviado à prompt visual
    markdown: str


@lru_cache(maxsize=1)
def get_converter():
    # Import tardio: carregar o docling e seus modelos leva alguns segundos
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import OcrAutoOptions, PdfPipelineOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.ocr_options = OcrAutoOptions(lang=OCR_LANG)

    return DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.IMAGE],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
        },
    )


def converter(path):
    """
    Converte um documento (imagem ou PDF) em markdown.
    """
    document = get_converter().convert(path).document

    # O layout do docling costuma classificar documentos de identidade, selos e carimbos como
    # figuras, e por padrão o texto lido dentro de figuras fica fora do markdown
    paginas = {page_no: document.export_to_markdown(traverse_pictures=True, page_no=page_no) for page_no in sorted(document.pages)}

    return DocumentoConvertido(path=Path(path), markdown=juntar_paginas(paginas))


def juntar_paginas(paginas):
    """
    Markdown do documento a partir do markdown de cada página ({número: markdown}). Com mais de
    uma página, cada uma começa com o marcador "--- PÁGINA N ---", como no markdown da
    referência: é o que permite às prompts de fraude apontar a página de um valor.
    """
    if len(paginas) <= 1:
        return "".join(paginas.values())

    return "\n\n".join(f"--- PÁGINA {page_no} ---\n\n{markdown.strip()}" for page_no, markdown in paginas.items())
