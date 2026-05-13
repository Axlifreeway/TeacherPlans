"""Общие фикстуры для тестов TeacherFactory."""

from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from teacherfactory import retrieval
from teacherfactory.model import (
    Competency,
    InterdisciplinaryConnection,
    LearningOutcome,
    LessonCard,
    LessonStep,
    LessonTasks,
    Resources,
    TeachingMethodsTable,
)
from teacherfactory.retrieval import BM25Index


def build_stub_card(**overrides) -> LessonCard:
    """Готовый LessonCard под новый Эталон. Любое поле можно переопределить."""
    base = dict(
        discipline="Тестовая дисциплина",
        specialty="09.01.03 Оператор ИС",
        course_number=2,
        group_name="TEST-21",
        students_count=20,
        lesson_topic="Тестовая тема",
        duration=90,
        teacher_name="Тестов Т.Т.",
        lesson_type="Урок изучения нового материала",
        lesson_kind="лекция",
        pedagogical_technologies="ИКТ, контекстное обучение",
        goal="Сформировать тестовое умение",
        tasks=LessonTasks(
            educational="образ. задача 1; образ. задача 2",
            developmental="разв. задача 1",
            upbringing="воспит. задача 1",
            perspective="перспект. задача",
            personal="личностная задача",
        ),
        epigraph="Тест — это путь к истине.",
        epigraph_author="Тестов",
        organization_forms=["групповая", "индивидуальная"],
        teaching_techniques=["приём 1", "приём 2"],
        methodological_support=["методичка"],
        teaching_means="Компьютер, проектор",
        learning_outcomes=[
            LearningOutcome(type="Знания", code="З-1", name="знание 1", indicator="индикатор 1"),
            LearningOutcome(type="Умения", code="У-1", name="умение 1", indicator="индикатор 2"),
        ],
        competencies=[
            Competency(code="ОК 01", name="Выбирать способы", indicator="показатель 1"),
            Competency(code="ПК 1.2", name="Преобразование данных", indicator="показатель 2"),
        ],
        interdisciplinary_connections=[
            InterdisciplinaryConnection(
                outcome_source="З-2 связь",
                discipline="Смежная дисциплина",
                topic="Тема 1.1",
                outcome_target="Целевой результат",
                indicator="показатель межсвязи",
            ),
        ],
        teaching_methods_table=TeachingMethodsTable(
            by_source="Словесные: беседа",
            by_character="Проблемные: целеполагание",
            by_independence="Индивидуальная работа",
            health_saving="Физкультминутка",
        ),
        lesson_structure=[
            LessonStep(
                number=1, stage="Орг", substage="орг", time="5",
                tasks="организовать", result="готовы", methods="беседа",
                means="слово", teacher="приветствует", student="приветствуют",
                control="осмотр",
            ),
            LessonStep(
                number=2, stage="Основной", substage="изучение", time="40",
                tasks="изучить тему", result="изучили", methods="объяснение",
                means="проектор", teacher="объясняет", student="конспектируют",
                control="опрос",
            ),
        ],
        resources=Resources(
            literature_main=["Учебник 1"],
            literature_additional=["Доп. пособие"],
            databases=["БД 1"],
            normative_docs=["ГОСТ 1"],
            software=["ПО 1"],
            internet_resources=["url 1"],
        ),
    )
    base.update(overrides)
    return LessonCard(**base)


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
