"""
Тесты валидации компетенций:
  - регулярное выражение для извлечения кодов
  - логика проверки наличия кода в индексе
  - пограничные случаи (нет кодов, форматы написания)
"""

from unittest.mock import patch

from langchain_core.documents import Document

from teacherfactory.model import Competency
from teacherfactory.text_utils import COMPETENCY_RE, normalize_code
from teacherfactory.validation import validate_competencies
from tests.conftest import build_stub_card

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


# ─── validate_competencies (на новой модели со списком Competency) ───────────


def _card_with(*comps: Competency):
    return build_stub_card(competencies=list(comps))


def test_validation_finds_existing_code(mock_faiss, bm25_data):
    card = _card_with(Competency(code="ОК 01", name="Выбирать способы", indicator="..."))

    with patch("teacherfactory.validation.load_index", return_value=(mock_faiss, bm25_data)):
        result = validate_competencies(card)

    assert "ОК 01" in result
    assert result["ОК 01"] is True


def test_validation_flags_missing_code(mock_faiss, bm25_data):
    card = _card_with(Competency(code="ОК 99", name="Несуществующая", indicator="..."))

    mock_faiss.similarity_search.return_value = [
        Document(page_content="ОК 01 Выбирать способы решения", metadata={})
    ]

    with patch("teacherfactory.validation.load_index", return_value=(mock_faiss, bm25_data)):
        result = validate_competencies(card)

    assert "ОК 99" in result
    assert result["ОК 99"] is False


def test_validation_empty_card(mock_faiss, bm25_data):
    """Карта без компетенций не должна вызывать ошибку."""
    card = build_stub_card(competencies=[])

    with patch("teacherfactory.validation.load_index", return_value=(mock_faiss, bm25_data)):
        result = validate_competencies(card)

    assert result == {}


def test_validation_deduplicates_codes(mock_faiss, bm25_data):
    """Один и тот же код в двух разных Competency не должен проверяться дважды."""
    card = _card_with(
        Competency(code="ОК 01", name="дубль 1", indicator="..."),
        Competency(code="ОК 01", name="дубль 2", indicator="..."),
    )

    with (
        patch("teacherfactory.validation.load_index", return_value=(mock_faiss, bm25_data)),
        patch("teacherfactory.validation.retrieve_context") as mock_retrieve,
    ):
        mock_retrieve.return_value = "ОК01 найдено"
        validate_competencies(card)
        assert mock_retrieve.call_count == 1


# ─── Нормализация кодов при сравнении ─────────────────────────────────────────


def test_normalize_code_strips_whitespace():
    assert normalize_code("ОК 01") == "ОК01"
    assert normalize_code("ОК01") == "ОК01"
    assert normalize_code("ПК 1.2") == "ПК1.2"


def test_normalize_code_in_context():
    context_with_space = "В программе указаны ОК 01 и ОК 02"
    context_normalized = normalize_code(context_with_space)
    assert "ОК01" in context_normalized
