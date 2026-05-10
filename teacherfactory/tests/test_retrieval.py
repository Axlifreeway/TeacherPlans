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
