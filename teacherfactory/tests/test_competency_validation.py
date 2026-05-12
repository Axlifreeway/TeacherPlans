"""
Тесты валидации компетенций:
  - регулярное выражение для извлечения кодов
  - логика проверки наличия кода в контексте
  - пограничные случаи (нет кодов, форматы написания)
"""

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from teacherfactory.text_utils import COMPETENCY_RE, normalize_code
from teacherfactory.validation import validate_competencies

# ─── COMPETENCY_RE ────────────────────────────────────────────────────────────


def test_regex_finds_ok_codes():
    text = "ОК 01 Выбирать способы решения задач; ОК 02 Использовать технологии"
    codes = COMPETENCY_RE.findall(text)
    assert "ОК 01" in codes
    assert "ОК 02" in codes


def test_regex_finds_pk_codes():
    text = "ПК 1.2 Выполнять преобразование; ПК 1.6 Формировать запросы"
    codes = COMPETENCY_RE.findall(text)
    assert "ПК 1.2" in codes
    assert "ПК 1.6" in codes


def test_regex_finds_no_space_format():
    """Некоторые документы пишут без пробела: ОК01, ПК12."""
    codes = COMPETENCY_RE.findall("ОК01 ПК12")
    assert len(codes) == 2


def test_regex_ignores_random_text():
    text = "Студент изучает программирование на Python"
    codes = COMPETENCY_RE.findall(text)
    assert codes == []


def test_regex_handles_mixed_text():
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
    card = _make_card(ok="ОК 01 Выбирать способы решения задач")

    with patch("teacherfactory.validation.load_index", return_value=(mock_faiss, bm25_data)):
        result = validate_competencies(card)

    assert "ОК 01" in result
    assert result["ОК 01"] is True


def test_validation_flags_missing_code(mock_faiss, bm25_data):
    """Выдуманный код, которого нет в документах, должен быть помечен как не найденный."""
    card = _make_card(ok="ОК 99 Несуществующая компетенция")

    mock_faiss.similarity_search.return_value = [
        Document(page_content="ОК 01 Выбирать способы решения", metadata={})
    ]

    with patch("teacherfactory.validation.load_index", return_value=(mock_faiss, bm25_data)):
        result = validate_competencies(card)

    assert "ОК 99" in result
    assert result["ОК 99"] is False


def test_validation_empty_card(mock_faiss, bm25_data):
    """Карта без компетенций не должна вызывать ошибку."""
    card = _make_card(ok="Не указано в документах", pk="")

    with patch("teacherfactory.validation.load_index", return_value=(mock_faiss, bm25_data)):
        result = validate_competencies(card)

    assert result == {}


def test_validation_deduplicates_codes(mock_faiss, bm25_data):
    """Один и тот же код в ОК и ПК полях не должен проверяться дважды."""
    card = _make_card(ok="ОК 01 текст ОК 01 дубль", pk="")

    with (
        patch("teacherfactory.validation.load_index", return_value=(mock_faiss, bm25_data)),
        patch("teacherfactory.validation.retrieve_context") as mock_retrieve,
    ):
        mock_retrieve.return_value = "ОК01 найдено"
        validate_competencies(card)
        assert mock_retrieve.call_count == 1


# ─── Нормализация кодов при сравнении ─────────────────────────────────────────


def test_normalize_code_strips_whitespace():
    """ОК 01 и ОК01 должны давать один и тот же ключ."""
    assert normalize_code("ОК 01") == "ОК01"
    assert normalize_code("ОК01") == "ОК01"
    assert normalize_code("ПК 1.2") == "ПК1.2"


def test_normalize_code_in_context():
    context_with_space = "В программе указаны ОК 01 и ОК 02"
    context_normalized = normalize_code(context_with_space)
    assert "ОК01" in context_normalized
