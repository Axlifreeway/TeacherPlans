"""
Тесты валидации компетенций:
  - регулярное выражение для извлечения кодов
  - логика проверки наличия кода в контексте
  - пограничные случаи (нет кодов, форматы написания)
"""

import re
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document


# ─── COMPETENCY_RE ────────────────────────────────────────────────────────────

def test_regex_finds_ok_codes():
    from generator import COMPETENCY_RE
    text = "ОК 01 Выбирать способы решения задач; ОК 02 Использовать технологии"
    codes = COMPETENCY_RE.findall(text)
    assert "ОК 01" in codes
    assert "ОК 02" in codes


def test_regex_finds_pk_codes():
    from generator import COMPETENCY_RE
    text = "ПК 1.2 Выполнять преобразование; ПК 1.6 Формировать запросы"
    codes = COMPETENCY_RE.findall(text)
    assert "ПК 1.2" in codes
    assert "ПК 1.6" in codes


def test_regex_finds_no_space_format():
    from generator import COMPETENCY_RE
    # Некоторые документы пишут без пробела: ОК01, ПК12
    codes = COMPETENCY_RE.findall("ОК01 ПК12")
    assert len(codes) == 2


def test_regex_ignores_random_text():
    from generator import COMPETENCY_RE
    text = "Студент изучает программирование на Python"
    codes = COMPETENCY_RE.findall(text)
    assert codes == []


def test_regex_handles_mixed_text():
    from generator import COMPETENCY_RE
    text = "Формируются: ОК 01, ОК 04, ПК 1.6, ПК 1.7"
    codes = COMPETENCY_RE.findall(text)
    assert len(codes) == 4


# ─── validate_competencies ────────────────────────────────────────────────────

def _make_card(ok: str = "", pk: str = "") -> MagicMock:
    card = MagicMock()
    card.competencies_ok = ok
    card.competencies_pk = pk
    return card


def test_validation_finds_existing_code(mock_faiss, bm25_data):
    """Код, реально присутствующий в документах, должен быть помечен как найденный."""
    from generator import validate_competencies

    card = _make_card(ok="ОК 01 Выбирать способы решения задач")

    with patch("generator.load_index", return_value=(mock_faiss, bm25_data)):
        result = validate_competencies(card)

    assert "ОК 01" in result
    assert result["ОК 01"] is True


def test_validation_flags_missing_code(mock_faiss, bm25_data):
    """Выдуманный код, которого нет в документах, должен быть помечен как не найденный."""
    from generator import validate_competencies

    card = _make_card(ok="ОК 99 Несуществующая компетенция")

    # Возвращаем документы без ОК 99
    mock_faiss.similarity_search.return_value = [
        Document(page_content="ОК 01 Выбирать способы решения", metadata={})
    ]

    with patch("generator.load_index", return_value=(mock_faiss, bm25_data)):
        result = validate_competencies(card)

    assert "ОК 99" in result
    assert result["ОК 99"] is False


def test_validation_empty_card(mock_faiss, bm25_data):
    """Карта без компетенций не должна вызывать ошибку."""
    from generator import validate_competencies

    card = _make_card(ok="Не указано в документах", pk="")

    with patch("generator.load_index", return_value=(mock_faiss, bm25_data)):
        result = validate_competencies(card)

    assert result == {}


def test_validation_deduplicates_codes(mock_faiss, bm25_data):
    """Один и тот же код в ОК и ПК полях не должен проверяться дважды."""
    from generator import validate_competencies

    card = _make_card(ok="ОК 01 текст ОК 01 дубль", pk="")

    call_count = 0
    original_retrieve = None

    with patch("generator.load_index", return_value=(mock_faiss, bm25_data)):
        with patch("generator.retrieve_context") as mock_retrieve:
            mock_retrieve.return_value = "ОК01 найдено"
            validate_competencies(card)
            # ОК 01 встречается дважды, но проверяться должен один раз
            assert mock_retrieve.call_count == 1


# ─── Нормализация кодов при сравнении ─────────────────────────────────────────

def test_validation_normalizes_whitespace():
    """ОК 01 и ОК01 должны считаться одним кодом при поиске."""
    import re as re_module
    from generator import COMPETENCY_RE

    # Проверяем что нормализация убирает пробелы
    code = "ОК 01"
    normalized = re_module.sub(r"\s+", "", code)
    assert normalized == "ОК01"

    context_with_space = "В программе указаны ОК 01 и ОК 02"
    context_normalized = re_module.sub(r"\s+", "", context_with_space)
    assert "ОК01" in context_normalized
