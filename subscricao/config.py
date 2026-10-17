import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Modelo Claude usado na classificação e nas extrações
MODEL_ID = os.environ.get("MODEL_ID", "claude-opus-5-5")

# Profundidade de raciocínio: low | medium | high | xhigh | max. Vazio = padrão do modelo
LLM_EFFORT = os.environ.get("LLM_EFFORT") or None

# Se o modelo recusar a requisição, a API a reexecuta em outro modelo ("default" = escolha
# automática). Vazio desliga; necessário para modelos que não aceitam o parâmetro
LLM_FALLBACKS = os.environ.get("LLM_FALLBACKS", "default") or None

# Idiomas do OCR do docling, como tags BCP-47 com o prefixo "iso:" (separados por vírgula)
OCR_LANG = os.environ.get("OCR_LANG", "iso:pt").split(",")
