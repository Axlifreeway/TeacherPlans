"""
Groq API интеграция для TeacherFactory.

Groq предоставляет бесплатный доступ к LLM с высокими лимитами:
- Llama 3.1 8B/70B, Mixtral 8x7B, Gemma 2 9B
- Бесплатно: ~30 запросов в минуту (зависит от модели)
- Не требует локальной установки моделей

Получить API ключ: https://console.groq.com/keys

Использование:
    1. Зарегистрируйся на https://console.groq.com/
    2. Создай API ключ
    3. Добавь в config.local.toml:
       
       [groq]
       api_key = "gsk_..."
       model = "llama-3.1-8b-instant"
    
    4. В app.py выбери источник: Ollama или Groq
"""

import logging
from collections.abc import Callable, Generator
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from config import CONFIG
from model import LessonCard

log = logging.getLogger(__name__)


# ─── Callback для подсчёта токенов ────────────────────────────────────────────

class _TokenCallback(BaseCallbackHandler):
    """Считает сгенерированные токены."""
    
    def __init__(self, on_token: Callable[[int], None]) -> None:
        self._fn = on_token
        self.count = 0

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        self.count += 1
        self._fn(self.count)


# ─── Создание LLM ─────────────────────────────────────────────────────────────

def _make_groq_llm(
    temperature: float = 0.1,
    streaming: bool = False,
    callbacks: list | None = None,
) -> ChatGroq:
    """
    Создать ChatGroq实例.
    
    Параметры:
        temperature: температура генерации (0.1 для карт, 0.7 для чата)
        streaming: потоковый вывод
        callbacks: callback'и для обработки токенов
    
    Возвращает:
        ChatGroq instance
    
    Raises:
        ValueError: если API ключ не настроен
    """
    groq_config = CONFIG.get("groq", {})
    api_key = groq_config.get("api_key")
    model = groq_config.get("model", "llama-3.1-8b-instant")
    
    if not api_key:
        raise ValueError(
            "Groq API ключ не настроен! "
            "Добавь в config.local.toml:\n"
            "[groq]\n"
            "api_key = \"gsk_...\"\n"
            "Получить ключ: https://console.groq.com/keys"
        )
    
    log.info(f"Инициализация Groq: модель={model}")
    
    return ChatGroq(
        api_key=api_key,
        model_name=model,
        temperature=temperature,
        streaming=streaming,
        callbacks=callbacks or [],
    )


# ─── Генерация технологической карты ──────────────────────────────────────────

# Промпты те же самые, что и для Ollama (импортируем из generator)
from generator import SYSTEM_PROMPT, USER_PROMPT


def generate_with_groq(
    params: dict,
    context: str,
    on_token: Callable[[int], None] | None = None,
) -> LessonCard:
    """
    Сгенерировать технологическую карту через Groq API.
    
    Параметры:
        params: параметры урока (discipline, specialty, topic, ...)
        context: контекст из нормативных документов (найденный через RAG)
        on_token: callback для отображения прогресса генерации
    
    Возвращает:
        LessonCard: валидированная технологическая карта
    
    Raises:
        ValueError: если API ключ не настроен
        Exception: ошибки API (лимиты, сеть и т.п.)
    """
    callbacks = [_TokenCallback(on_token)] if on_token else []
    
    llm = _make_groq_llm(
        temperature=CONFIG["model"]["temperature"],
        streaming=True,
        callbacks=callbacks,
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT),
    ])
    
    chain = prompt | llm.with_structured_output(LessonCard)
    
    log.info(f"Генерация через Groq: тема={params['lesson_topic']}")
    
    result = chain.invoke({"context": context, **params})
    
    log.info(f"Карта сгенерирована: {result.lesson_topic}")
    return result


# ─── Потоковый чат ────────────────────────────────────────────────────────────

from generator import CHAT_SYSTEM_PROMPT, HYDE_PROMPT


def stream_chat_with_groq(question: str, context: str) -> Generator[str, None, None]:
    """
    Потоковый ответ в чате через Groq API.
    
    Параметры:
        question: вопрос пользователя
        context: контекст из документов (RAG)
    
    Yields:
        str: части ответа (токены)
    
    Raises:
        ValueError: если API ключ не настроен
    """
    llm = _make_groq_llm(
        temperature=CONFIG["model"]["chat_temperature"],
        streaming=True,
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", CHAT_SYSTEM_PROMPT),
        ("human", "Контекст:\n{context}\n\nВопрос: {question}"),
    ])
    
    chain = prompt | llm
    
    log.info(f"Чат через Groq: вопрос={question[:50]}...")
    
    for chunk in chain.stream({"context": context, "question": question}):
        yield chunk.content


# ─── Утилита: проверка доступности ────────────────────────────────────────────

def is_groq_configured() -> bool:
    """Проверить, настроен ли Groq API ключ."""
    groq_config = CONFIG.get("groq", {})
    return bool(groq_config.get("api_key"))


def get_groq_model_info() -> dict:
    """
    Получить информацию о настроенной Groq модели.
    
    Returns:
        dict: {'model': str, 'configured': bool}
    """
    groq_config = CONFIG.get("groq", {})
    return {
        "model": groq_config.get("model", "llama-3.1-8b-instant"),
        "configured": is_groq_configured(),
    }


# ─── Пример использования ─────────────────────────────────────────────────────

if __name__ == "__main__":
    # Тестовый запуск
    logging.basicConfig(level=logging.INFO)
    
    if not is_groq_configured():
        print("❌ Groq API ключ не настроен!")
        print("Добавь в config.local.toml:")
        print("  [groq]")
        print("  api_key = \"gsk_...\"")
        exit(1)
    
    print("✅ Groq настроен!")
    print(f"Модель: {get_groq_model_info()['model']}")
    
    # Тест генерации
    test_params = {
        "discipline": "Компьютерные сети",
        "specialty": "09.02.07",
        "course_number": 2,
        "group_name": "ИС-21",
        "students_count": 25,
        "lesson_topic": "Основы TCP/IP",
        "lesson_number": 1,
        "date": "01.09.2024",
        "teacher_name": "Иванов И.И.",
        "lesson_type": "комбинированный урок",
        "lesson_kind": "лекция",
        "duration": 90,
    }
    
    test_context = "Контекст из документов (для теста пустой)"
    
    def on_token(count: int):
        print(f"\rТокенов: {count}", end="", flush=True)
    
    try:
        card = generate_with_groq(test_params, test_context, on_token=on_token)
        print(f"\n✅ Карта сгенерирована: {card.lesson_topic}")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
