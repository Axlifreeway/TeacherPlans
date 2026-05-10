"""
Генератор технологических карт уроков.

Пайплайн:
  1. Мультизапросный гибридный поиск (FAISS + BM25 → RRF)
  2. Cross-encoder reranking
  3. LLM-генерация со структурированным выводом
  4. Валидация компетенций по индексу
  5. DOCX-рендеринг

Для чата используется HyDE: перед поиском генерируется гипотетический
ответ, что улучшает точность для разговорных запросов.

Запуск: poetry run python src/teacherfactory/generator.py
"""

import logging
import pickle
import re
from collections.abc import Callable, Generator
from pathlib import Path

from docxtpl import DocxTemplate
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama, OllamaEmbeddings
from sentence_transformers import CrossEncoder

from config import CONFIG
from model import LessonCard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
INDEX_DIR = Path.home() / ".teacherfactory" / "faiss_index"
BM25_PATH = INDEX_DIR / "bm25.pkl"
TEMPLATE_PATH = PROJECT_ROOT / "template_fixed.docx"
OUTPUT_DIR = Path.home() / ".teacherfactory" / "output"

# Паттерн для кодов компетенций: ОК 01, ПК 1.2, ОК01 и т.п.
COMPETENCY_RE = re.compile(r'(?:ОК|ПК)\s*\d+(?:\.\d+)*')


# ─── Промпты ──────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ты — опытный методист среднего профессионального образования (СПО) в России.
Твоя задача — составить технологическую карту урока строго на русском языке.

Используй ТОЛЬКО информацию из предоставленного контекста нормативных документов.

ПРАВИЛА ДЛЯ КОМПЕТЕНЦИЙ (критически важно):
- Перечисли ВСЕ компетенции из контекста, не сокращай список
- Сохраняй ТОЧНЫЕ коды и формулировки из документа (пример: «ОК 01 Выбирать способы...»)
- Формат кода должен точно совпадать с документом (если в документе «ОК 01» — пиши «ОК 01», не «ОК-1»)
- Если компетенции для данной дисциплины в контексте не найдены — напиши «Не указано в документах»
- НЕ выдумывай коды, которых нет в контексте

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

Пример хорошо заполненного этапа:
{{
  "number": 1,
  "stage": "Организационный момент",
  "time": "5 мин",
  "teacher": "Приветствует студентов, проверяет готовность к занятию, отмечает отсутствующих",
  "student": "Приветствуют преподавателя, подготавливают рабочие места",
  "methods": "Фронтальная беседа",
  "result": "Готовность группы к занятию"
}}
"""

CHAT_SYSTEM_PROMPT = """Ты — помощник методиста среднего профессионального образования (СПО) в России.
Отвечай на вопросы об образовательном процессе, учебных программах и нормативных требованиях,
используя ТОЛЬКО информацию из предоставленного контекста документов.
Если в контексте нет ответа — честно скажи об этом, не додумывай.
Отвечай развёрнуто и по существу, на русском языке.

ВАЖНО — расшифровка аббревиатур в контексте СПО:
- ОК — общие компетенции (не «одноклассники» и не что-то другое)
- ПК — профессиональные компетенции (НЕ персональный компьютер)
- РПП — рабочая программа профессии
- РПД — рабочая программа дисциплины
- МДК — междисциплинарный курс
- ФГОС — федеральный государственный образовательный стандарт
Когда пользователь спрашивает «ПК», «все ПК», «список ПК» — он имеет в виду
профессиональные компетенции из учебной программы, а не компьютеры.

КОНТЕКСТ ИЗ НОРМАТИВНЫХ ДОКУМЕНТОВ:
{context}
"""

HYDE_PROMPT = """Напиши 3-4 предложения из нормативного документа СПО, \
которые содержат ответ на вопрос: {question}
Пиши как официальный нормативный документ (не как ответ на вопрос, \
а как фрагмент учебной программы или стандарта)."""


# ─── Кеш reranker ─────────────────────────────────────────────────────────────

_reranker: CrossEncoder | None = None


def _get_reranker() -> CrossEncoder | None:
    model_name = CONFIG["rag"].get("reranker_model")
    if not model_name:
        return None
    global _reranker
    if _reranker is None:
        log.info("Загружаю reranker: %s", model_name)
        _reranker = CrossEncoder(model_name)
    return _reranker


# ─── Callback для подсчёта токенов ────────────────────────────────────────────

class _TokenCallback(BaseCallbackHandler):
    def __init__(self, on_token: Callable[[int], None]) -> None:
        self._fn = on_token
        self.count = 0

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self.count += 1
        self._fn(self.count)


# ─── Утилиты ──────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def _make_llm(temperature: float | None = None, streaming: bool = False,
              callbacks: list | None = None) -> ChatOllama:
    return ChatOllama(
        model=CONFIG["model"]["llm"],
        temperature=temperature if temperature is not None else CONFIG["model"]["temperature"],
        num_gpu=CONFIG["model"]["num_gpu"],
        keep_alive=CONFIG["model"].get("keep_alive", "5m"),
        streaming=streaming,
        callbacks=callbacks or [],
    )


def _lesson_search_queries(discipline: str, specialty: str) -> list[str]:
    """Несколько вариантов запроса для лучшего покрытия документа."""
    return [
        f"{discipline} {specialty} компетенции знания умения навыки",
        f"профессиональные компетенции ПК {discipline}",
        f"общие компетенции ОК {specialty}",
        f"{discipline} результаты освоения рабочая программа",
    ]


# ─── Загрузка индекса ─────────────────────────────────────────────────────────

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


# ─── Retrieval ────────────────────────────────────────────────────────────────

def retrieve_context(
    db: FAISS,
    bm25_data: dict | None,
    query: str | list[str],
    k: int | None = None,
) -> str:
    """
    Трёхступенчатый поиск: FAISS + BM25 → RRF → cross-encoder reranking.

    query может быть строкой или списком строк (мультизапрос).
    При мультизапросе результаты по всем запросам объединяются через RRF,
    что улучшает покрытие документа.
    """
    if k is None:
        k = CONFIG["rag"]["retrieval_k"]

    queries = [query] if isinstance(query, str) else query
    candidates = CONFIG["rag"].get("retrieval_candidates", k * 4)
    per_query = max(candidates // len(queries), k)

    # Собираем кандидатов из всех запросов
    K_RRF = 60
    score_map: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for q in queries:
        dense = db.similarity_search(q, k=per_query)

        if bm25_data is not None:
            tokens = _tokenize(q)
            bm25_scores = bm25_data["bm25"].get_scores(tokens)
            chunks: list[Document] = bm25_data["chunks"]
            top_idx = sorted(
                range(len(bm25_scores)),
                key=lambda i: bm25_scores[i],
                reverse=True,
            )[:per_query]
            sparse = [chunks[i] for i in top_idx]
        else:
            sparse = []

        for rank, doc in enumerate(dense):
            key = doc.page_content[:120]
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (K_RRF + rank + 1)
            doc_map[key] = doc

        for rank, doc in enumerate(sparse):
            key = doc.page_content[:120]
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (K_RRF + rank + 1)
            doc_map[key] = doc

    rrf_top = sorted(score_map, key=score_map.__getitem__, reverse=True)[:candidates]
    candidate_docs = [doc_map[key] for key in rrf_top]

    # Cross-encoder reranking — оцениваем по первому (основному) запросу
    primary_query = queries[0] if isinstance(queries[0], str) else queries[0]
    reranker = _get_reranker()
    if reranker and len(candidate_docs) > k:
        pairs = [(primary_query, doc.page_content) for doc in candidate_docs]
        rerank_scores = reranker.predict(pairs)
        ranked = sorted(zip(rerank_scores, candidate_docs), key=lambda x: x[0], reverse=True)
        top_docs = [doc for _, doc in ranked[:k]]
        log.info("Reranking: %d кандидатов → топ-%d", len(candidate_docs), k)
    else:
        top_docs = candidate_docs[:k]

    context_parts = []
    for doc in top_docs:
        source = Path(doc.metadata.get("source", "неизвестно")).name
        page = doc.metadata.get("page", "?")
        context_parts.append(f"[Источник: {source}, стр. {page}]\n{doc.page_content}")

    return "\n\n---\n\n".join(context_parts)


# ─── Валидация компетенций ────────────────────────────────────────────────────

def validate_competencies(card: LessonCard) -> dict[str, bool]:
    """
    Проверяет наличие кодов компетенций из карты в индексированных документах.

    Возвращает {код: найден_ли_в_документах}.
    Коды которых нет в индексе — скорее всего выдуманы LLM.
    """
    db, bm25_data = load_index()
    all_text = f"{card.competencies_ok} {card.competencies_pk}"
    codes = list(set(COMPETENCY_RE.findall(all_text)))

    if not codes:
        return {}

    results: dict[str, bool] = {}
    for code in codes:
        context = retrieve_context(db, bm25_data, code, k=3)
        normalized_code = re.sub(r"\s+", "", code)
        normalized_ctx = re.sub(r"\s+", "", context)
        found = normalized_code in normalized_ctx
        results[code] = found
        log.info("Компетенция %s: %s", code, "найдена" if found else "НЕ НАЙДЕНА в документах")

    return results


# ─── Основная генерация ───────────────────────────────────────────────────────

def generate_lesson_card(
    params: dict,
    on_token: Callable[[int], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> LessonCard:
    """
    Сгенерировать технологическую карту урока.

    params     — параметры урока (discipline, specialty, ...)
    on_token   — вызывается с кол-вом токенов на каждый новый токен от LLM
    on_stage   — вызывается с названием этапа: "index", "context", "generate"
    """
    def _stage(name: str) -> None:
        log.info("Этап: %s", name)
        if on_stage:
            on_stage(name)

    _stage("index")
    db, bm25_data = load_index()

    _stage("context")
    queries = _lesson_search_queries(params["discipline"], params["specialty"])
    log.info("Мультизапрос: %d вариантов", len(queries))
    context = retrieve_context(db, bm25_data, queries)

    _stage("generate")
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT),
    ])

    callbacks = [_TokenCallback(on_token)] if on_token else []
    llm = _make_llm(streaming=True, callbacks=callbacks)
    chain = prompt | llm.with_structured_output(LessonCard)

    log.info("Генерирую карту: %s (модель: %s)", params["lesson_topic"], CONFIG["model"]["llm"])
    result = chain.invoke({"context": context, **params})
    log.info("Карта готова: %s", result.lesson_topic)
    return result


# ─── Чат с документами ────────────────────────────────────────────────────────

def stream_chat_response(question: str) -> Generator[str, None, None]:
    """
    Потоковый RAG-чат по документам без генерации файлов.

    Использует HyDE (если включён в конфиге): перед поиском генерирует
    гипотетический ответ и ищет по нему — улучшает точность для
    разговорных вопросов об образовательном процессе.
    """
    db, bm25_data = load_index()
    llm = _make_llm(temperature=CONFIG["model"]["chat_temperature"])

    # HyDE: генерируем гипотетический документ для лучшего поиска
    search_query: str | list[str] = question
    if CONFIG["rag"].get("hyde_enabled", False):
        try:
            hyde_prompt = HYDE_PROMPT.format(question=question)
            hypothetical = llm.invoke(hyde_prompt).content
            # Ищем по обоим: HyDE-документ даёт семантику, оригинал — ключевые слова
            search_query = [hypothetical, question]
            log.info("HyDE: сгенерирован гипотетический документ (%d симв.)", len(hypothetical))
        except Exception as e:
            log.warning("HyDE не удался, ищу по оригинальному вопросу: %s", e)

    context = retrieve_context(db, bm25_data, search_query, k=10)

    prompt = ChatPromptTemplate.from_messages([
        ("system", CHAT_SYSTEM_PROMPT),
        ("human", "{question}"),
    ])
    chain = prompt | _make_llm(temperature=CONFIG["model"]["chat_temperature"])

    for chunk in chain.stream({"context": context, "question": question}):
        yield chunk.content


# ─── Рендеринг DOCX ───────────────────────────────────────────────────────────

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

        validation = validate_competencies(card)
        print("\nВалидация компетенций:")
        for code, found in validation.items():
            print(f"  {'✓' if found else '✗'} {code}")

    except Exception as e:
        log.error("Ошибка: %s", e)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
