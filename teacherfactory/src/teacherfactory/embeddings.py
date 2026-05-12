"""
Фабрика эмбеддингов для FAISS-индекса.

Поддерживает:
- Ollama (`provider="ollama"`) — через локальный сервер Ollama.
- HuggingFace (`provider="huggingface"`) — локально через sentence-transformers,
  без необходимости поднимать Ollama. Удобно при работе через Groq.

ВАЖНО: смена провайдера или модели делает существующий FAISS-индекс несовместимым —
его нужно перестроить через indexer.build_index().
"""

from typing import Any

from teacherfactory.config import CONFIG

# Кэш по ключу (provider, model_name): HF-модель занимает ~470 МБ и грузится
# в память несколько секунд. Без кэша Streamlit перезагружал бы её на каждый
# rerun, что давало «серый экран» и таймауты heartbeat-а.
_cache: dict[tuple[str, str], Any] = {}


def _resolve() -> tuple[str, str]:
    emb_cfg = CONFIG.get("embeddings", {})
    provider = emb_cfg.get("provider", "ollama").lower()
    if provider == "huggingface":
        model = emb_cfg.get(
            "hf_model",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
    elif provider == "ollama":
        model = CONFIG["model"]["embeddings"]
    else:
        raise ValueError(
            f"Неизвестный embeddings.provider='{provider}'. "
            "Допустимые значения: 'ollama', 'huggingface'."
        )
    return provider, model


def get_embeddings() -> Any:
    """Вернуть LangChain-совместимый объект эмбеддингов по настройкам [embeddings]."""
    provider, model = _resolve()
    key = (provider, model)
    if key in _cache:
        return _cache[key]

    instance: Any
    if provider == "huggingface":
        from langchain_community.embeddings import HuggingFaceEmbeddings

        instance = HuggingFaceEmbeddings(
            model_name=model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    else:  # ollama
        from langchain_ollama import OllamaEmbeddings

        instance = OllamaEmbeddings(model=model)

    _cache[key] = instance
    return instance


def describe_embeddings() -> str:
    """Строка для отображения в UI: 'huggingface: paraphrase-...' и т.п."""
    provider, model = _resolve()
    return f"{provider}: {model}"
