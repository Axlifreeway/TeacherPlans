"""
Единое форматирование и показ ошибок в UI.

Вынесено отдельно, чтобы view-модули не тянули `traceback` и не дублировали
эвристику «это rate-limit или нет».
"""

import traceback

import streamlit as st


def format_exception(e: BaseException) -> str:
    """Человекочитаемое описание ошибки.

    Некоторые исключения LangChain имеют пустой `str()` — без этой обёртки
    в UI будет просто пустая строка.
    """
    msg = str(e).strip()
    return f"{type(e).__name__}: {msg}" if msg else type(e).__name__


def is_rate_limit(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    return (
        "rate_limit" in msg
        or "rate limit" in msg
        or "tokens per minute" in msg
        or "tpm" in msg
        or getattr(exc, "status_code", None) in (413, 429)
        or "RateLimit" in name
    )


def show_error(prefix: str, exc: BaseException) -> None:
    if is_rate_limit(exc):
        st.error(
            "⏱️ Groq упёрся в лимит токенов в минуту (TPM). "
            "На бесплатном тарифе у `llama-3.3-70b-versatile` лимит — 12k токенов/мин.\n\n"
            "Что можно сделать:\n"
            "- подождать минуту и повторить запрос;\n"
            "- переключиться на `llama-3.1-8b-instant` в `config.local.toml` "
            "(у неё лимит существенно выше);\n"
            "- уменьшить контекст: `chat_k` и `chat_specialty_k` в `[rag]` "
            "в `config.local.toml`."
        )
        with st.expander("Ответ Groq"):
            st.code(format_exception(exc))
        return

    st.error(f"{prefix}: {format_exception(exc)}")
    with st.expander("Подробности (traceback)"):
        st.code(traceback.format_exc())
