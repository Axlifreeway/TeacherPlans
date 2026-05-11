"""
Единый интерфейс для работы с различными LLM-провайдерами.

Поддерживает:
- Ollama (локально)
- Groq (облако, бесплатно)

Безопасность:
- API ключи через переменные окружения
- Валидация конфигурации
- Изоляция провайдеров

Использование:
    from llm_provider import get_llm_provider, LLMProviderType
    
    provider = get_llm_provider()  # автовыбор по конфигурации
    response = provider.generate("вопрос", system_prompt="...")
    
    # или потоково
    for chunk in provider.stream_chat(messages):
        print(chunk, end="")
"""

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Generator
from enum import Enum
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class LLMProviderType(str, Enum):
    """Типы поддерживаемых LLM-провайдеров."""
    OLLAMA = "ollama"
    GROQ = "groq"


class ProviderConfig(BaseModel):
    """Конфигурация провайдера."""
    provider_type: LLMProviderType
    model_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_retries: int = 3
    timeout: int = 60
    
    class Config:
        use_enum_values = True


class LLMProvider(ABC):
    """Абстрактный базовый класс для LLM-провайдеров."""
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client = None
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Название провайдера."""
        pass
    
    @abstractmethod
    def _create_client(self) -> Any:
        """Создание клиента API."""
        pass
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Генерация текста."""
        pass
    
    @abstractmethod
    def stream_chat(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = ""
    ) -> Generator[str, None, None]:
        """Потоковый чат."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Проверка доступности провайдера."""
        pass
    
    def _get_client(self) -> Any:
        """Ленивая инициализация клиента."""
        if self._client is None:
            self._client = self._create_client()
        return self._client


class OllamaProvider(LLMProvider):
    """Провайдер для локальной Ollama."""
    
    @property
    def name(self) -> str:
        return "Ollama"
    
    def _create_client(self) -> Any:
        from langchain_ollama import ChatOllama
        
        return ChatOllama(
            model=self.config.model_name,
            temperature=self.config.temperature,
            num_gpu=-1 if os.name == 'nt' else 0,  # Адаптация под ОС
            keep_alive="10m",
        )
    
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        client = self._get_client()
        
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))
        
        response = client.invoke(messages)
        return response.content
    
    def stream_chat(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = ""
    ) -> Generator[str, None, None]:
        client = self._get_client()
        
        chat_messages = []
        if system_prompt:
            chat_messages.append(SystemMessage(content=system_prompt))
        
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            
            if role == 'user':
                chat_messages.append(HumanMessage(content=content))
            elif role == 'assistant':
                chat_messages.append(HumanMessage(content=content))
        
        stream = client.stream(chat_messages)
        for chunk in stream:
            yield chunk.content
    
    def is_available(self) -> bool:
        """Проверка доступности Ollama."""
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False


class GroqProvider(LLMProvider):
    """Провайдер для облачного Groq API."""
    
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
    
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        client = self._get_client()
        
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))
        
        response = client.invoke(messages)
        return response.content
    
    def stream_chat(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = ""
    ) -> Generator[str, None, None]:
        client = self._get_client()
        
        chat_messages = []
        if system_prompt:
            chat_messages.append(SystemMessage(content=system_prompt))
        
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            
            if role == 'user':
                chat_messages.append(HumanMessage(content=content))
            elif role == 'assistant':
                chat_messages.append(HumanMessage(content=content))
        
        stream = client.stream(chat_messages)
        for chunk in stream:
            if hasattr(chunk, 'content'):
                yield chunk.content
            else:
                yield str(chunk)
    
    def is_available(self) -> bool:
        """Проверка наличия API ключа."""
        return bool(self.config.api_key)


def create_provider_config(
    provider_type: LLMProviderType,
    model_name: str,
    api_key: Optional[str] = None,
    temperature: float = 0.7,
) -> ProviderConfig:
    """Создание конфигурации провайдера с валидацией."""
    try:
        return ProviderConfig(
            provider_type=provider_type.value if isinstance(provider_type, LLMProviderType) else provider_type,
            model_name=model_name,
            api_key=api_key,
            temperature=temperature,
        )
    except ValidationError as e:
        logger.error(f"Ошибка валидации конфигурации: {e}")
        raise


def get_llm_provider(
    provider_type: Optional[LLMProviderType] = None,
    config_dict: Optional[Dict] = None,
) -> LLMProvider:
    """
    Фабрика для получения LLM-провайдера.
    
    Args:
        provider_type: Тип провайдера (автовыбор если None)
        config_dict: Словарь конфигурации
    
    Returns:
        Экземпляр LLMProvider
    
    Raises:
        ValueError: Если ни один провайдер не доступен
    """
    from .config import CONFIG
    
    if config_dict is None:
        config_dict = CONFIG
    
    # Автоопределение провайдера
    if provider_type is None:
        # Проверяем Groq
        groq_config = config_dict.get("groq", {})
        if groq_config.get("api_key"):
            provider_type = LLMProviderType.GROQ
            logger.info("Автовыбран провайдер: Groq")
        # Проверяем Ollama
        elif OllamaProvider(
            create_provider_config(
                LLMProviderType.OLLAMA,
                config_dict["model"]["llm"]
            )
        ).is_available():
            provider_type = LLMProviderType.OLLAMA
            logger.info("Автовыбран провайдер: Ollama")
        else:
            raise ValueError(
                "Ни один LLM-провайдер не доступен!\n"
                "- Для Groq: добавьте api_key в config.local.toml\n"
                "- Для Ollama: запустите ollama serve"
            )
    
    # Создание провайдера
    if provider_type == LLMProviderType.GROQ:
        groq_config = config_dict.get("groq", {})
        api_key = groq_config.get("api_key") or os.getenv("GROQ_API_KEY")
        
        if not api_key:
            raise ValueError("Groq API ключ не настроен!")
        
        config = create_provider_config(
            LLMProviderType.GROQ,
            groq_config.get("model", "llama-3.1-8b-instant"),
            api_key=api_key,
            temperature=config_dict["model"].get("chat_temperature", 0.7),
        )
        return GroqProvider(config)
    
    elif provider_type == LLMProviderType.OLLAMA:
        config = create_provider_config(
            LLMProviderType.OLLAMA,
            config_dict["model"]["llm"],
            temperature=config_dict["model"].get("chat_temperature", 0.7),
        )
        return OllamaProvider(config)
    
    else:
        raise ValueError(f"Неподдерживаемый тип провайдера: {provider_type}")


def list_available_providers(config_dict: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """
    Получить список доступных провайдеров.
    
    Returns:
        Список словарей: [{'name': str, 'type': str, 'available': bool, 'model': str}]
    """
    from .config import CONFIG
    
    if config_dict is None:
        config_dict = CONFIG
    
    providers = []
    
    # Ollama
    ollama_model = config_dict["model"]["llm"]
    ollama_available = OllamaProvider(
        create_provider_config(LLMProviderType.OLLAMA, ollama_model)
    ).is_available()
    providers.append({
        "name": "Ollama",
        "type": LLMProviderType.OLLAMA.value,
        "available": ollama_available,
        "model": ollama_model,
    })
    
    # Groq
    groq_config = config_dict.get("groq", {})
    groq_api_key = groq_config.get("api_key") or os.getenv("GROQ_API_KEY")
    groq_model = groq_config.get("model", "llama-3.1-8b-instant")
    groq_available = bool(groq_api_key)
    providers.append({
        "name": "Groq",
        "type": LLMProviderType.GROQ.value,
        "available": groq_available,
        "model": groq_model,
    })
    
    return providers


__all__ = [
    "LLMProviderType",
    "ProviderConfig",
    "LLMProvider",
    "OllamaProvider",
    "GroqProvider",
    "get_llm_provider",
    "list_available_providers",
    "create_provider_config",
]
