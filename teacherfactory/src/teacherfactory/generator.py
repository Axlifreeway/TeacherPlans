"""
Генератор технологических карт уроков.

Пайплайн: гибридный RAG-поиск (FAISS + BM25 → RRF) → LLM-генерация → DOCX-рендеринг.

Запуск: poetry run python src/teacherfactory/generator.py
"""

import logging
import pickle
from collections.abc import Generator
from pathlib import Path

from docxtpl import DocxTemplate
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama, OllamaEmbeddings

from config import CONFIG
from model import LessonCard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
INDEX_DIR = Path.home() / ".teacherfactory" / "faiss_index"
BM25_PATH = INDEX_DIR / "bm25.pkl"
TEMPLATE_PATH = PROJECT_ROOT / "template_fixed.docx"
OUTPUT_DIR = Path.home() / ".teacherfactory" / "output"


SYSTEM_PROMPT = """Ты — опытный методист среднего профессионального образования (СПО) в России.
Твоя задача — составить технологическую карту урока строго на русском языке.

Используй ТОЛЬКО информацию из предоставленного контекста нормативных документов.
Компетенции (ОК, ПК), знания, умения и навыки бери ТОЛЬКО из контекста.
Не выдумывай коды компетенций — если в контексте нет нужной информации, напиши "Не указано в документах".

КОНТЕКСТ ИЗ НОРМАТИВНЫХ ДОКУМЕНТОВ:
{context}
"""

USER_PROMPT = """Составь технологическую карту урока со следующими параметрами:

Дисциплина: {discipline}
Специальность: {specialty}
Курс: {course_number}
Группа: {group_name}
Количество студентов: {students_count}
Тема занятия: {lesson_topic}
Номер занятия: {lesson_number}
Дата: {date}
Преподаватель: {teacher_name}
Тип урока: {lesson_type}
Вид занятия: {lesson_kind}
Продолжительность: {duration} минут

Включи 5-7 этапов в ход занятия. Все тексты — на русском языке.
"""

CHAT_SYSTEM_PROMPT = """Ты — помощник методиста СПО в России.
Отвечай на вопросы об образовательном процессе, компетенциях, программах обучения,
используя ТОЛЬКО информацию из предоставленного контекста нормативных документов.
Если в контексте нет ответа — честно скажи об этом.
Отвечай развёрнуто и по существу, на русском языке.

КОНТЕКСТ ИЗ НОРМАТИВНЫХ ДОКУМЕНТОВ:
{context}
"""


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def load_index() -> tuple[FAISS, dict | None]:
    """Загрузить FAISS и (если есть) BM25 индекс."""
    if not INDEX_DIR.exists() or not any(INDEX_DIR.iterdir()):
        raise FileNotFoundError(
            f"FAISS-индекс не найден в {INDEX_DIR}. "
            "Сначала запусти indexer.py: poetry run python src/teacherfactory/indexer.py"
        )
    embeddings = OllamaEmbeddings(model=CONFIG["model"]["embeddings"])
    db = FAISS.load_local(str(INDEX_DIR), embeddings, allow_dangerous_deserialization=True)

    bm25_data = None
    if BM25_PATH.exists():
        with open(BM25_PATH, "rb") as f:
            bm25_data = pickle.load(f)
        log.info("BM25-индекс загружен (%d чанков)", len(bm25_data["chunks"]))
    else:
        log.warning("BM25-индекс не найден — используется только FAISS. Перестройте индекс.")

    return db, bm25_data


def retrieve_context(db: FAISS, bm25_data: dict | None, query: str, k: int | None = None) -> str:
    """
    Гибридный поиск: FAISS (dense) + BM25 (sparse), слияние через RRF.

    BM25 критичен для точного поиска кодов компетенций (ОК-1, ПК-3),
    где семантический поиск может промахнуться.
    """
    if k is None:
        k = CONFIG["rag"]["retrieval_k"]

    dense_docs = db.similarity_search(query, k=k * 2)

    if bm25_data is not None:
        tokens = _tokenize(query)
        scores = bm25_data["bm25"].get_scores(tokens)
        chunks: list[Document] = bm25_data["chunks"]
        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[: k * 2]
        sparse_docs = [chunks[i] for i in top_idx]
    else:
        sparse_docs = []

    # RRF fusion (K=60 — стандартная константа)
    K_RRF = 60
    score_map: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for rank, doc in enumerate(dense_docs):
        key = doc.page_content[:120]
        score_map[key] = score_map.get(key, 0.0) + 1.0 / (K_RRF + rank + 1)
        doc_map[key] = doc

    for rank, doc in enumerate(sparse_docs):
        key = doc.page_content[:120]
        score_map[key] = score_map.get(key, 0.0) + 1.0 / (K_RRF + rank + 1)
        doc_map[key] = doc

    top_keys = sorted(score_map, key=score_map.__getitem__, reverse=True)[:k]
    top_docs = [doc_map[key] for key in top_keys]

    log.info(
        "Найдено %d чанков (dense=%d, sparse=%d)",
        len(top_docs), len(dense_docs), len(sparse_docs),
    )

    context_parts = []
    for doc in top_docs:
        source = Path(doc.metadata.get("source", "неизвестно")).name
        page = doc.metadata.get("page", "?")
        context_parts.append(f"[Источник: {source}, стр. {page}]\n{doc.page_content}")

    return "\n\n---\n\n".join(context_parts)


def generate_lesson_card(params: dict) -> LessonCard:
    """
    Сгенерировать технологическую карту урока.

    params — словарь с параметрами урока:
        discipline, specialty, course_number, group_name, students_count,
        lesson_topic, lesson_number, date, teacher_name,
        lesson_type, lesson_kind, duration
    """
    log.info("Загружаю индекс...")
    db, bm25_data = load_index()

    search_query = f"{params['discipline']} {params['specialty']} компетенции знания умения навыки"
    log.info("Запрос: %s", search_query[:80])
    context = retrieve_context(db, bm25_data, search_query)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT),
    ])

    llm = ChatOllama(
        model=CONFIG["model"]["llm"],
        temperature=CONFIG["model"]["temperature"],
        num_gpu=CONFIG["model"]["num_gpu"],
    )
    chain = prompt | llm.with_structured_output(LessonCard)

    log.info("Генерирую карту для темы: %s (модель: %s)", params["lesson_topic"], CONFIG["model"]["llm"])
    result = chain.invoke({"context": context, **params})
    log.info("Карта готова: %s", result.lesson_topic)
    return result


def stream_chat_response(question: str) -> Generator[str, None, None]:
    """
    Потоковый RAG-чат по документам без генерации файлов.

    Полезен для вопросов об образовательном процессе, компетенциях,
    программах обучения — не требует создания технологической карты.
    """
    db, bm25_data = load_index()
    context = retrieve_context(db, bm25_data, question)

    prompt = ChatPromptTemplate.from_messages([
        ("system", CHAT_SYSTEM_PROMPT),
        ("human", "{question}"),
    ])

    llm = ChatOllama(
        model=CONFIG["model"]["llm"],
        temperature=CONFIG["model"]["chat_temperature"],
        num_gpu=CONFIG["model"]["num_gpu"],
    )
    chain = prompt | llm

    for chunk in chain.stream({"context": context, "question": question}):
        yield chunk.content


def render_docx(card: LessonCard, output_path: Path) -> Path:
    """Отрендерить технологическую карту в DOCX через шаблон."""
    doc = DocxTemplate(str(TEMPLATE_PATH))
    context = card.to_template_context()

    try:
        doc.render(context)
    except Exception as e:
        log.warning("Предупреждение при рендеринге: %s — пробую без таблицы хода", e)
        context_safe = {**context, "lesson_structure": []}
        doc = DocxTemplate(str(TEMPLATE_PATH))
        doc.render(context_safe)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    log.info("Документ сохранён: %s", output_path)
    return output_path


def main():
    """Пример генерации одной карты."""
    params = {
        "discipline": "Компьютерные сети",
        "specialty": "09.01.03 Оператор информационных систем и ресурсов",
        "course_number": 2,
        "group_name": "ОИСИР-21",
        "students_count": 25,
        "lesson_topic": "Основы сетевых протоколов",
        "lesson_number": 1,
        "date": "08.05.2026",
        "teacher_name": "Иванов И.И.",
        "lesson_type": "комбинированный урок",
        "lesson_kind": "лекция",
        "duration": 90,
    }

    try:
        card = generate_lesson_card(params)
        output_file = OUTPUT_DIR / f"Урок_{params['lesson_number']}_{params['discipline']}.docx"
        render_docx(card, output_file)

        print(f"\nТема: {card.lesson_topic}")
        print(f"Цель: {card.goal}")
        print(f"ОК: {card.competencies_ok}")
        print(f"ПК: {card.competencies_pk}")
        print(f"Этапов: {len(card.lesson_structure)}")
        for step in card.lesson_structure:
            print(f"  {step.number}. {step.stage} ({step.time})")

    except Exception as e:
        log.error("Ошибка: %s", e)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
