"""
Тесты пайплайна retrieval:
  - токенизация
  - RRF-слияние
  - мультизапрос
  - интеграция с reranker (мок)
"""

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from teacherfactory.documents.lesson_card import build_lesson_queries
from teacherfactory.retrieval import retrieve_by_specialty, retrieve_context
from teacherfactory.text_utils import LIST_INTENT_RE, tokenize

# ─── tokenize ────────────────────────────────────────────────────────────────


def test_tokenize_basic():
    assert tokenize("Общие компетенции ОК") == ["общие", "компетенции", "ок"]


def test_tokenize_empty():
    assert tokenize("") == []


def test_tokenize_preserves_numbers():
    tokens = tokenize("ПК 1.2 Выполнять преобразование")
    assert "пк" in tokens
    assert "1.2" in tokens


def test_tokenize_normalizes_compact_codes():
    """ОК01 и ОК 01 должны давать одинаковые токены."""
    assert tokenize("ОК01") == tokenize("ОК 01")
    assert tokenize("ПК1.2") == tokenize("ПК 1.2")


# ─── retrieve_context ────────────────────────────────────────────────────────


def test_retrieve_context_returns_string(mock_faiss, bm25_data):
    """retrieve_context должна вернуть непустую строку с источниками."""
    result = retrieve_context(mock_faiss, bm25_data, "компетенции ОК", k=3)
    assert isinstance(result, str)
    assert len(result) > 0


def test_retrieve_context_includes_source(mock_faiss, bm25_data):
    """Результат должен содержать атрибуцию источника."""
    result = retrieve_context(mock_faiss, bm25_data, "ПК 1.6", k=3)
    assert "[Источник:" in result


def test_retrieve_context_multi_query(mock_faiss, bm25_data):
    """Мультизапрос не должен падать и должен вернуть результат."""
    queries = ["ПК профессиональные компетенции", "ОК общие компетенции"]
    result = retrieve_context(mock_faiss, bm25_data, queries, k=3)
    assert isinstance(result, str)
    assert len(result) > 0


def test_retrieve_context_deduplicates(sample_docs):
    """Одинаковые документы из разных запросов не должны дублироваться."""
    db = MagicMock()
    db.similarity_search.return_value = sample_docs[:3]

    corpus = [d.page_content.lower().split() for d in sample_docs[:3]]
    from teacherfactory.retrieval import BM25Index

    bm25_data = BM25Index(bm25=BM25Okapi(corpus), chunks=sample_docs[:3])

    queries = ["запрос один", "запрос два", "запрос три"]
    result = retrieve_context(db, bm25_data, queries, k=3)

    chunks_in_result = [s.strip() for s in result.split("---") if s.strip()]
    assert len(chunks_in_result) == len(set(chunks_in_result)), "Дублирующиеся чанки в результате"


def test_retrieve_context_no_bm25(mock_faiss):
    """Должно работать без BM25 (только FAISS)."""
    result = retrieve_context(mock_faiss, None, "тест", k=3)
    assert isinstance(result, str)


def test_retrieve_context_respects_k(mock_faiss, bm25_data):
    """Результат не должен содержать больше k чанков."""
    with patch("teacherfactory.retrieval._get_reranker", return_value=None):
        result = retrieve_context(mock_faiss, bm25_data, "компетенции", k=2)

    count = result.count("[Источник:")
    assert count <= 2


# ─── build_lesson_queries ────────────────────────────────────────────────────


def test_lesson_queries_count():
    queries = build_lesson_queries(
        {"discipline": "Базы данных", "specialty": "09.01.03 Оператор ИС"}
    )
    assert len(queries) >= 2


def test_lesson_queries_contain_discipline():
    queries = build_lesson_queries({"discipline": "Базы данных", "specialty": "09.01.03"})
    assert any("Базы данных" in q for q in queries)


def test_lesson_queries_contain_competency_terms():
    queries = build_lesson_queries({"discipline": "Компьютерные сети", "specialty": "09.01.03"})
    all_text = " ".join(queries).lower()
    assert "компетенци" in all_text


# ─── retrieve_by_specialty ───────────────────────────────────────────────────


def test_retrieve_by_specialty_filters_by_code():
    """Должны вернуться чанки из файлов с кодом специальности в имени."""
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
    from teacherfactory.retrieval import BM25Index

    corpus = [d.page_content.lower().split() for d in specialty_docs]
    bm25 = BM25Index(bm25=BM25Okapi(corpus), chunks=specialty_docs)

    db = MagicMock()
    db.similarity_search.return_value = []

    result = retrieve_by_specialty(bm25, "09.01.03", "компетенции", db, k=50)
    assert "ОК 01" in result
    assert "ПК 1.2" in result
    assert "10.02.05" not in result


def test_list_intent_regex():
    """Проверяем что паттерн ловит перечислительные запросы."""
    assert LIST_INTENT_RE.search("Перечисли все ОК")
    assert LIST_INTENT_RE.search("список компетенций")
    assert LIST_INTENT_RE.search("какие дисциплины у направления")
    assert not LIST_INTENT_RE.search("что такое ОК 01")
