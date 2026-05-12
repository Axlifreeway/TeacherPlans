"""
Реестр типов документов, которые умеет генерировать TeacherFactory.

Добавление нового типа (РПД, аттестационные материалы, КОС и т.п.):
  1. Опиши Pydantic-модель в `model.py` или в собственном модуле.
  2. Напиши шаблон DOCX (templates/<имя>.docx) с jinja-плейсхолдерами.
  3. Создай `documents/<slug>.py` по образу `documents/lesson_card.py`.
  4. Зарегистрируй экземпляр `DocumentType` в `_REGISTRY` ниже.

После этого UI и пайплайн автоматически подхватят новый тип:
  - `get_document_type("rpd")`
  - `list_document_types()` для списка во вкладках/dropdown.
"""

from typing import Any

from teacherfactory.documents.base import DocumentType
from teacherfactory.documents.lesson_card import LESSON_CARD

# В реестре документы разных типов лежат вперемешку. `DocumentType[Any]` —
# единственный практичный способ собрать их в одну коллекцию; при работе
# с конкретным типом всегда используй сам объект (`LESSON_CARD`), а не
# выборку из реестра.
_REGISTRY: dict[str, DocumentType[Any]] = {
    LESSON_CARD.slug: LESSON_CARD,
}


def get_document_type(slug: str) -> DocumentType[Any]:
    try:
        return _REGISTRY[slug]
    except KeyError as e:
        known = ", ".join(_REGISTRY) or "—"
        raise ValueError(
            f"Неизвестный тип документа: '{slug}'. Зарегистрированные: {known}."
        ) from e


def list_document_types() -> list[DocumentType[Any]]:
    return list(_REGISTRY.values())


__all__ = ["DocumentType", "get_document_type", "list_document_types"]
