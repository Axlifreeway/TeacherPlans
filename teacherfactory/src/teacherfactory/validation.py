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
    codes = _collect_codes(card)
    if not codes:
        return {}

    db, bm25_data = load_index()
    results: dict[str, bool] = {}
    for code in codes:
        context = retrieve_context(db, bm25_data, code, k=3)
        found = normalize_code(code) in normalize_code(context)
        results[code] = found
        log.info("Компетенция %s: %s", code, "найдена" if found else "НЕ НАЙДЕНА в документах")

    return results


def _collect_codes(card: LessonCard) -> list[str]:
    """
    Собрать уникальные коды компетенций из карты.

    Источники:
      - поле `code` в каждой Competency (основное);
      - текст в `name`/`indicator` — если LLM по ошибке упомянула там код.
    """
    found: set[str] = set()
    for comp in card.competencies:
        for code in COMPETENCY_RE.findall(f"{comp.code} {comp.name} {comp.indicator}"):
            found.add(code)
    return list(found)
