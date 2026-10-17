import base64
from io import BytesIO
from pathlib import Path

import anthropic
from anthropic import transform_schema
from PIL import Image
from pydantic import TypeAdapter

from .config import LLM_EFFORT, LLM_FALLBACKS, MODEL_ID

# Limite da resposta. O raciocínio do modelo também consome esse limite
MAX_TOKENS = 16000

# A API limita cada imagem a 5 MB. A margem cobre o acréscimo da codificação em base64
MAX_IMAGE_SIZE_MB = 3.75


class LLM:

    def __init__(self):
        self.client = anthropic.Anthropic()

    def compress_image(self, image_data, max_size_mb=5):
        img = Image.open(BytesIO(image_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')

        img_byte_arr = BytesIO()
        quality = 95
        img.save(img_byte_arr, format='JPEG', quality=quality)

        while img_byte_arr.tell() > max_size_mb * 1024 * 1024 and quality > 10:
            img_byte_arr = BytesIO()
            quality -= 5
            img.save(img_byte_arr, format='JPEG', quality=quality)

        img_byte_arr.seek(0)
        return img_byte_arr.getvalue()

    def file_content(self, file_path):
        """
        Monta o bloco de conteúdo com o próprio arquivo do documento (PDF ou imagem).
        """
        file_data = Path(file_path).read_bytes()
        file_type = Path(file_path).suffix.lower().lstrip('.')

        if file_type == 'pdf':
            content_type = 'document'
            media_type = 'application/pdf'
        else:
            content_type = 'image'
            if file_type in ['jpg', 'jpeg']:
                media_type = 'image/jpeg'
            elif file_type == 'png':
                media_type = 'image/png'
            else:
                media_type = None

            # Check image size and compress if necessary
            if media_type is None or len(file_data) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
                file_data = self.compress_image(file_data, max_size_mb=MAX_IMAGE_SIZE_MB)
                media_type = 'image/jpeg'

        encoded_string = base64.standard_b64encode(file_data).decode('utf-8')

        return {
            "type": content_type,
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": encoded_string,
            },
        }

    def call_claude(self, prompt, output_format=None, file_path=None, max_tokens=MAX_TOKENS):
        """
        Chama o Claude com a prompt e, opcionalmente, o arquivo do documento (PDF ou imagem).
        Com `output_format` (um dataclass), a resposta segue essa estrutura e volta como instância
        dela. Sem ele, volta o texto da resposta.
        """
        content = []
        if file_path is not None:
            content.append(self.file_content(file_path))
        content.append({"type": "text", "text": prompt})

        output_config = {}
        if output_format is not None:
            # A estrutura vira o JSON schema que a API garante na resposta
            adapter = TypeAdapter(output_format)
            output_config["format"] = {"type": "json_schema", "schema": transform_schema(adapter.json_schema())}
        if LLM_EFFORT:
            output_config["effort"] = LLM_EFFORT

        request = {
            "model": MODEL_ID,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
        }
        if output_config:
            request["output_config"] = output_config

        if LLM_FALLBACKS:
            messages = self.client.beta.messages
            request["betas"] = ["server-side-fallback-2026-07-01"]
            request["fallbacks"] = LLM_FALLBACKS
        else:
            messages = self.client.messages

        with messages.stream(**request) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise RuntimeError(f"O modelo {response.model} recusou a requisição: {response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise RuntimeError(f"Resposta truncada: o modelo atingiu o limite de {max_tokens} tokens.")

        results = "".join(block.text for block in response.content if block.type == "text")
        if output_format is None:
            return results

        return adapter.validate_json(results)
