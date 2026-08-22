"""
Profile system for SimpleReconDorking.

Profiles are defined in config/profiles.json and let users run predefined
source sets with optional default options.

Usage:
    python simplerecondorking.py -d 'site:{TARGET} ext:sql' -t example.com --profile fast
    python simplerecondorking.py --list-profiles
"""
from __future__ import annotations

import json
import os

_PROFILES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'config', 'profiles.json'
)

_cache: dict | None = None


def load_profiles() -> dict:
    """Load and return the profiles dict from config/profiles.json."""
    global _cache
    if _cache is None:
        try:
            with open(_PROFILES_FILE, 'r') as fh:
                _cache = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def get_profile(name: str) -> dict | None:
    """Return the profile dict for *name*, or None if it doesn't exist."""
    return load_profiles().get(name)


def profile_names() -> list[str]:
    """Return all profile names in definition order."""
    return list(load_profiles().keys())


def resolve_sources(name: str) -> list[str] | str | None:
    """
    Return the source list for the given profile name.

    Returns:
        'all'        - use every registered source
        list[str]    - explicit list of source names
        None         - profile not found
    """
    profile = get_profile(name)
    if profile is None:
        return None
    return profile.get('sources', 'all')


def profile_options(name: str) -> dict:
    """Return the options dict for the given profile, or {}."""
    profile = get_profile(name)
    if not profile:
        return {}
    return profile.get('options', {})
