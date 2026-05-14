"""
Оркестрация RAG-генерации и чата.

Главные точки входа:
  - `generate_document(doc_type, params, ...)` — для любого `DocumentType`;
  - `stream_chat_response(question, ...)`     — потоковый чат с документами.

Пайплайн ничего не знает о конкретном типе документа: всё, что нужно,
лежит в `DocumentType` (промпт, модель, retrieval-запросы).
"""

import logging
from collections.abc import Callable, Generator
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from teacherfactory.config import CONFIG
from teacherfactory.documents.base import DocumentType
from teacherfactory.llm_provider import LLMProvider, get_llm_provider
from teacherfactory.prompts import CHAT_SYSTEM_PROMPT, HYDE_PROMPT
from teacherfactory.retrieval import (
    load_index,
    retrieve_by_specialty,
    retrieve_context,
)
from teacherfactory.text_utils import LIST_INTENT_RE, SPECIALTY_CODE_RE


def _specialty_code_from_params(params: dict) -> str | None:
    """Достаёт код специальности из параметров (поле может быть «09.01.03 ...»)."""
    raw = params.get("specialty") or ""
    m = SPECIALTY_CODE_RE.search(str(raw))
    return m.group() if m else None

log = logging.getLogger(__name__)


class _TokenCallback(BaseCallbackHandler):
    def __init__(self, on_token: Callable[[int], None]) -> None:
        self._fn = on_token
        self.count = 0

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self.count += 1
        self._fn(self.count)


def _check_required(doc_type: DocumentType[Any], params: dict) -> None:
    missing = [k for k in doc_type.required_params if k not in params]
    if missing:
        raise ValueError(
            f"Для типа документа '{doc_type.slug}' не хватает параметров: {', '.join(missing)}"
        )


def generate_document[T: BaseModel](
    doc_type: DocumentType[T],
    params: dict,
    provider: LLMProvider | None = None,
    on_token: Callable[[int], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> T:
    """
    Сгенерировать документ выбранного типа.

    doc_type   — спецификация документа (тех. карта, РПД, аттестация и т.п.).
    params     — словарь параметров; обязательные ключи объявлены в
                 `doc_type.required_params`.
    provider   — LLM-провайдер. Если None, выбирается автоматически.
    on_token   — вызывается с кол-вом токенов на каждый новый токен от LLM.
    on_stage   — вызывается с названием этапа: «index», «context», «generate».
    """
    _check_required(doc_type, params)

    def _stage(name: str) -> None:
        log.info("Этап: %s", name)
        if on_stage:
            on_stage(name)

    _stage("index")
    db, bm25_data = load_index()

    _stage("context")
    queries = doc_type.build_queries(params)
    specialty = _specialty_code_from_params(params)
    log.info(
        "Мультизапрос для '%s': %d вариантов, фильтр по специальности: %s",
        doc_type.slug,
        len(queries),
        specialty or "—",
    )
    context = retrieve_context(db, bm25_data, queries, specialty=specialty)

    _stage("generate")
    if provider is None:
        provider = get_llm_provider(temperature=CONFIG["model"]["temperature"])

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", doc_type.system_prompt),
            ("human", doc_type.user_prompt),
        ]
    )

    client = provider.get_client()
    if on_token is not None:
        client = client.bind(callbacks=[_TokenCallback(on_token)])

    chain = prompt | client.with_structured_output(doc_type.model)

    log.info(
        "Генерирую %s (провайдер: %s, модель: %s)",
        doc_type.title,
        provider.name,
        provider.config.model_name,
    )
    result: T = chain.invoke({"context": context, **params})
    log.info("Документ готов: %s", doc_type.slug)
    return result


def stream_chat_response(
    question: str,
    provider: LLMProvider | None = None,
) -> Generator[str]:
    """
    Потоковый RAG-чат по документам без генерации файлов.

    Использует HyDE (если включён в конфиге): перед поиском генерирует
    гипотетический ответ и ищет по нему — улучшает точность для
    разговорных вопросов об образовательном процессе.
    """
    if provider is None:
        provider = get_llm_provider(temperature=CONFIG["model"]["chat_temperature"])

    db, bm25_data = load_index()

    is_list_query = bool(LIST_INTENT_RE.search(question))
    specialty_match = SPECIALTY_CODE_RE.search(question)

    if specialty_match and bm25_data:
        context = retrieve_by_specialty(
            bm25_data,
            specialty_match.group(),
            extra_query=question,
            db=db,
        )
        log.info("Используется фильтрация по специальности %s", specialty_match.group())
    else:
        chat_k = CONFIG["rag"].get("chat_k", 15)
        effective_k = chat_k * 2 if is_list_query else chat_k
        if is_list_query:
            log.info("Обнаружен запрос-перечисление, увеличиваю k до %d", effective_k)

        search_query: str | list[str] = question
        if CONFIG["rag"].get("hyde_enabled", False):
            try:
                hypothetical = provider.generate(HYDE_PROMPT.format(question=question))
                search_query = [hypothetical, question]
                log.info("HyDE: сгенерирован гипотетический документ (%d симв.)", len(hypothetical))
            except Exception as e:
                log.warning("HyDE не удался, ищу по оригинальному вопросу: %s", e)

        context = retrieve_context(db, bm25_data, search_query, k=effective_k)

    messages = [
        {"role": "user", "content": f"Контекст:\n{context}\n\nВопрос: {question}"},
    ]
    yield from provider.stream_chat(messages, system_prompt=CHAT_SYSTEM_PROMPT)
