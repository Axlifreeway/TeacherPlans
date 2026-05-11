"""
Единый интерфейс для LLM-провайдеров.

Поддерживает:
- Ollama (локально)
- Groq (облако, бесплатный тариф)

Использование:
    from llm_provider import get_llm_provider, LLMProviderType

    provider = get_llm_provider()                # автовыбор по конфигурации
    text = provider.generate("вопрос", system_prompt="...")

    for chunk in provider.stream_chat(messages):
        print(chunk, end="")
"""

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Generator
from enum import Enum
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from config import CONFIG

log = logging.getLogger(__name__)


class LLMProviderType(str, Enum):
    OLLAMA = "ollama"
    GROQ = "groq"


class ProviderConfig(BaseModel):
    provider_type: LLMProviderType
    model_name: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.7
    num_gpu: int = 0
    keep_alive: str = "10m"

    model_config = {"use_enum_values": True, "protected_namespaces": ()}


class LLMProvider(ABC):
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client: Any = None

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def _create_client(self) -> Any: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    def get_client(self) -> Any:
        """Ленивая инициализация клиента LangChain."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        messages: list[Any] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))
        response = self.get_client().invoke(messages)
        return response.content

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str = "",
    ) -> Generator[str, None, None]:
        chat_messages: list[Any] = []
        if system_prompt:
            chat_messages.append(SystemMessage(content=system_prompt))

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "assistant":
                chat_messages.append(AIMessage(content=content))
            elif role == "system":
                chat_messages.append(SystemMessage(content=content))
            else:
                chat_messages.append(HumanMessage(content=content))

        for chunk in self.get_client().stream(chat_messages):
            yield getattr(chunk, "content", str(chunk))


class OllamaProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "Ollama"

    def _create_client(self) -> Any:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=self.config.model_name,
            temperature=self.config.temperature,
            num_gpu=self.config.num_gpu,
            keep_alive=self.config.keep_alive,
        )

    def is_available(self) -> bool:
        try:
            import requests

            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            return response.status_code == 200
        except Exception:
            return False


class GroqProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "Groq"

    def _create_client(self) -> Any:
        from langchain_groq import ChatGroq

        if not self.config.api_key:
            raise ValueError("Groq API ключ не настроен")

        return ChatGroq(
            api_key=self.config.api_key,
            model_name=self.config.model_name,
            temperature=self.config.temperature,
            streaming=True,
        )

    def is_available(self) -> bool:
        return bool(self.config.api_key)


# ─── Фабрика ──────────────────────────────────────────────────────────────────

def _groq_api_key(config_dict: dict) -> str | None:
    """Берёт ключ Groq из конфига или переменной окружения."""
    return config_dict.get("groq", {}).get("api_key") or os.getenv("GROQ_API_KEY")


def _make_config(
    provider_type: LLMProviderType,
    config_dict: dict,
    temperature: float | None = None,
) -> ProviderConfig:
    model_cfg = config_dict["model"]
    temp = temperature if temperature is not None else model_cfg.get("temperature", 0.1)

    try:
        if provider_type == LLMProviderType.GROQ:
            groq_cfg = config_dict.get("groq", {})
            return ProviderConfig(
                provider_type=LLMProviderType.GROQ,
                model_name=groq_cfg.get("model", "llama-3.1-8b-instant"),
                api_key=_groq_api_key(config_dict),
                temperature=temp,
            )
        return ProviderConfig(
            provider_type=LLMProviderType.OLLAMA,
            model_name=model_cfg["llm"],
            temperature=temp,
            num_gpu=model_cfg.get("num_gpu", 0),
            keep_alive=model_cfg.get("keep_alive", "10m"),
        )
    except ValidationError as e:
        log.error("Ошибка валидации конфигурации провайдера: %s", e)
        raise


def get_llm_provider(
    provider_type: LLMProviderType | None = None,
    temperature: float | None = None,
    config_dict: dict | None = None,
) -> LLMProvider:
    """
    Получить LLM-провайдер. Если provider_type=None, выбирается автоматически:
    приоритет — Groq (если задан api_key), иначе Ollama.
    """
    cfg = config_dict if config_dict is not None else CONFIG

    if provider_type is None:
        if _groq_api_key(cfg):
            provider_type = LLMProviderType.GROQ
        else:
            ollama = OllamaProvider(_make_config(LLMProviderType.OLLAMA, cfg))
            if ollama.is_available():
                provider_type = LLMProviderType.OLLAMA
            else:
                raise ValueError(
                    "Ни один LLM-провайдер не доступен:\n"
                    "  - для Groq добавьте api_key в config.local.toml или "
                    "переменную GROQ_API_KEY;\n"
                    "  - для Ollama запустите `ollama serve`."
                )

    config = _make_config(provider_type, cfg, temperature=temperature)
    if provider_type == LLMProviderType.GROQ:
        if not config.api_key:
            raise ValueError("Groq API ключ не настроен")
        return GroqProvider(config)
    return OllamaProvider(config)


def list_available_providers(config_dict: dict | None = None) -> list[dict[str, Any]]:
    """Список провайдеров для отображения в UI."""
    cfg = config_dict if config_dict is not None else CONFIG

    ollama_model = cfg["model"]["llm"]
    ollama_available = OllamaProvider(
        _make_config(LLMProviderType.OLLAMA, cfg)
    ).is_available()

    groq_cfg = cfg.get("groq", {})
    groq_model = groq_cfg.get("model", "llama-3.1-8b-instant")
    groq_available = bool(_groq_api_key(cfg))

    return [
        {
            "name": "Ollama",
            "type": LLMProviderType.OLLAMA.value,
            "available": ollama_available,
            "model": ollama_model,
        },
        {
            "name": "Groq",
            "type": LLMProviderType.GROQ.value,
            "available": groq_available,
            "model": groq_model,
        },
    ]


__all__ = [
    "LLMProviderType",
    "ProviderConfig",
    "LLMProvider",
    "OllamaProvider",
    "GroqProvider",
    "get_llm_provider",
    "list_available_providers",
]
