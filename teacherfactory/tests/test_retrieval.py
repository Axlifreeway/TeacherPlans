"""
Тесты пайплайна retrieval:
  - токенизация
  - RRF-слияние
  - мультизапрос
  - интеграция с reranker (мок)
"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document


# ─── _tokenize ────────────────────────────────────────────────────────────────

def test_tokenize_basic():
    from generator import _tokenize
    assert _tokenize("Общие компетенции ОК") == ["общие", "компетенции", "ок"]


def test_tokenize_empty():
    from generator import _tokenize
    assert _tokenize("") == []


def test_tokenize_preserves_numbers():
    from generator import _tokenize
    tokens = _tokenize("ПК 1.2 Выполнять преобразование")
    assert "пк" in tokens
    assert "1.2" in tokens


def test_tokenize_normalizes_compact_codes():
    """ОК01 и ОК 01 должны давать одинаковые токены."""
    from generator import _tokenize
    assert _tokenize("ОК01") == _tokenize("ОК 01")
    assert _tokenize("ПК1.2") == _tokenize("ПК 1.2")


# ─── RRF-слияние (через retrieve_context с моками) ────────────────────────────

def test_retrieve_context_returns_string(mock_faiss, bm25_data):
    """retrieve_context должна вернуть непустую строку с источниками."""
    from generator import retrieve_context
    result = retrieve_context(mock_faiss, bm25_data, "компетенции ОК", k=3)
    assert isinstance(result, str)
    assert len(result) > 0


def test_retrieve_context_includes_source(mock_faiss, bm25_data):
    """Результат должен содержать атрибуцию источника."""
    from generator import retrieve_context
    result = retrieve_context(mock_faiss, bm25_data, "ПК 1.6", k=3)
    assert "[Источник:" in result


def test_retrieve_context_multi_query(mock_faiss, bm25_data):
    """Мультизапрос не должен падать и должен вернуть результат."""
    from generator import retrieve_context
    queries = ["ПК профессиональные компетенции", "ОК общие компетенции"]
    result = retrieve_context(mock_faiss, bm25_data, queries, k=3)
    assert isinstance(result, str)
    assert len(result) > 0


def test_retrieve_context_deduplicates(sample_docs):
    """Одинаковые документы из разных запросов не должны дублироваться."""
    from generator import retrieve_context

    # FAISS всегда возвращает одни и те же 3 документа для любого запроса
    db = MagicMock()
    db.similarity_search.return_value = sample_docs[:3]

    from rank_bm25 import BM25Okapi
    corpus = [d.page_content.lower().split() for d in sample_docs[:3]]
    bm25_data = {"bm25": BM25Okapi(corpus), "chunks": sample_docs[:3]}

    queries = ["запрос один", "запрос два", "запрос три"]
    result = retrieve_context(db, bm25_data, queries, k=3)

    # Проверяем что каждый чанк присутствует ровно один раз (по содержимому)
    chunks_in_result = [s.strip() for s in result.split("---") if s.strip()]
    assert len(chunks_in_result) == len(set(chunks_in_result)), "Дублирующиеся чанки в результате"


def test_retrieve_context_no_bm25(mock_faiss):
    """Должно работать без BM25 (только FAISS)."""
    from generator import retrieve_context
    result = retrieve_context(mock_faiss, None, "тест", k=3)
    assert isinstance(result, str)


def test_retrieve_context_respects_k(mock_faiss, bm25_data):
    """Результат не должен содержать больше k чанков."""
    from generator import retrieve_context

    with patch("generator._get_reranker", return_value=None):
        result = retrieve_context(mock_faiss, bm25_data, "компетенции", k=2)

    count = result.count("[Источник:")
    assert count <= 2


# ─── lesson search queries ────────────────────────────────────────────────────

def test_lesson_search_queries_count():
    from generator import _lesson_search_queries
    queries = _lesson_search_queries("Базы данных", "09.01.03 Оператор ИС")
    assert len(queries) >= 2


def test_lesson_search_queries_contain_discipline():
    from generator import _lesson_search_queries
    queries = _lesson_search_queries("Базы данных", "09.01.03")
    assert any("Базы данных" in q for q in queries)


def test_lesson_search_queries_contain_competency_terms():
    from generator import _lesson_search_queries
    queries = _lesson_search_queries("Компьютерные сети", "09.01.03")
    all_text = " ".join(queries).lower()
    assert "компетенци" in all_text


# ─── _retrieve_by_specialty ───────────────────────────────────────────────────

def test_retrieve_by_specialty_filters_by_code(sample_docs):
    """Должны вернуться чанки из файлов с кодом специальности в имени."""
    from generator import _retrieve_by_specialty
    from unittest.mock import MagicMock

    # Добавляем чанк с явным кодом специальности в источнике
    from langchain_core.documents import Document
    specialty_docs = [
        Document(
            page_content="ОК 01 Выбирать способы решения задач",
            metadata={"source": "/docs/KII_RPP_09.01.03_program.pdf", "page": 5},
        ),
        Document(
            page_content="ПК 1.2 Выполнять преобразование данных",
            metadata={"source": "/docs/KII_RPP_09.01.03_program.pdf", "page": 6},
        ),
        Document(
            page_content="Дисциплина: Компьютерные сети. Специальность 10.02.05",
            metadata={"source": "/docs/KII_RPD_10.02.05_OIBAS.pdf", "page": 1},
        ),
    ]
    from rank_bm25 import BM25Okapi
    corpus = [d.page_content.lower().split() for d in specialty_docs]
    bm25 = {"bm25": BM25Okapi(corpus), "chunks": specialty_docs}

    db = MagicMock()
    db.similarity_search.return_value = []

    result = _retrieve_by_specialty(bm25, "09.01.03", "компетенции", db, k=50)
    # Должны попасть чанки из 09.01.03, но не из 10.02.05
    assert "ОК 01" in result
    assert "ПК 1.2" in result
    assert "10.02.05" not in result


def test_list_intent_regex():
    """Проверяем что паттерн ловит перечислительные запросы."""
    from generator import _LIST_INTENT_RE
    assert _LIST_INTENT_RE.search("Перечисли все ОК")
    assert _LIST_INTENT_RE.search("список компетенций")
    assert _LIST_INTENT_RE.search("какие дисциплины у направления")
    assert not _LIST_INTENT_RE.search("что такое ОК 01")
