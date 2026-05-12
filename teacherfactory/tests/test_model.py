"""
Тесты модели LessonCard:
  - to_template_context включает все ключи, на которые ссылается шаблон;
  - вложенные модели (tasks, outcomes, resources) разворачиваются плоско;
  - lesson_structure становится списком dict (для {%tr for %} в docxtpl).
"""

import pytest

from teacherfactory.documents.lesson_card import LESSON_CARD
from teacherfactory.model import LessonCard, LessonStep, LessonTasks, PlannedOutcomes, Resources


@pytest.fixture
def card() -> LessonCard:
    return LessonCard(
        lesson_number=1,
        date="01.01.2026",
        group_name="G",
        students_count=1,
        discipline="D",
        specialty="S",
        course_number=1,
        lesson_topic="T",
        lesson_type="L",
        lesson_kind="K",
        duration=45,
        teacher_name="N",
        goal="G",
        tasks=LessonTasks(educational="e", developmental="d", upbringing="u", pedagogical="p"),
        competencies_ok="ОК 01",
        competencies_pk="ПК 1.2",
        outcomes=PlannedOutcomes(
            knowledge_indicator="ki",
            knowledge_control="kc",
            skill_indicator="si",
            skill_control="sc",
            ability_indicator="ai",
            ability_control="ac",
        ),
        resources=Resources(literature="l", internet_resources="i", other_materials="o"),
        lesson_structure=[
            LessonStep(
                number=1, stage="s", time="t", teacher="te", student="st", methods="m", result="r"
            ),
        ],
    )


def test_to_template_context_flattens_tasks(card):
    ctx = card.to_template_context()
    assert ctx["task_educational"] == "e"
    assert ctx["task_developmental"] == "d"
    assert ctx["task_upbringing"] == "u"
    assert ctx["task_pedagogical"] == "p"
    # tasks как объект НЕ должен остаться в плоском контексте
    assert "tasks" not in ctx


def test_to_template_context_flattens_outcomes(card):
    ctx = card.to_template_context()
    assert ctx["knowledge_indicator"] == "ki"
    assert ctx["knowledge_control"] == "kc"
    assert ctx["skill_indicator"] == "si"
    assert ctx["ability_control"] == "ac"
    assert "outcomes" not in ctx


def test_to_template_context_flattens_resources(card):
    ctx = card.to_template_context()
    assert ctx["literature"] == "l"
    assert ctx["internet_resources"] == "i"
    assert ctx["other_materials"] == "o"
    assert "resources" not in ctx


def test_to_template_context_lesson_structure_is_list_of_dicts(card):
    ctx = card.to_template_context()
    structure = ctx["lesson_structure"]
    assert isinstance(structure, list)
    assert isinstance(structure[0], dict)
    assert structure[0]["stage"] == "s"
    assert structure[0]["number"] == 1


def test_template_context_has_all_top_level_fields(card):
    ctx = card.to_template_context()
    expected = {
        "lesson_number",
        "date",
        "group_name",
        "students_count",
        "discipline",
        "specialty",
        "course_number",
        "lesson_topic",
        "lesson_type",
        "lesson_kind",
        "duration",
        "teacher_name",
        "goal",
        "competencies_ok",
        "competencies_pk",
    }
    assert expected.issubset(ctx.keys())


def test_lesson_card_round_trip_via_doc_type(card):
    """Контекст шаблона, полученный через DocumentType, идентичен прямому вызову."""
    assert LESSON_CARD.to_template_context is not None
    via_doc_type = LESSON_CARD.to_template_context(card)
    direct = card.to_template_context()
    assert via_doc_type == direct
