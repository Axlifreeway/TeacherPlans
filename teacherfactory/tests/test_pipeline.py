"""
End-to-end тесты пайплайна `generate_document`.

LLM и индекс полностью замоканы — тесты проверяют:
  - required_params реально валидируются перед запуском (иначе LLM съест
    мусор и вернёт галлюцинацию);
  - `build_queries` действительно вызывается с params;
  - `on_stage` коллбек получает все три этапа в правильном порядке;
  - результат — тот самый Pydantic-объект, который вернул LLM (тип сохраняется);
  - stream_chat_response корректно выбирает retrieve_by_specialty / retrieve_context.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from teacherfactory.documents.lesson_card import LESSON_CARD
from teacherfactory.model import LessonCard, LessonStep, LessonTasks, PlannedOutcomes, Resources
from teacherfactory.pipeline import generate_document, stream_chat_response
from teacherfactory.retrieval import BM25Index

# ─── Фикстуры ─────────────────────────────────────────────────────────────────


def _stub_lesson_card() -> LessonCard:
    """Сэмпл валидного LessonCard, как если бы его вернул LLM."""
    return LessonCard(
        lesson_number=1,
        date="08.05.2026",
        group_name="ОИСИР-21",
        students_count=25,
        discipline="Компьютерные сети",
        specialty="09.01.03 Оператор ИС",
        course_number=2,
        lesson_topic="Основы TCP/IP",
        lesson_type="комбинированный урок",
        lesson_kind="лекция",
        duration=90,
        teacher_name="Иванов И.И.",
        goal="Сформировать представление о TCP/IP",
        tasks=LessonTasks(
            educational="Изучить TCP/IP",
            developmental="Развить аналитическое мышление",
            upbringing="Воспитать ответственность",
            pedagogical="Применить проблемное обучение",
        ),
        competencies_ok="ОК 01 Выбирать способы решения задач",
        competencies_pk="ПК 1.6 Формировать запросы",
        outcomes=PlannedOutcomes(
            knowledge_indicator="знает уровни OSI",
            knowledge_control="устный опрос",
            skill_indicator="умеет настраивать IP",
            skill_control="практическая работа",
            ability_indicator="владеет утилитой ping",
            ability_control="демонстрация",
        ),
        resources=Resources(
            literature="Олифер В.Г.",
            internet_resources="rfc-editor.org",
            other_materials="ПК с Linux",
        ),
        lesson_structure=[
            LessonStep(
                number=1,
                stage="Орг. момент",
                time="5 мин",
                teacher="Приветствует",
                student="Готовятся",
                methods="Беседа",
                result="Готовы",
            ),
        ],
    )


@pytest.fixture
def valid_params() -> dict:
    """Полный набор параметров для LESSON_CARD."""
    return {
        "discipline": "Компьютерные сети",
        "specialty": "09.01.03 Оператор ИС",
        "course_number": 2,
        "group_name": "ОИСИР-21",
        "students_count": 25,
        "lesson_topic": "TCP/IP",
        "lesson_number": 1,
        "date": "08.05.2026",
        "teacher_name": "Иванов И.И.",
        "lesson_type": "комбинированный урок",
        "lesson_kind": "лекция",
        "duration": 90,
    }


@pytest.fixture
def stub_card() -> LessonCard:
    return _stub_lesson_card()


@pytest.fixture
def fake_provider(stub_card: LessonCard) -> MagicMock:
    """LLMProvider, чей клиент возвращает фиксированный LessonCard.

    Мы патчим `ChatPromptTemplate.from_messages` так, чтобы `prompt | structured`
    сводился к самому structured-клиенту (его invoke и возвращает stub).
    """
    provider = MagicMock()
    provider.name = "Fake"
    provider.config.model_name = "fake-model"

    structured = MagicMock(name="structured_client")
    structured.invoke.return_value = stub_card

    raw_client = MagicMock(name="raw_client")
    raw_client.with_structured_output.return_value = structured
    raw_client.bind.return_value = raw_client  # bind(callbacks=...) → тот же клиент

    provider.get_client.return_value = raw_client
    provider._structured = structured  # хвостик для удобных assert'ов в тестах
    return provider


@pytest.fixture
def pass_through_prompt():
    """Патч ChatPromptTemplate: `prompt | x` отдаёт x; `x.invoke(params)` вызывается напрямую."""
    fake_prompt = MagicMock(name="fake_prompt")
    fake_prompt.__or__ = lambda self, other: other
    with patch("teacherfactory.pipeline.ChatPromptTemplate") as MockTpl:
        MockTpl.from_messages.return_value = fake_prompt
        yield MockTpl


@pytest.fixture
def fake_index(sample_docs, bm25_data):
    """load_index → (faiss_mock, bm25_index)."""
    db = MagicMock()
    db.similarity_search.return_value = sample_docs
    return db, bm25_data


# ─── required_params ─────────────────────────────────────────────────────────


def test_pipeline_rejects_missing_required_params(fake_provider, fake_index):
    """Без обязательных полей пайплайн НЕ должен дёргать LLM (стоит денег / квот)."""
    with (
        patch("teacherfactory.pipeline.load_index", return_value=fake_index),
        pytest.raises(ValueError, match="не хватает параметров"),
    ):
        generate_document(LESSON_CARD, {"discipline": "X"}, provider=fake_provider)

    # И LLM не вызван — это главное.
    fake_provider.get_client.assert_not_called()


def test_pipeline_reports_all_missing_keys(fake_provider, fake_index):
    """Сообщение об ошибке должно перечислять все недостающие поля."""
    with (
        patch("teacherfactory.pipeline.load_index", return_value=fake_index),
        pytest.raises(ValueError) as exc,
    ):
        generate_document(
            LESSON_CARD,
            {"discipline": "X"},
            provider=fake_provider,
        )
    msg = str(exc.value)
    assert "specialty" in msg
    assert "lesson_topic" in msg


# ─── happy path ──────────────────────────────────────────────────────────────


def test_pipeline_calls_stages_in_order(fake_provider, fake_index, valid_params):
    """on_stage должен получить index → context → generate."""
    stages: list[str] = []
    with patch("teacherfactory.pipeline.load_index", return_value=fake_index):
        generate_document(
            LESSON_CARD,
            valid_params,
            provider=fake_provider,
            on_stage=stages.append,
        )
    assert stages == ["index", "context", "generate"]


def test_pipeline_returns_lesson_card(fake_provider, fake_index, valid_params, pass_through_prompt):
    """generate_document должен вернуть инстанс модели документа."""
    with patch("teacherfactory.pipeline.load_index", return_value=fake_index):
        result = generate_document(LESSON_CARD, valid_params, provider=fake_provider)
    assert isinstance(result, LessonCard)
    assert result.lesson_topic == "Основы TCP/IP"


def test_pipeline_passes_params_to_llm(
    fake_provider, fake_index, valid_params, pass_through_prompt
):
    """Параметры из вызова должны дойти до chain.invoke({...})."""
    with patch("teacherfactory.pipeline.load_index", return_value=fake_index):
        generate_document(LESSON_CARD, valid_params, provider=fake_provider)

    invoke_args = fake_provider._structured.invoke.call_args[0][0]
    assert invoke_args["discipline"] == "Компьютерные сети"
    assert invoke_args["lesson_topic"] == "TCP/IP"
    assert "context" in invoke_args  # retrieval-контекст подставлен


def test_pipeline_uses_doc_type_build_queries(
    fake_provider, fake_index, valid_params, pass_through_prompt
):
    """build_queries должен быть вызван с params (и не пустыми)."""
    captured: list[list[str]] = []

    def fake_retrieve(db: Any, bm25: Any, query: Any, k: int | None = None) -> str:
        captured.append(query if isinstance(query, list) else [query])
        return "stub context"

    with (
        patch("teacherfactory.pipeline.load_index", return_value=fake_index),
        patch("teacherfactory.pipeline.retrieve_context", side_effect=fake_retrieve),
    ):
        generate_document(LESSON_CARD, valid_params, provider=fake_provider)

    assert len(captured) == 1
    queries = captured[0]
    assert len(queries) >= 2
    # Хоть один запрос должен содержать дисциплину
    assert any("Компьютерные сети" in q for q in queries)


# ─── stream_chat_response ────────────────────────────────────────────────────


@pytest.fixture
def chat_provider():
    """Провайдер для чата: stream_chat возвращает заранее заданные чанки."""
    provider = MagicMock()
    provider.stream_chat.return_value = iter(["hello ", "world"])
    provider.generate.return_value = "hypothetical answer"
    return provider


def test_chat_uses_specialty_filter_when_code_present(chat_provider, fake_index):
    db, bm25 = fake_index
    with (
        patch("teacherfactory.pipeline.load_index", return_value=(db, bm25)),
        patch("teacherfactory.pipeline.retrieve_by_specialty") as mock_spec,
        patch("teacherfactory.pipeline.retrieve_context") as mock_ctx,
    ):
        mock_spec.return_value = "specialty ctx"
        list(stream_chat_response("Какие дисциплины у 09.01.03?", provider=chat_provider))

    mock_spec.assert_called_once()
    mock_ctx.assert_not_called()


def test_chat_uses_general_retrieval_for_topic_question(chat_provider, fake_index):
    db, bm25 = fake_index
    with (
        patch("teacherfactory.pipeline.load_index", return_value=(db, bm25)),
        patch("teacherfactory.pipeline.retrieve_by_specialty") as mock_spec,
        patch("teacherfactory.pipeline.retrieve_context") as mock_ctx,
    ):
        mock_ctx.return_value = "general ctx"
        list(stream_chat_response("Что такое ОК 01?", provider=chat_provider))

    mock_spec.assert_not_called()
    mock_ctx.assert_called_once()


def test_chat_yields_provider_chunks(chat_provider, fake_index):
    db, bm25 = fake_index
    with (
        patch("teacherfactory.pipeline.load_index", return_value=(db, bm25)),
        patch("teacherfactory.pipeline.retrieve_context", return_value="ctx"),
    ):
        chunks = list(stream_chat_response("Что такое ОК?", provider=chat_provider))

    assert "".join(chunks) == "hello world"


def test_chat_recovers_when_hyde_fails(chat_provider, fake_index):
    """Если HyDE-промпт провалился, чат всё равно отвечает по исходному вопросу."""
    chat_provider.generate.side_effect = RuntimeError("HyDE сломался")

    db, bm25 = fake_index
    captured_query = []

    def capture_query(_db, _bm, query, k=None):
        captured_query.append(query)
        return "ctx"

    with (
        patch("teacherfactory.pipeline.load_index", return_value=(db, bm25)),
        patch("teacherfactory.pipeline.retrieve_context", side_effect=capture_query),
        patch(
            "teacherfactory.pipeline.CONFIG",
            {
                "model": {"chat_temperature": 0.7},
                "rag": {"chat_k": 10, "hyde_enabled": True},
            },
        ),
    ):
        list(stream_chat_response("Что такое ОК?", provider=chat_provider))

    # Запрос должен быть исходным, без HyDE.
    assert captured_query == ["Что такое ОК?"]


# ─── фикстура fake_index использует sample_docs/bm25_data из conftest.py ─────


@pytest.fixture
def sample_docs():
    return [
        Document(page_content="ОК 01 Выбирать способы", metadata={"source": "t.pdf", "page": 1}),
        Document(page_content="ПК 1.2 Преобразовывать", metadata={"source": "t.pdf", "page": 2}),
    ]


@pytest.fixture
def bm25_data(sample_docs):
    corpus = [d.page_content.lower().split() for d in sample_docs]
    return BM25Index(bm25=BM25Okapi(corpus), chunks=sample_docs)
