import json
from pathlib import Path

_CONFIG_FILE = Path(__file__).parent.parent / 'config' / 'api_keys.json'

_cache: dict | None = None


def _load() -> dict:
    if not _CONFIG_FILE.exists():
        return {}
    try:
        with open(_CONFIG_FILE, 'r') as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def get_key(name: str) -> str | None:
    """
    Retorna a API key para *name* lida de config/api_keys.json.
    Retorna None se a chave não existir ou estiver vazia.
    """
    global _cache
    if _cache is None:
        _cache = _load()

    val = _cache.get(name, '')
    return val.strip() if isinstance(val, str) and val.strip() else None


def has_key(name: str) -> bool:
    """Retorna True se a API key para *name* está configurada."""
    return get_key(name) is not None
