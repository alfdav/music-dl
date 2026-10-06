"""NFC for names and paths before compare, prefix map, or lookup."""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Mapping


def nfc(value: str | None) -> str:
    return unicodedata.normalize("NFC", value or "")


def nfc_path(path: str | os.PathLike[str] | None) -> str:
    if path is None:
        return ""
    return unicodedata.normalize("NFC", os.fspath(path))


def apply_prefix_map(path: str, prefixes: Mapping[str, str]) -> str:
    """Rewrite *path* with the longest prefix. Keys and values are NFC first."""
    text = nfc_path(path)
    ranked = sorted(
        ((nfc_path(source), nfc_path(dest)) for source, dest in prefixes.items()),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for source, dest in ranked:
        if not source:
            continue
        if text == source:
            return dest
        prefix = source if source.endswith("/") else f"{source}/"
        if text.startswith(prefix):
            rest = text[len(prefix):]
            base = dest.removesuffix("/")
            return nfc_path(f"{base}/{rest}" if rest else base)
    return text
