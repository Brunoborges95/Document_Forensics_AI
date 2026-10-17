from datetime import datetime
import re

def str2bool(text, std=False):
    """
    Converte string em booleano com valor padrão em caso de erro.
    
    Args:
        texto: String a ser convertida
        padrao: Valor padrão se a conversão falhar (default: False)
        
    Returns:
        bool: True, False ou valor padrão
    """
    if isinstance(text, bool):
        return text
    
    if not isinstance(text, str):
        return std
    
    text_clean = text.strip().lower()
    
    values_true = {'true', '1', 'sim', 's', 'yes', 'y', 'verdadeiro', 'on', 't'}
    values_false = {'false', '0', 'não', 'nao', 'n', 'no', 'falso', 'off', 'f'}
    
    if text_clean in values_true:
        return True
    elif text_clean in values_false:
        return False
    else:
        return std

class DataNotFoundError(Exception):
    """Erro lançado quando se tenta parsear uma string que indica ausência de data."""
    pass

class InvalidDateError(Exception):
    def __init__(self, value):
        self.value = value
        super().__init__(f"Data inválida ou inexistente: {value!r}")

def safe_strptime(value: str, fmt: str) -> datetime:
    """
    Wrapper para datetime.strptime que detecta tentativas de parsear 'Not Found'
    e datas inválidas.
    """
    if isinstance(value, str) and value.strip().lower() in ['not found', 'n/a', 'null', 'none']:
        raise DataNotFoundError(
            f"Tentativa de gerar data a partir de valor inválido: {value!r}"
        )

    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        raise InvalidDateError(value)

class ValidationResultNormalizer:
    def __init__(self):
        self.DATE_WITH_HYPHEN_REGEX = re.compile(r'(\d{2})-(\d{2})-(\d{4})')

    def normalize(self, value):
        if isinstance(value, dict):
            return self._normalize_dict(value)
        
        if isinstance(value, list):
            return self._normalize_list(value)

        return self._normalize_string(value)

    def _normalize_string(self, value):
        if not isinstance(value, str):
            return value

        new_value = self._normalize_date(value)
        new_value = self._normalize_not_found(new_value)

        return new_value

    def _normalize_date(self, value: str) -> str:
        return self.DATE_WITH_HYPHEN_REGEX.sub(r'\1/\2/\3', value)

    def _normalize_not_found(self, value: str) -> str:
        not_found = 'Trecho não encontrado'
        normalized_value = not_found if value.upper() == 'NOT FOUND' else value

        return normalized_value

    def _normalize_dict(self, value: dict) -> dict:
        new_value = value.copy()

        for key in new_value:
            new_value[key] = self._normalize_string(new_value[key])

        return new_value
    
    def _normalize_list(self, value: list) -> list:
        new_value = value.copy()

        for index, list_value in enumerate(value):
            new_value[index] = self._normalize_string(list_value)
        
        return new_value


def str2float(value):
    """
    Normaliza string e converte para float
    
    Args:
        value: String a ser convertida
        
    Returns: float ou None
    """
    if not value:
        return None

    return float(value.replace('.', '').replace(',', '.'))

def format_currency(value: float, default_value=None):
    """
    Converte float para string, formatando unidade de milhar e decimais
    
    Args:
        value: Float a ser convertido
        
    Returns: string
    """
    if not value:
        return default_value

    formatted_value = f'{value:,.2f}'.replace(',', 'X')
    formatted_value = formatted_value.replace('.', ',')
    formatted_value = formatted_value.replace('X', '.')

    return formatted_value