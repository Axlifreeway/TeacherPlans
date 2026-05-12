"""
Базовая спецификация типа документа.

`DocumentType` объединяет всё, что отличает «технологическую карту» от
«РПД» или «КОС»:
  - Pydantic-модель (структура данных, которую возвращает LLM)
  - шаблон DOCX
  - промпты system/user
  - правила построения retrieval-запросов
  - (опционально) пост-валидация
  - (опционально) маппинг модели в контекст шаблона

Параметризован по типу модели `T` (PEP 695), чтобы callbacks `validate` и
`to_template_context` принимали конкретный тип, а не безликий `BaseModel`.
Пайплайн `generate_document()` работает с этим объектом и ничего не знает
про конкретный тип документа.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel


@dataclass(frozen=True)
class DocumentType[T: BaseModel]:
    slug: str
    """Машинный идентификатор: «lesson_card», «rpd», «assessment»."""

    title: str
    """Человекочитаемое название для UI: «Технологическая карта урока»."""

    model: type[T]
    """Pydantic-схема, под которую LLM формирует структурированный ответ."""

    template_path: Path
    """Путь к DOCX-шаблону (jinja-плейсхолдеры через docxtpl)."""

    system_prompt: str
    """Шаблон system-промпта. Должен содержать `{context}`."""

    user_prompt: str
    """Шаблон user-промпта. Должен содержать поля из params."""

    build_queries: Callable[[dict], list[str]]
    """params → список поисковых запросов в RAG-индекс."""

    filename_pattern: str
    """Шаблон имени файла, форматируется через `.format(**params)`."""

    validate: Callable[[T], dict[str, bool]] | None = None
    """Опциональная пост-валидация (например, проверка кодов компетенций)."""

    to_template_context: Callable[[T], dict] | None = None
    """
    Преобразование модели в плоский dict для docxtpl.
    По умолчанию используется `model.model_dump()`.
    """

    required_params: tuple[str, ...] = field(default_factory=tuple)
    """Ключи, обязательные в params. Проверяются перед запуском пайплайна."""
