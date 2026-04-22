"""Camelot wheel notation helpers for harmonic mixing.

Classic (Open Key): Abm, Dbm, ... / B, E, ...
Alphanumeric: 1A–12A (minor), 1B–12B (major)
"""

from enum import StrEnum


class KeyScale(StrEnum):
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class CamelotNotation(StrEnum):
    CLASSIC = "classic"
    ALPHANUMERIC = "alphanumeric"


_KEY_TO_ALPHANUMERIC: dict[tuple[str, KeyScale], str] = {
    ("Ab", KeyScale.MINOR): "1A",
    ("Eb", KeyScale.MINOR): "2A",
    ("Bb", KeyScale.MINOR): "3A",
    ("F", KeyScale.MINOR): "4A",
    ("C", KeyScale.MINOR): "5A",
    ("G", KeyScale.MINOR): "6A",
    ("D", KeyScale.MINOR): "7A",
    ("A", KeyScale.MINOR): "8A",
    ("E", KeyScale.MINOR): "9A",
    ("B", KeyScale.MINOR): "10A",
    ("FSharp", KeyScale.MINOR): "11A",
    ("Db", KeyScale.MINOR): "12A",
    ("B", KeyScale.MAJOR): "1B",
    ("FSharp", KeyScale.MAJOR): "2B",
    ("Db", KeyScale.MAJOR): "3B",
    ("Ab", KeyScale.MAJOR): "4B",
    ("Eb", KeyScale.MAJOR): "5B",
    ("Bb", KeyScale.MAJOR): "6B",
    ("F", KeyScale.MAJOR): "7B",
    ("C", KeyScale.MAJOR): "8B",
    ("G", KeyScale.MAJOR): "9B",
    ("D", KeyScale.MAJOR): "10B",
    ("A", KeyScale.MAJOR): "11B",
    ("E", KeyScale.MAJOR): "12B",
}

_ALPHANUMERIC_TO_KEY: dict[str, tuple[str, KeyScale]] = {v: k for k, v in _KEY_TO_ALPHANUMERIC.items()}

_KEY_TO_CLASSIC: dict[tuple[str, KeyScale], str] = {
    ("Ab", KeyScale.MINOR): "Abm",
    ("Eb", KeyScale.MINOR): "Ebm",
    ("Bb", KeyScale.MINOR): "Bbm",
    ("F", KeyScale.MINOR): "Fm",
    ("C", KeyScale.MINOR): "Cm",
    ("G", KeyScale.MINOR): "Gm",
    ("D", KeyScale.MINOR): "Dm",
    ("A", KeyScale.MINOR): "Am",
    ("E", KeyScale.MINOR): "Em",
    ("B", KeyScale.MINOR): "Bm",
    ("FSharp", KeyScale.MINOR): "F#m",
    ("Db", KeyScale.MINOR): "Dbm",
    ("B", KeyScale.MAJOR): "B",
    ("FSharp", KeyScale.MAJOR): "Gb",
    ("Db", KeyScale.MAJOR): "Db",
    ("Ab", KeyScale.MAJOR): "Ab",
    ("Eb", KeyScale.MAJOR): "Eb",
    ("Bb", KeyScale.MAJOR): "Bb",
    ("F", KeyScale.MAJOR): "F",
    ("C", KeyScale.MAJOR): "C",
    ("G", KeyScale.MAJOR): "G",
    ("D", KeyScale.MAJOR): "D",
    ("A", KeyScale.MAJOR): "A",
    ("E", KeyScale.MAJOR): "E",
}

_CLASSIC_TO_KEY: dict[str, tuple[str, KeyScale]] = {v: k for k, v in _KEY_TO_CLASSIC.items()}


def _normalize_key_input(key: str) -> str:
    key_clean = key.replace(" ", "").replace("sharp", "Sharp").replace("#", "Sharp")

    if "b" in key_clean and "Sharp" not in key_clean:
        return key_clean

    sharp_to_flat: dict[str, str] = {
        "CSharp": "Db",
        "DSharp": "Eb",
        "GSharp": "Ab",
        "ASharp": "Bb",
    }

    return sharp_to_flat.get(key_clean, key_clean)


def key_to_alphanumeric(key: str, key_scale: KeyScale | str) -> str | None:
    if isinstance(key_scale, str):
        try:
            key_scale = KeyScale(key_scale.upper())
        except ValueError:
            return None

    return _KEY_TO_ALPHANUMERIC.get((_normalize_key_input(key), key_scale))


def key_to_classic(key: str, key_scale: KeyScale | str) -> str | None:
    if isinstance(key_scale, str):
        try:
            key_scale = KeyScale(key_scale.upper())
        except ValueError:
            return None

    return _KEY_TO_CLASSIC.get((_normalize_key_input(key), key_scale))


def format_initial_key(key: str, key_scale: str, initial_key_format: CamelotNotation | str) -> str:
    """Format a musical key into the requested Camelot notation.

    Args:
        key (str): Musical key (e.g. 'C', 'Eb', 'FSharp') or 'UNKNOWN'.
        key_scale (str): Scale ('MAJOR', 'MINOR') or 'UNKNOWN'.
        initial_key_format (CamelotNotation | str): 'classic' or 'alphanumeric'.

    Returns:
        str: Formatted key or empty string if unknown/invalid.
    """
    if not key or not key_scale or key == "UNKNOWN" or key_scale == "UNKNOWN":
        return ""

    if isinstance(initial_key_format, str):
        try:
            initial_key_format = CamelotNotation(initial_key_format.lower())
        except ValueError:
            return ""

    result: str | None = None

    if initial_key_format == CamelotNotation.CLASSIC:
        result = key_to_classic(key, key_scale)
    elif initial_key_format == CamelotNotation.ALPHANUMERIC:
        result = key_to_alphanumeric(key, key_scale)

    return result if result is not None else ""
