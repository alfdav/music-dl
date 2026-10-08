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


def nfd_path(path: str | os.PathLike[str] | None) -> str:
    if path is None:
        return ""
    return unicodedata.normalize("NFD", os.fspath(path))


def filesystem_spellings(path: str | os.PathLike[str] | None) -> tuple[str, ...]:
    """Stored spelling, then NFD, then NFC. Empty strings are dropped.

    Comparison and prefix maps stay on ``nfc_path``. This tuple is only for
    probing which spelling opens.
    """
    if path is None:
        return ()
    raw = os.fspath(path)
    if not raw:
        return ()
    nfc = unicodedata.normalize("NFC", raw)
    nfd = unicodedata.normalize("NFD", nfc)
    found: list[str] = []
    for item in (raw, nfd, nfc):
        if item not in found:
            found.append(item)
    return tuple(found)


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
