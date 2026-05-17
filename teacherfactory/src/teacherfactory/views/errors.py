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
            "⏱️ Провайдер вернул rate-limit. Это значит, что fallback-цепочка "
            "не смогла переключиться — у тебя настроен только один рабочий "
            "провайдер.\n\n"
            "**Чтобы это больше не повторялось**, настрой fallback (он включён "
            "по умолчанию в выборе провайдера, если их доступно ≥ 2):\n"
            "- **Gemini** — бесплатный ключ на https://aistudio.google.com/apikey, "
            "вписать в `[gemini].api_key` в `config.local.toml`. Free-tier: "
            "1500 RPD и контекст 1M токенов — большие RAG-промпты, на которых "
            "падает Groq, проходят без проблем.\n"
            "- **OpenRouter** — бесплатный ключ на https://openrouter.ai/keys, "
            "вписать в `[openrouter].api_key` в `config.local.toml`. "
            "На free-моделях (`:free`) лимиты иные, чем у Groq, — "
            "пока один отдыхает, другой работает.\n"
            "- **Ollama** — `ollama serve` локально и `ollama pull qwen2.5:14b` "
            "(или другая модель из `[model].llm`). Локально без лимитов.\n\n"
            "**Что сделать прямо сейчас**:\n"
            "- подожди минуту и повтори запрос (TPM-окно у Groq — 60 секунд);\n"
            "- либо смени модель Groq на `llama-3.1-8b-instant` в `config.local.toml` "
            "(у 8B-модели лимит ~30k TPM против 12k у 70B);\n"
            "- либо уменьши контекст: `retrieval_k` / `chat_k` / `chat_specialty_k` "
            "в `[rag]` в `config.local.toml`."
        )
        with st.expander("Ответ провайдера"):
            st.code(format_exception(exc))
        return

    st.error(f"{prefix}: {format_exception(exc)}")
    with st.expander("Подробности (traceback)"):
        st.code(traceback.format_exc())
