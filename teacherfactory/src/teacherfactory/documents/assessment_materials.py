"""
Регистрация типа «Оценочные материалы по дисциплине» (КОС / ФОС).

Структура карты — по шаблону колледжа ИИ ТюмГУ (см. docs/«! ИИКолледж
Шаблон_Оценочные материалы.docx»).
"""

from teacherfactory.documents.base import DocumentType
from teacherfactory.model import AssessmentMaterials
from teacherfactory.paths import ASSESSMENT_TEMPLATE
from teacherfactory.prompts import ASSESSMENT_SYSTEM_PROMPT, ASSESSMENT_USER_PROMPT


def build_assessment_queries(params: dict) -> list[str]:
    """
    Мультизапрос для генерации ОМ.

    Опираемся на тематический план + перечень компетенций РПД, плюс
    раздел «Фонд оценочных средств» / «Контрольно-оценочные средства»,
    если он есть в индексе.
    """
    discipline = params["discipline"]
    specialty = params["specialty"]
    return [
        f"{discipline} тематический план разделы темы",
        f"{discipline} фонд оценочных средств критерии оценивания",
        f"{discipline} {specialty} контрольно-оценочные средства",
        f"профессиональные компетенции ПК {discipline}",
        f"общие компетенции ОК {specialty}",
        f"{discipline} промежуточная аттестация форма контроля",
    ]


def _to_context(materials: AssessmentMaterials) -> dict:
    return materials.to_template_context()


ASSESSMENT_MATERIALS: DocumentType[AssessmentMaterials] = DocumentType(
    slug="assessment_materials",
    title="Оценочные материалы",
    model=AssessmentMaterials,
    template_path=ASSESSMENT_TEMPLATE,
    system_prompt=ASSESSMENT_SYSTEM_PROMPT,
    user_prompt=ASSESSMENT_USER_PROMPT,
    build_queries=build_assessment_queries,
    to_template_context=_to_context,
    filename_pattern="ОМ_{discipline}.docx",
    required_params=(
        "discipline",
        "specialty",
        "semester",
        "final_form",
    ),
)
