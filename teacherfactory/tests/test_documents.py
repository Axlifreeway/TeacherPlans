"""
Тесты реестра типов документов.

Ключевая ценность реестра — масштабируемость. Тесты ловят:
  - LESSON_CARD честно зарегистрирован;
  - get_document_type корректно работает и кидает осмысленную ошибку;
  - DocumentType — frozen (нельзя случайно перезаписать поля в runtime);
  - required_params реально проверяются в пайплайне (см. test_pipeline.py).
"""

import dataclasses

import pytest

from teacherfactory.documents import (
    get_document_type,
    list_document_types,
)
from teacherfactory.documents.lesson_card import LESSON_CARD, build_lesson_queries
from teacherfactory.model import LessonCard


def test_lesson_card_is_registered():
    assert LESSON_CARD.slug == "lesson_card"
    assert LESSON_CARD.model is LessonCard
    assert "lesson_card" in {dt.slug for dt in list_document_types()}


def test_get_document_type_returns_same_object():
    assert get_document_type("lesson_card") is LESSON_CARD


def test_get_document_type_unknown_raises():
    with pytest.raises(ValueError, match="Неизвестный тип документа"):
        get_document_type("not_a_real_type")


def test_get_document_type_error_lists_known():
    """Сообщение об ошибке должно подсказывать, что зарегистрировано."""
    with pytest.raises(ValueError, match="lesson_card"):
        get_document_type("rpd")


def test_document_type_is_frozen():
    """frozen=True: попытка переписать поле должна падать."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        LESSON_CARD.slug = "other"  # type: ignore[misc]


def test_lesson_card_template_exists():
    """Спецификация ссылается на реальный файл — иначе render упадёт в проде."""
    assert LESSON_CARD.template_path.exists(), f"Шаблон не найден: {LESSON_CARD.template_path}"


def test_lesson_card_required_params_cover_user_prompt():
    """
    Все плейсхолдеры из user_prompt должны быть в required_params.
    Если кто-то добавит новое поле в промпт, но забудет в required_params —
    тест ловит.
    """
    import string

    placeholders = {
        fname
        for _, fname, _, _ in string.Formatter().parse(LESSON_CARD.user_prompt)
        if fname and not fname.startswith("0")
    }
    # `lesson_topic` встречается дважды в шаблоне — формат всё равно даст имя.
    declared = set(LESSON_CARD.required_params)
    missing = placeholders - declared
    assert not missing, f"Поля промпта не объявлены в required_params: {missing}"


def test_build_lesson_queries_returns_useful_queries():
    queries = build_lesson_queries({"discipline": "Базы данных", "specialty": "09.01.03"})
    assert len(queries) >= 2
    assert all("Базы данных" in q or "09.01.03" in q or "компетенц" in q.lower() for q in queries)


def test_lesson_card_to_template_context_callable():
    """Если to_template_context указан, он должен быть вызываемым."""
    assert LESSON_CARD.to_template_context is not None
    assert callable(LESSON_CARD.to_template_context)


def test_lesson_card_validate_callable():
    assert LESSON_CARD.validate is not None
    assert callable(LESSON_CARD.validate)
