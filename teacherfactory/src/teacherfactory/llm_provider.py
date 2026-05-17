"""
Единый интерфейс для LLM-провайдеров.

Поддерживает:
- Gemini (Google AI Studio, бесплатный тариф 1500 RPD, контекст 1M)
- Groq (облако, бесплатный тариф, быстро)
- OpenRouter (облако, OpenAI-совместимый API, много моделей включая :free)
- Ollama (локально)

Использование:
    from llm_provider import get_llm_provider, LLMProviderType

    provider = get_llm_provider()                # автовыбор по конфигурации
    text = provider.generate("вопрос", system_prompt="...")

    for chunk in provider.stream_chat(messages):
        print(chunk, end="")

Fallback-цепочка:
    provider = get_llm_provider(LLMProviderType.FALLBACK)
    # Внутри: Gemini → Groq → OpenRouter → Ollama (порядок — по доступности).
    # При rate-limit / сетевой ошибке langchain автоматически
    # перебирает провайдеров через Runnable.with_fallbacks.
"""

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Generator
from enum import StrEnum
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, SecretStr, ValidationError

from teacherfactory.config import CONFIG

log = logging.getLogger(__name__)


class LLMProviderType(StrEnum):
    OLLAMA = "ollama"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    GEMINI = "gemini"
    FALLBACK = "fallback"  # цепочка Gemini → Groq → OpenRouter → Ollama


class ProviderConfig(BaseModel):
    provider_type: LLMProviderType
    model_name: str
    # SecretStr: исключаем ключ из repr/str и из любых случайных логов.
    # Доступ к самому значению — только через api_key.get_secret_value().
    api_key: SecretStr | None = None
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
        return str(response.content)

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str = "",
    ) -> Generator[str]:
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
        except (requests.RequestException, OSError):
            return False
        return bool(response.status_code == 200)


class GroqProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "Groq"

    def _create_client(self) -> Any:
        from langchain_groq import ChatGroq

        if self.config.api_key is None:
            raise ValueError("Groq API ключ не настроен")

        # Reasoning-модели (deepseek-r1*) тратят токены на <think>...</think>
        # перед tool call; обычным моделям 8K хватает с запасом.
        is_reasoning = "deepseek-r1" in self.config.model_name.lower()
        max_out = 16384 if is_reasoning else 8192

        kwargs: dict[str, Any] = {
            "api_key": self.config.api_key,  # ChatGroq принимает SecretStr напрямую
            "model": self.config.model_name,
            "temperature": self.config.temperature,
            "streaming": True,
            "max_tokens": max_out,
            # Без явного таймаута httpx висит 600 с (дефолт openai/groq SDK) —
            # на free-tier это превращает fallback в фикцию: запрос не
            # бросает исключение, а просто стоит. 90 с хватает на честную
            # генерацию большой карты, всё, что дольше — гарантированно
            # rate-limit/очередь, и пусть пускают следующего.
            "timeout": 90.0,
            "max_retries": 1,
        }
        # reasoning_format="hidden" прячет <think>-блок на стороне Groq,
        # чтобы он не мешал langchain распарсить tool call.
        if is_reasoning:
            kwargs["reasoning_format"] = "hidden"

        return ChatGroq(**kwargs)

    def is_available(self) -> bool:
        return self.config.api_key is not None


class OpenRouterProvider(LLMProvider):
    """OpenAI-совместимый шлюз к десяткам моделей.

    Free-tier: модели с суффиксом ":free" (общая квота ~20 RPM, без оплаты).
    Платные модели стоят дёшево, но требуют пополнения баланса.
    Документация: https://openrouter.ai/docs
    """

    @property
    def name(self) -> str:
        return "OpenRouter"

    def _create_client(self) -> Any:
        from langchain_openai import ChatOpenAI

        if self.config.api_key is None:
            raise ValueError("OpenRouter API ключ не настроен")

        # OpenRouter рекомендует указывать заголовки HTTP-Referer и X-Title
        # для атрибуции трафика и попадания в их лидерборд приложений.
        default_headers = {
            "HTTP-Referer": "https://github.com/Axlifreeway/teacherfactory",
            "X-Title": "TeacherFactory",
        }
        return ChatOpenAI(
            api_key=self.config.api_key,
            model=self.config.model_name,
            base_url=self.config.base_url or "https://openrouter.ai/api/v1",
            temperature=self.config.temperature,
            streaming=True,
            max_tokens=8192,
            default_headers=default_headers,
            # На :free-моделях OpenRouter любит молча держать запрос в
            # очереди. Без таймаута fallback-цепочка зависает. 120 с —
            # компромисс: реальная генерация 70B обычно укладывается,
            # очередь — нет.
            timeout=120.0,
            max_retries=1,
        )

    def is_available(self) -> bool:
        return self.config.api_key is not None


class GeminiProvider(LLMProvider):
    """Google Gemini через Google AI Studio API.

    Free-tier: 1500 запросов/день, 15 RPM, 1M контекст. Гибкий по размеру
    промпта — не упирается в Groq-овский TPM на больших RAG-контекстах.
    Ключ: https://aistudio.google.com/apikey
    """

    @property
    def name(self) -> str:
        return "Gemini"

    def _create_client(self) -> Any:
        from langchain_google_genai import ChatGoogleGenerativeAI

        if self.config.api_key is None:
            raise ValueError("Gemini API ключ не настроен")

        return ChatGoogleGenerativeAI(
            api_key=self.config.api_key,
            model=self.config.model_name,
            temperature=self.config.temperature,
            max_output_tokens=8192,
            # Без таймаута langchain-google-genai по умолчанию ждёт минуты при
            # очереди — fallback в этот момент не срабатывает.
            timeout=120.0,
            max_retries=1,
        )

    def is_available(self) -> bool:
        return self.config.api_key is not None


# ─── Fallback-цепочка ─────────────────────────────────────────────────────────


# Какие исключения трактуем как «попробуй следующий провайдер».
# Импортируем лениво, чтобы не тянуть зависимости провайдеров до использования.
def _fallback_exceptions() -> tuple[type[BaseException], ...]:
    excs: list[type[BaseException]] = [TimeoutError, ConnectionError]
    # httpx — нижний слой openai/groq SDK. Без его таймаутов в списке
    # ReadTimeout может проскочить мимо APIError и завесить цепочку.
    try:
        import httpx

        excs.extend([httpx.TimeoutException, httpx.HTTPError])
    except ImportError:
        pass
    # Groq / OpenAI поднимают свои подклассы; импорт ленивый, чтобы не падать,
    # если соответствующий пакет не установлен.
    try:
        from groq import APIError as GroqAPIError, APIStatusError as GroqAPIStatusError

        excs.extend([GroqAPIError, GroqAPIStatusError])
    except ImportError:
        pass
    try:
        from openai import APIError as OpenAIAPIError, APIStatusError as OpenAIAPIStatusError

        excs.extend([OpenAIAPIError, OpenAIAPIStatusError])
    except ImportError:
        pass
    return tuple(excs)


class FallbackProvider(LLMProvider):
    """Цепочка из нескольких провайдеров. Первый — основной, остальные —
    подменяют его при rate-limit/сетевой ошибке через `Runnable.with_fallbacks`.

    Имена/модель отражают первого; `.config` берётся у него же, чтобы внешний
    код (например, логирование) видел осмысленные значения.
    """

    def __init__(self, primary: LLMProvider, fallbacks: list[LLMProvider]):
        super().__init__(primary.config)
        self.primary = primary
        self.fallbacks = fallbacks

    @property
    def name(self) -> str:
        chain = " → ".join([self.primary.name, *(f.name for f in self.fallbacks)])
        return f"Fallback ({chain})"

    def is_available(self) -> bool:
        return self.primary.is_available() or any(f.is_available() for f in self.fallbacks)

    def _create_client(self) -> Any:
        excs = _fallback_exceptions()
        base = self.primary.get_client()
        fbs = [f.get_client() for f in self.fallbacks]
        if not fbs:
            return base
        return base.with_fallbacks(fbs, exceptions_to_handle=excs)


# ─── Фабрика ──────────────────────────────────────────────────────────────────


def _groq_api_key(config_dict: dict) -> SecretStr | None:
    """Берёт ключ Groq из конфига или переменной окружения."""
    raw = config_dict.get("groq", {}).get("api_key") or os.getenv("GROQ_API_KEY")
    return SecretStr(raw) if raw else None


def _openrouter_api_key(config_dict: dict) -> SecretStr | None:
    raw = config_dict.get("openrouter", {}).get("api_key") or os.getenv("OPENROUTER_API_KEY")
    return SecretStr(raw) if raw else None


def _gemini_api_key(config_dict: dict) -> SecretStr | None:
    raw = (
        config_dict.get("gemini", {}).get("api_key")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )
    return SecretStr(raw) if raw else None


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
        if provider_type == LLMProviderType.OPENROUTER:
            or_cfg = config_dict.get("openrouter", {})
            return ProviderConfig(
                provider_type=LLMProviderType.OPENROUTER,
                model_name=or_cfg.get("model", "meta-llama/llama-3.3-70b-instruct:free"),
                api_key=_openrouter_api_key(config_dict),
                base_url=or_cfg.get("base_url", "https://openrouter.ai/api/v1"),
                temperature=temp,
            )
        if provider_type == LLMProviderType.GEMINI:
            gemini_cfg = config_dict.get("gemini", {})
            return ProviderConfig(
                provider_type=LLMProviderType.GEMINI,
                model_name=gemini_cfg.get("model", "gemini-2.0-flash"),
                api_key=_gemini_api_key(config_dict),
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


def _single_provider(
    provider_type: LLMProviderType,
    cfg: dict,
    temperature: float | None,
) -> LLMProvider:
    config = _make_config(provider_type, cfg, temperature=temperature)
    if provider_type == LLMProviderType.GROQ:
        if config.api_key is None:
            raise ValueError("Groq API ключ не настроен")
        return GroqProvider(config)
    if provider_type == LLMProviderType.OPENROUTER:
        if config.api_key is None:
            raise ValueError("OpenRouter API ключ не настроен")
        return OpenRouterProvider(config)
    if provider_type == LLMProviderType.GEMINI:
        if config.api_key is None:
            raise ValueError("Gemini API ключ не настроен")
        return GeminiProvider(config)
    return OllamaProvider(config)


def _build_fallback(cfg: dict, temperature: float | None) -> FallbackProvider:
    """Строит цепочку Gemini → Groq → OpenRouter → Ollama из доступных.

    Gemini ставим первым: free-tier 1500 RPD и контекст 1M токенов перекрывают
    Groq-овский TPM-лимит, на котором большие RAG-запросы у нас разваливались.
    Если основной недоступен — повышаем следующий доступный до primary,
    остальные становятся фолбэками. Это даёт работающую цепочку даже когда
    верхний слой ещё не настроен.
    """
    order: list[LLMProviderType] = [
        LLMProviderType.GEMINI,
        LLMProviderType.GROQ,
        LLMProviderType.OPENROUTER,
        LLMProviderType.OLLAMA,
    ]
    available: list[LLMProvider] = []
    for ptype in order:
        try:
            p = _single_provider(ptype, cfg, temperature)
        except ValueError:
            continue
        if p.is_available():
            available.append(p)

    if not available:
        raise ValueError(
            "Ни один LLM-провайдер не доступен. Настройте хотя бы один:\n"
            "  - Gemini: GEMINI_API_KEY или [gemini].api_key в config.local.toml;\n"
            "  - Groq: GROQ_API_KEY или [groq].api_key в config.local.toml;\n"
            "  - OpenRouter: OPENROUTER_API_KEY или [openrouter].api_key;\n"
            "  - Ollama: запустите `ollama serve`."
        )

    return FallbackProvider(available[0], available[1:])


def get_llm_provider(
    provider_type: LLMProviderType | None = None,
    temperature: float | None = None,
    config_dict: dict | None = None,
) -> LLMProvider:
    """
    Получить LLM-провайдер.

    provider_type:
        - None или FALLBACK — цепочка Gemini → Groq → OpenRouter → Ollama
          (по доступности; недоступные пропускаются);
        - GEMINI / GROQ / OPENROUTER / OLLAMA — конкретный провайдер.
    """
    cfg = config_dict if config_dict is not None else CONFIG

    if provider_type is None or provider_type == LLMProviderType.FALLBACK:
        return _build_fallback(cfg, temperature)

    return _single_provider(provider_type, cfg, temperature)


def list_available_providers(config_dict: dict | None = None) -> list[dict[str, Any]]:
    """Список провайдеров для отображения в UI."""
    cfg = config_dict if config_dict is not None else CONFIG

    ollama_model = cfg["model"]["llm"]
    ollama_available = OllamaProvider(_make_config(LLMProviderType.OLLAMA, cfg)).is_available()

    groq_cfg = cfg.get("groq", {})
    groq_model = groq_cfg.get("model", "llama-3.1-8b-instant")
    groq_available = _groq_api_key(cfg) is not None

    or_cfg = cfg.get("openrouter", {})
    or_model = or_cfg.get("model", "meta-llama/llama-3.3-70b-instruct:free")
    or_available = _openrouter_api_key(cfg) is not None

    gemini_cfg = cfg.get("gemini", {})
    gemini_model = gemini_cfg.get("model", "gemini-2.0-flash")
    gemini_available = _gemini_api_key(cfg) is not None

    # Fallback доступен, если хоть один из четырёх работает.
    fallback_available = (
        ollama_available or groq_available or or_available or gemini_available
    )
    chain_parts = []
    if gemini_available:
        chain_parts.append("Gemini")
    if groq_available:
        chain_parts.append("Groq")
    if or_available:
        chain_parts.append("OpenRouter")
    if ollama_available:
        chain_parts.append("Ollama")
    fallback_model = " → ".join(chain_parts) if chain_parts else "—"

    return [
        {
            "name": "Авто (fallback)",
            "type": LLMProviderType.FALLBACK.value,
            "available": fallback_available,
            "model": fallback_model,
        },
        {
            "name": "Gemini",
            "type": LLMProviderType.GEMINI.value,
            "available": gemini_available,
            "model": gemini_model,
        },
        {
            "name": "Groq",
            "type": LLMProviderType.GROQ.value,
            "available": groq_available,
            "model": groq_model,
        },
        {
            "name": "OpenRouter",
            "type": LLMProviderType.OPENROUTER.value,
            "available": or_available,
            "model": or_model,
        },
        {
            "name": "Ollama",
            "type": LLMProviderType.OLLAMA.value,
            "available": ollama_available,
            "model": ollama_model,
        },
    ]


__all__ = [
    "FallbackProvider",
    "GeminiProvider",
    "GroqProvider",
    "LLMProvider",
    "LLMProviderType",
    "OllamaProvider",
    "OpenRouterProvider",
    "ProviderConfig",
    "get_llm_provider",
    "list_available_providers",
]
