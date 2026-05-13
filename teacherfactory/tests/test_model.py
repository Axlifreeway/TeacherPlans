"""
Тесты модели LessonCard:
  - to_template_context выдаёт ключи, на которые ссылается шаблон;
  - вложенные модели (tasks, taula методов) разворачиваются плоско;
  - таблицы (learning_outcomes, competencies, lesson_structure, межсвязи)
    становятся списками dict (для {%tr for %} в docxtpl).
"""

import pytest

from teacherfactory.documents.lesson_card import LESSON_CARD
from teacherfactory.model import LessonCard
from tests.conftest import build_stub_card


@pytest.fixture
def card() -> LessonCard:
    return build_stub_card()


def test_to_template_context_flattens_tasks(card):
    ctx = card.to_template_context()
    assert "task_educational" in ctx
    assert "task_developmental" in ctx
    assert "task_upbringing" in ctx
    assert "task_perspective" in ctx
    assert "task_personal" in ctx
    # tasks как объект НЕ должен остаться в плоском контексте
    assert "tasks" not in ctx


def test_to_template_context_flattens_methods_table(card):
    ctx = card.to_template_context()
    assert "method_source" in ctx
    assert "method_character" in ctx
    assert "method_independence" in ctx
    assert "method_health" in ctx
    assert "teaching_methods_table" not in ctx


def test_to_template_context_lists_are_present(card):
    ctx = card.to_template_context()
    assert isinstance(ctx["learning_outcomes"], list)
    assert isinstance(ctx["competencies"], list)
    assert isinstance(ctx["interdisciplinary_connections"], list)
    assert isinstance(ctx["lesson_structure"], list)
    assert isinstance(ctx["learning_outcomes"][0], dict)
    assert ctx["competencies"][0]["code"] == "ОК 01"


def test_to_template_context_lesson_structure_is_list_of_dicts(card):
    ctx = card.to_template_context()
    structure = ctx["lesson_structure"]
    assert isinstance(structure, list)
    assert isinstance(structure[0], dict)
    assert structure[0]["stage"] == "Орг"
    assert structure[0]["number"] == 1


def test_to_template_context_resources_are_strings(card):
    """Списочные ресурсы превращаются в готовую к выводу строку с маркерами."""
    ctx = card.to_template_context()
    assert isinstance(ctx["lit_main"], str)
    assert isinstance(ctx["databases"], str)
    assert ctx["lit_main"].startswith("— ")
    assert "resources" not in ctx  # объект не должен утечь в плоский ctx


def test_template_context_has_all_top_level_fields(card):
    ctx = card.to_template_context()
    expected = {
        "discipline",
        "specialty",
        "course_number",
        "group_name",
        "students_count",
        "lesson_topic",
        "lesson_type",
        "lesson_kind",
        "duration",
        "teacher_name",
        "pedagogical_technologies",
        "goal",
        "epigraph",
        "epigraph_author",
        "teaching_means",
    }
    assert expected.issubset(ctx.keys())


def test_lesson_card_round_trip_via_doc_type(card):
    """Контекст шаблона, полученный через DocumentType, идентичен прямому вызову."""
    assert LESSON_CARD.to_template_context is not None
    via_doc_type = LESSON_CARD.to_template_context(card)
    direct = card.to_template_context()
    assert via_doc_type == direct
