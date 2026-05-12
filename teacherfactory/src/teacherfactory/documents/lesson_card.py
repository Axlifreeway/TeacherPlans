"""
Регистрация типа «Технологическая карта урока».
"""

from teacherfactory.documents.base import DocumentType
from teacherfactory.model import LessonCard
from teacherfactory.paths import LESSON_CARD_TEMPLATE
from teacherfactory.prompts import LESSON_SYSTEM_PROMPT, LESSON_USER_PROMPT


def build_lesson_queries(params: dict) -> list[str]:
    """Несколько вариантов запроса для лучшего покрытия документа."""
    discipline = params["discipline"]
    specialty = params["specialty"]
    return [
        f"{discipline} {specialty} компетенции знания умения навыки",
        f"профессиональные компетенции ПК {discipline}",
        f"общие компетенции ОК {specialty}",
        f"{discipline} результаты освоения рабочая программа",
    ]


def _to_context(card: LessonCard) -> dict:
    return card.to_template_context()


def _validate(card: LessonCard) -> dict[str, bool]:
    # Локальный импорт: validation сам зависит от retrieval, чтобы при
    # импорте `documents.__init__` не тянуть весь стек RAG.
    from teacherfactory.validation import validate_competencies

    return validate_competencies(card)


LESSON_CARD: DocumentType[LessonCard] = DocumentType(
    slug="lesson_card",
    title="Технологическая карта урока",
    model=LessonCard,
    template_path=LESSON_CARD_TEMPLATE,
    system_prompt=LESSON_SYSTEM_PROMPT,
    user_prompt=LESSON_USER_PROMPT,
    build_queries=build_lesson_queries,
    to_template_context=_to_context,
    validate=_validate,
    filename_pattern="Урок_{lesson_number}_{discipline}.docx",
    required_params=(
        "discipline",
        "specialty",
        "course_number",
        "group_name",
        "students_count",
        "lesson_topic",
        "lesson_number",
        "date",
        "teacher_name",
        "lesson_type",
        "lesson_kind",
        "duration",
    ),
)
