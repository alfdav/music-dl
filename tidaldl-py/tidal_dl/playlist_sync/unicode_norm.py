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


def nfd_path(path: str | os.PathLike[str] | None) -> str:
    if path is None:
        return ""
    return unicodedata.normalize("NFD", os.fspath(path))


def _prefix_rest(path: str, prefix: str) -> str | None:
    """Suffix after *prefix*, or ``""`` when *path* is the prefix. ``None`` if not under it.

    ``/`` and ``\\`` are both separators. Comparison does not depend on the host OS.
    """
    folded_prefix = prefix.replace("\\", "/")
    if not folded_prefix:
        return None
    head = folded_prefix.rstrip("/")
    folded = path.replace("\\", "/")
    if not head:
        if not folded.startswith("/"):
            return None
        return folded[1:]
    if folded == head:
        return ""
    needle = f"{head}/"
    if folded.startswith(needle):
        return folded[len(needle):]
    return None


def apply_prefix_map(path: str, prefixes: Mapping[str, str]) -> str:
    """Rewrite *path* with the longest prefix. Keys and values are NFC first.

    ``/`` and ``\\`` are both separators.
    """
    text = nfc_path(path)
    ranked = sorted(
        ((nfc_path(source), nfc_path(dest)) for source, dest in prefixes.items()),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for source, dest in ranked:
        rest = _prefix_rest(text, source)
        if rest is None:
            continue
        if not rest:
            return dest
        sep = "\\" if "\\" in dest else "/"
        base = dest.rstrip("/\\")
        tail = rest.replace("/", sep)
        return nfc_path(f"{base}{sep}{tail}")
    return text
