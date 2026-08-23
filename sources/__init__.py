"""Dynamic source registry.

Scans *sources/passive/* and *sources/active/* at import time and builds the
``{name: class}`` dictionaries consumed by the engine and CLI.
"""
import importlib
import pkgutil

import sources.active
import sources.passive


def _load_package(package) -> dict:
    """Return {NAME: class} for every source module in *package*."""
    result: dict = {}
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name.startswith('_'):
            continue
        try:
            mod = importlib.import_module(f'{package.__name__}.{module_name}')
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if isinstance(obj, type) and getattr(obj, 'NAME', None) == module_name:
                    result[module_name] = obj
                    break
        except Exception as e:
            import sys
            print(
                f'[!] [sources] Failed to load {package.__name__}.{module_name}: {e}',
                file=sys.stderr,
            )
    return result


PASSIVE_SOURCES: dict = _load_package(sources.passive)
ACTIVE_SOURCES: dict = _load_package(sources.active)
SOURCES: dict = {**PASSIVE_SOURCES, **ACTIVE_SOURCES}

# Order matters for display only: keyless web indexes first, paid/niche last.
CATEGORY_ORDER = ('web', 'code', 'source', 'legal', 'leak', 'darkweb')


def by_category() -> dict:
    """Return {category: {name: class}} following CATEGORY_ORDER."""
    grouped: dict = {c: {} for c in CATEGORY_ORDER}
    for name, cls in SOURCES.items():
        grouped.setdefault(getattr(cls, 'CATEGORY', 'web'), {})[name] = cls
    return {c: g for c, g in grouped.items() if g}


def categories() -> list[str]:
    return list(by_category().keys())


def in_categories(names: set[str]) -> dict:
    """Return {name: class} for every source whose CATEGORY is in *names*."""
    return {
        name: cls
        for name, cls in SOURCES.items()
        if getattr(cls, 'CATEGORY', 'web') in names
    }
