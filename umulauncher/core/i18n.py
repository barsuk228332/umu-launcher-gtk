"""Translation helpers.

The UI is written with English message ids; Russian lives in ``po/ru.po`` and is
compiled to ``umulauncher/locale/ru/LC_MESSAGES/umulauncher.mo`` by ``make i18n``.
"""

from __future__ import annotations

import gettext
import os
from pathlib import Path

DOMAIN = "umulauncher"
LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"

_translation: gettext.NullTranslations = gettext.NullTranslations()


def available_languages() -> list[str]:
    """Languages that have a compiled catalogue."""
    languages: list[str] = []
    if not LOCALE_DIR.is_dir():
        return languages
    for child in sorted(LOCALE_DIR.iterdir()):
        if (child / "LC_MESSAGES" / f"{DOMAIN}.mo").is_file():
            languages.append(child.name)
    return languages


def _language_chain(language: str | None) -> list[str]:
    if language and language != "system":
        return [language]

    candidates: list[str] = []
    for key in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        raw = os.environ.get(key)
        if not raw:
            continue
        for part in raw.split(":"):
            part = part.split(".")[0].split("@")[0]
            if part and part not in ("C", "POSIX"):
                candidates.append(part)
    return candidates


def setup(language: str | None = None) -> None:
    global _translation
    try:
        _translation = gettext.translation(
            DOMAIN,
            localedir=str(LOCALE_DIR),
            languages=_language_chain(language) or None,
            fallback=True,
        )
    except (OSError, ValueError):
        _translation = gettext.NullTranslations()


def _(message: str) -> str:
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)
