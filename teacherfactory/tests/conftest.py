"""Общие фикстуры для тестов TeacherFactory."""

from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from teacherfactory import retrieval
from teacherfactory.retrieval import BM25Index


@pytest.fixture(autouse=True)
def mock_reranker(monkeypatch):
    """Глобально отключаем CrossEncoder во всех тестах — не скачиваем модели."""
    monkeypatch.setattr(retrieval, "_get_reranker", lambda: None)
    monkeypatch.setattr(retrieval, "_reranker", None)


@pytest.fixture
def sample_docs() -> list[Document]:
    """Набор документов, имитирующих реальный РПП/РПД СПО."""
    return [
        Document(
            page_content=(
                "ОК 01 Выбирать способы решения задач профессиональной деятельности "
                "применимо к различным контекстам"
            ),
            metadata={"source": "test_rpp.pdf", "page": 5},
        ),
        Document(
            page_content=(
                "ОК 02 Использовать современные средства поиска, анализа и интерпретации "
                "информации и информационные технологии"
            ),
            metadata={"source": "test_rpp.pdf", "page": 5},
        ),
        Document(
            page_content=("ОК 04 Эффективно взаимодействовать и работать в коллективе и команде"),
            metadata={"source": "test_rpp.pdf", "page": 5},
        ),
        Document(
            page_content=(
                "ОК 05 Осуществлять устную и письменную коммуникацию на государственном "
                "языке с учётом особенностей социального и культурного контекста"
            ),
            metadata={"source": "test_rpp.pdf", "page": 6},
        ),
        Document(
            page_content=(
                "ПК 1.2 Выполнять преобразование данных, связанных с изменениями "
                "структуры документов"
            ),
            metadata={"source": "test_rpd.pdf", "page": 3},
        ),
        Document(
            page_content=("ПК 1.6 Формировать запросы для получения информации в базах данных"),
            metadata={"source": "test_rpd.pdf", "page": 3},
        ),
        Document(
            page_content=("ПК 1.7 Выполнять операции с объектами базы данных"),
            metadata={"source": "test_rpd.pdf", "page": 3},
        ),
        Document(
            page_content=(
                "Дисциплина: Базы данных. Специальность: 09.01.03 Оператор информационных "
                "систем и ресурсов. Рабочая программа дисциплины."
            ),
            metadata={"source": "test_rpd.pdf", "page": 1},
        ),
    ]


@pytest.fixture
def bm25_data(sample_docs: list[Document]) -> BM25Index:
    """BM25Index, готовый к использованию в retrieve_context / validate_competencies."""
    corpus = [doc.page_content.lower().split() for doc in sample_docs]
    return BM25Index(bm25=BM25Okapi(corpus), chunks=sample_docs)


@pytest.fixture
def mock_faiss(sample_docs: list[Document]) -> MagicMock:
    """Мок FAISS, возвращающий sample_docs при similarity_search."""
    db = MagicMock()
    db.similarity_search.return_value = sample_docs
    return db
