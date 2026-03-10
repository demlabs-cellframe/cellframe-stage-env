"""
Localization for stage-env CLI output.

Uses system locale (LANG/LC_ALL): if Russian, user-facing messages are shown in Russian;
otherwise English (default in code). No external .po/.mo files — translations live in
translations_ru.py.
"""
import locale
import os

# Lazy load to avoid circular imports and speed up CLI when not running tests
_ru_map: dict | None = None


def _get_language() -> str:
    """Return 'ru' if system locale suggests Russian, else 'en'."""
    for env in ("LC_ALL", "LANG", "LC_MESSAGES"):
        val = os.environ.get(env, "")
        if val:
            lang_part = val.split(".")[0].split("_")[0].lower()
            if lang_part.startswith("ru"):
                return "ru"
    try:
        loc, _ = locale.getdefaultlocale()
        if loc:
            lang_part = (loc.split("_")[0] or "").lower()
            if lang_part.startswith("ru"):
                return "ru"
    except Exception:
        pass
    return "en"


def _get_ru_translations() -> dict:
    global _ru_map
    if _ru_map is None:
        from .translations_ru import RU
        _ru_map = RU
    return _ru_map


def translate(msg: str) -> str:
    """Return translated message for current locale. Message is in English in code."""
    if _get_language() != "ru":
        return msg
    return _get_ru_translations().get(msg, msg)


def gettext(msg: str) -> str:
    """Alias for translate(); use as _() in code."""
    return translate(msg)


# Convenience: use as from src.utils.i18n import _
_ = gettext
