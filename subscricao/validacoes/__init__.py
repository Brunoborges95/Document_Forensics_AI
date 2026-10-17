import importlib
import pkgutil
import sys
from pathlib import Path

import nltk


def _garante_nltk_data():
    """Distances.py usa stopwords e tokenizer do NLTK (na lambda vinham de uma layer em /opt/nltk_data)."""
    for recurso, pacote in (("corpora/stopwords", "stopwords"), ("tokenizers/punkt_tab", "punkt_tab")):
        try:
            nltk.data.find(recurso)
        except LookupError:
            nltk.download(pacote, quiet=True)


_garante_nltk_data()

from .ValidateDocument import FICHA_CADASTRO, PREPARA_FICHA_CADASTRO, VALIDACOES, validate  # noqa: E402,F401

# Arquivos .py desta pasta na última carga, com a data de modificação de cada um
_carregado = None


def _arquivos():
    return {str(path): path.stat().st_mtime_ns for pasta in __path__ for path in Path(pasta).glob("*.py")}


def carregar_validacoes(apenas_se_alterado=False):
    """
    Carrega todos os arquivos *_validate.py desta pasta, o que registra suas validações: criar o
    arquivo basta. Chamada de novo, recarrega os arquivos, e o registro passa a refletir
    exatamente o que está neles. Retorna True se carregou.
    """
    global _carregado

    arquivos = _arquivos()
    if apenas_se_alterado and arquivos == _carregado:
        return False

    _carregado = None
    VALIDACOES.clear()
    PREPARA_FICHA_CADASTRO.clear()

    # As regras prontas são usadas pelos arquivos de validação: recarregadas antes deles
    regras = sys.modules.get(f"{__name__}.regras")
    if regras is not None:
        importlib.reload(regras)

    for module in pkgutil.iter_modules(__path__):
        if module.name.endswith("_validate"):
            name = f"{__name__}.{module.name}"
            if name in sys.modules:
                importlib.reload(sys.modules[name])
            else:
                importlib.import_module(name)

    _carregado = arquivos
    return True


carregar_validacoes()
