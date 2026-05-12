"""
Пост-валидация результата генерации.

Сейчас единственная проверка — наличие кодов компетенций в индексированных
документах (защита от галлюцинаций LLM).
"""

import logging

from teacherfactory.model import LessonCard
from teacherfactory.retrieval import load_index, retrieve_context
from teacherfactory.text_utils import COMPETENCY_RE, normalize_code

log = logging.getLogger(__name__)


def validate_competencies(card: LessonCard) -> dict[str, bool]:
    """
    Проверяет наличие кодов компетенций из карты в индексированных документах.

    Возвращает {код: найден_ли_в_документах}.
    Коды, которых нет в индексе — скорее всего выдуманы LLM.
    """
    db, bm25_data = load_index()
    all_text = f"{card.competencies_ok} {card.competencies_pk}"
    codes = list(set(COMPETENCY_RE.findall(all_text)))

    if not codes:
        return {}

    results: dict[str, bool] = {}
    for code in codes:
        context = retrieve_context(db, bm25_data, code, k=3)
        found = normalize_code(code) in normalize_code(context)
        results[code] = found
        log.info("Компетенция %s: %s", code, "найдена" if found else "НЕ НАЙДЕНА в документах")

    return results
