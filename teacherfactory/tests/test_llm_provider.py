"""
Тесты фабрики LLM-провайдеров:
  - SecretStr защищает api_key от утечки в repr/str/логи;
  - автовыбор Groq → Ollama → ValueError;
  - explicit override провайдера через provider_type;
  - окружение `GROQ_API_KEY` имеет нижний приоритет относительно config.local.toml;
  - list_available_providers честно показывает доступность.
"""

from unittest.mock import patch

import pytest
from pydantic import SecretStr, ValidationError

from teacherfactory.llm_provider import (
    GroqProvider,
    LLMProviderType,
    OllamaProvider,
    ProviderConfig,
    _groq_api_key,
    _make_config,
    get_llm_provider,
    list_available_providers,
)

REAL_KEY = "gsk_FAKE_REAL_LOOKING_KEY_FOR_TESTS_0123456789"


# ─── SecretStr защита ─────────────────────────────────────────────────────────


def test_provider_config_hides_api_key_in_repr():
    """Самое важное свойство SecretStr: ключ не вытекает в логи/трейсбеки."""
    cfg = ProviderConfig(
        provider_type=LLMProviderType.GROQ,
        model_name="llama-3.1-8b-instant",
        api_key=SecretStr(REAL_KEY),
    )
    assert REAL_KEY not in repr(cfg)
    assert REAL_KEY not in str(cfg)
    # А получить значение можно явно — это и есть весь интерфейс.
    assert cfg.api_key is not None
    assert cfg.api_key.get_secret_value() == REAL_KEY


def test_provider_config_rejects_invalid_temperature():
    """temperature — float, передача строки должна валиться pydantic-валидацией."""
    with pytest.raises(ValidationError):
        ProviderConfig(
            provider_type=LLMProviderType.GROQ,
            model_name="m",
            temperature="hot",  # type: ignore[arg-type]
        )


# ─── _groq_api_key: config vs env priority ───────────────────────────────────


def test_groq_key_from_config_wins_over_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from_env")
    cfg = {"groq": {"api_key": "from_config"}}
    result = _groq_api_key(cfg)
    assert result is not None
    assert result.get_secret_value() == "from_config"


def test_groq_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from_env")
    result = _groq_api_key({})
    assert result is not None
    assert result.get_secret_value() == "from_env"


def test_groq_key_missing_returns_none(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert _groq_api_key({}) is None
    assert _groq_api_key({"groq": {}}) is None
    assert _groq_api_key({"groq": {"api_key": ""}}) is None


# ─── _make_config ─────────────────────────────────────────────────────────────


def test_make_config_for_groq_wraps_secret(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = {
        "model": {"llm": "ollama-model", "temperature": 0.5},
        "groq": {"api_key": REAL_KEY, "model": "llama-3.3-70b"},
    }
    pc = _make_config(LLMProviderType.GROQ, cfg)
    assert pc.provider_type == LLMProviderType.GROQ
    assert pc.model_name == "llama-3.3-70b"
    assert isinstance(pc.api_key, SecretStr)
    assert pc.api_key.get_secret_value() == REAL_KEY


def test_make_config_temperature_override():
    cfg = {"model": {"llm": "m", "temperature": 0.1}}
    pc = _make_config(LLMProviderType.OLLAMA, cfg, temperature=0.9)
    assert pc.temperature == 0.9


def test_make_config_for_ollama_uses_model_section():
    cfg = {"model": {"llm": "qwen2.5:14b", "temperature": 0.1, "num_gpu": -1}}
    pc = _make_config(LLMProviderType.OLLAMA, cfg)
    assert pc.provider_type == LLMProviderType.OLLAMA
    assert pc.model_name == "qwen2.5:14b"
    assert pc.num_gpu == -1


# ─── get_llm_provider: автовыбор ─────────────────────────────────────────────


def test_get_provider_prefers_groq_when_key_set(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = {
        "model": {"llm": "m", "temperature": 0.1},
        "groq": {"api_key": REAL_KEY},
    }
    provider = get_llm_provider(config_dict=cfg)
    assert isinstance(provider, GroqProvider)


def test_get_provider_falls_back_to_ollama(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = {"model": {"llm": "m", "temperature": 0.1}}
    with patch.object(OllamaProvider, "is_available", return_value=True):
        provider = get_llm_provider(config_dict=cfg)
    assert isinstance(provider, OllamaProvider)


def test_get_provider_raises_when_nothing_available(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = {"model": {"llm": "m", "temperature": 0.1}}
    with (
        patch.object(OllamaProvider, "is_available", return_value=False),
        pytest.raises(ValueError, match="LLM-провайдер не доступен"),
    ):
        get_llm_provider(config_dict=cfg)


def test_get_provider_explicit_groq_without_key_raises(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = {"model": {"llm": "m", "temperature": 0.1}}
    with pytest.raises(ValueError, match="Groq API ключ не настроен"):
        get_llm_provider(LLMProviderType.GROQ, config_dict=cfg)


# ─── list_available_providers ────────────────────────────────────────────────


def test_list_available_providers_shape(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = {
        "model": {"llm": "qwen", "temperature": 0.1},
        "groq": {"api_key": REAL_KEY, "model": "llama-3.3-70b"},
    }
    with patch.object(OllamaProvider, "is_available", return_value=True):
        result = list_available_providers(config_dict=cfg)

    by_type = {p["type"]: p for p in result}
    assert by_type["ollama"]["available"] is True
    assert by_type["ollama"]["model"] == "qwen"
    assert by_type["groq"]["available"] is True
    assert by_type["groq"]["model"] == "llama-3.3-70b"


def test_list_available_providers_marks_unavailable(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = {"model": {"llm": "qwen", "temperature": 0.1}}
    with patch.object(OllamaProvider, "is_available", return_value=False):
        result = list_available_providers(config_dict=cfg)

    by_type = {p["type"]: p for p in result}
    assert by_type["ollama"]["available"] is False
    assert by_type["groq"]["available"] is False


# ─── OllamaProvider.is_available: сетевые ошибки ─────────────────────────────


def test_ollama_is_available_handles_connection_error():
    """is_available должен возвращать False при отсутствии сервера, а не падать."""
    import requests

    cfg = ProviderConfig(provider_type=LLMProviderType.OLLAMA, model_name="m")
    with patch("requests.get", side_effect=requests.ConnectionError()):
        assert OllamaProvider(cfg).is_available() is False


def test_ollama_is_available_handles_timeout():
    import requests

    cfg = ProviderConfig(provider_type=LLMProviderType.OLLAMA, model_name="m")
    with patch("requests.get", side_effect=requests.Timeout()):
        assert OllamaProvider(cfg).is_available() is False


def test_ollama_is_available_true_on_200():
    import requests

    cfg = ProviderConfig(provider_type=LLMProviderType.OLLAMA, model_name="m")
    mock_response = requests.Response()
    mock_response.status_code = 200
    with patch("requests.get", return_value=mock_response):
        assert OllamaProvider(cfg).is_available() is True


# ─── GroqProvider: контракт без сети ─────────────────────────────────────────


def test_groq_create_client_raises_without_key():
    cfg = ProviderConfig(provider_type=LLMProviderType.GROQ, model_name="m", api_key=None)
    with pytest.raises(ValueError, match="Groq API ключ не настроен"):
        GroqProvider(cfg)._create_client()


# ─── generate / stream_chat: контракт сообщений ──────────────────────────────


def _client_with(response_content: str):
    """LangChain-клиент, чей invoke возвращает AIMessage-подобный объект."""
    from unittest.mock import MagicMock

    client = MagicMock()
    reply = MagicMock()
    reply.content = response_content
    client.invoke.return_value = reply
    return client


def test_generate_strings_response_content():
    """generate должен вернуть .content как str (а не Any)."""
    from unittest.mock import patch

    cfg = ProviderConfig(provider_type=LLMProviderType.OLLAMA, model_name="m")
    provider = OllamaProvider(cfg)
    with patch.object(provider, "_create_client", return_value=_client_with("Привет")):
        result = provider.generate("Спроси что-нибудь")
    assert result == "Привет"
    assert isinstance(result, str)


def test_generate_adds_system_message_when_provided():
    from unittest.mock import patch

    cfg = ProviderConfig(provider_type=LLMProviderType.OLLAMA, model_name="m")
    provider = OllamaProvider(cfg)
    client = _client_with("Ответ")
    with patch.object(provider, "_create_client", return_value=client):
        provider.generate("user prompt", system_prompt="ты бот")

    sent_messages = client.invoke.call_args[0][0]
    assert len(sent_messages) == 2  # System + Human
    assert "ты бот" in str(sent_messages[0].content)
    assert "user prompt" in str(sent_messages[1].content)


def test_generate_omits_system_message_when_empty():
    from unittest.mock import patch

    cfg = ProviderConfig(provider_type=LLMProviderType.OLLAMA, model_name="m")
    provider = OllamaProvider(cfg)
    client = _client_with("Ответ")
    with patch.object(provider, "_create_client", return_value=client):
        provider.generate("user prompt")

    sent_messages = client.invoke.call_args[0][0]
    assert len(sent_messages) == 1  # только Human


def test_stream_chat_yields_chunk_content():
    """stream_chat должен превращать `chunk.content` в строки."""
    from unittest.mock import MagicMock, patch

    chunks = [MagicMock(content="hello "), MagicMock(content="world")]
    client = MagicMock()
    client.stream.return_value = iter(chunks)

    cfg = ProviderConfig(provider_type=LLMProviderType.OLLAMA, model_name="m")
    provider = OllamaProvider(cfg)
    with patch.object(provider, "_create_client", return_value=client):
        result = list(provider.stream_chat([{"role": "user", "content": "hi"}]))

    assert "".join(result) == "hello world"


def test_stream_chat_maps_role_to_message_type():
    """Сообщения с role=assistant/system/user должны стать AIMessage/SystemMessage/HumanMessage."""
    from unittest.mock import MagicMock, patch

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    client = MagicMock()
    client.stream.return_value = iter([])

    cfg = ProviderConfig(provider_type=LLMProviderType.OLLAMA, model_name="m")
    provider = OllamaProvider(cfg)
    with patch.object(provider, "_create_client", return_value=client):
        list(
            provider.stream_chat(
                [
                    {"role": "system", "content": "S"},
                    {"role": "user", "content": "U"},
                    {"role": "assistant", "content": "A"},
                    {"role": "weird-role", "content": "W"},  # неизвестный → Human
                ],
            )
        )

    sent = client.stream.call_args[0][0]
    types = [type(m) for m in sent]
    assert types == [SystemMessage, HumanMessage, AIMessage, HumanMessage]


# ─── _make_config: ошибки валидации ──────────────────────────────────────────


def test_make_config_raises_validation_error_for_bad_data(monkeypatch):
    """ValidationError должен пробросится наверх (а не быть проглочен)."""
    cfg = {"model": {"llm": 42, "temperature": "very-hot"}}  # некорректные типы
    with pytest.raises((ValidationError, TypeError)):
        _make_config(LLMProviderType.OLLAMA, cfg)
