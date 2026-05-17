"""
Извлечение тематического плана дисциплины из проиндексированных РПД.

Идея: пользователь указывает только дисциплину/специальность и диапазон
номеров занятий (с N по M) — мы достаём из RAG-индекса кусок «Тематический
план» соответствующей РПД и просим LLM распарсить его в структуру
`TopicPlan` (Pydantic, через with_structured_output).

Отдельный модуль, а не часть `documents/`, потому что это вспомогательный
запрос к LLM, не генерация документа в шаблоне.
"""

from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from teacherfactory.config import CONFIG
from teacherfactory.llm_provider import LLMProvider, get_llm_provider
from teacherfactory.retrieval import load_index, retrieve_context
from teacherfactory.text_utils import SPECIALTY_CODE_RE

log = logging.getLogger(__name__)


class TopicPlanItem(BaseModel):
    """Один пункт тематического плана."""

    number: int = Field(
        description="Сквозной порядковый номер занятия (1, 2, 3, ...). "
        "Если в РПД нумерация в формате '1.1', '1.2' — пронумеруй сквозным "
        "счётчиком по порядку появления."
    )
    title: str = Field(
        description="Точное название темы / занятия из тематического плана РПД. "
        "Без сокращений и переформулировок."
    )
    section: str = Field(
        default="",
        description="Раздел / модуль, к которому относится занятие (если указан).",
    )
    hours: int = Field(
        default=0,
        description="Часы на занятие, если явно указано в плане. 0 если не указано.",
    )
    kind: str = Field(
        default="",
        description="Вид занятия: 'лекция' / 'практическое занятие' / "
        "'лабораторная работа' / 'семинар'. Пустая строка, если не определено.",
    )


class TopicPlan(BaseModel):
    """Полный тематический план дисциплины."""

    discipline: str = Field(description="Дисциплина, как написана в РПД")
    specialty: str = Field(description="Специальность из РПД")
    items: list[TopicPlanItem] = Field(
        description="Список занятий в порядке их следования в РПД"
    )


_SYSTEM_PROMPT = """Ты — методист СПО. Твоя задача — извлечь полный тематический план
дисциплины из фрагментов РПД (рабочая программа дисциплины).

ЯЗЫК: только русский. Источник истины — предоставленный контекст из РПД.

ПРАВИЛА:
1. Извлекай ВСЕ темы / занятия из раздела «Тематический план», «Содержание
   учебной дисциплины», «Тематический план и содержание дисциплины».
2. Названия тем — ДОСЛОВНО как в РПД. Не сокращай, не переформулируй,
   не объединяй несколько строк в одну.
3. Нумерация — СКВОЗНАЯ с 1: даже если в РПД формат «Тема 1.1 / 1.2 / 2.1»,
   ты выдаёшь 1, 2, 3, ... в порядке появления.
4. Если в плане указаны часы — переноси точно (целое число академических
   часов на занятие). Если на тему отведено N часов и она дробится на
   несколько занятий — раздели разумно (стандартно 2 ч на занятие).
5. Вид занятия:
   - «лекция» — если в РПД помечено как «теоретическое занятие», «лекция»,
     или содержит слова «введение», «понятие», «основы», «обзор»;
   - «практическое занятие» — если «практическое», «практикум»,
     «решение задач», «упражнение»;
   - «лабораторная работа» — если «лабораторная»;
   - пустая строка, если определить невозможно.
6. Если в контексте НЕТ тематического плана нужной дисциплины — верни
   пустой список items. Не выдумывай темы из общих соображений.

КОНТЕКСТ ИЗ РПД:
{context}
"""

_USER_PROMPT = """Извлеки тематический план для:
Дисциплина: {discipline}
Специальность: {specialty}

Верни структуру TopicPlan со ВСЕМИ темами/занятиями, найденными в контексте.
"""


def extract_topic_plan(
    discipline: str,
    specialty: str,
    provider: LLMProvider | None = None,
) -> TopicPlan:
    """Достать тематический план дисциплины из индекса и распарсить через LLM.

    Не фильтрует по диапазону — это делает вызывающий код. Здесь только
    извлечение полного плана. Если в РПД дисциплины нет — вернётся
    `TopicPlan` с пустым `items`.
    """
    db, bm25 = load_index()

    code_match = SPECIALTY_CODE_RE.search(specialty)
    code = code_match.group() if code_match else None

    # Мультизапрос специально настроен под куски с тематическим планом —
    # разные РПД называют его по-разному.
    queries = [
        f"{discipline} тематический план содержание дисциплины",
        f"{discipline} темы занятий часы",
        f"{discipline} {specialty} разделы модули",
        f"{discipline} тематический план и содержание учебной дисциплины",
        f"раздел тема {discipline} количество часов",
    ]

    # k побольше обычного — план может быть на нескольких страницах.
    k = CONFIG["rag"].get("topic_plan_k", 12)
    context = retrieve_context(db, bm25, queries, k=k, specialty=code)

    if provider is None:
        # Низкая температура — план структурный, креатив не нужен.
        provider = get_llm_provider(temperature=0.0)

    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM_PROMPT), ("human", _USER_PROMPT)]
    )
    chain = prompt | provider.get_client().with_structured_output(TopicPlan)

    log.info(
        "Извлечение тематического плана: %s / %s (провайдер: %s)",
        discipline,
        specialty,
        provider.name,
    )
    plan: TopicPlan = chain.invoke(
        {"context": context, "discipline": discipline, "specialty": specialty}
    )
    log.info("План извлечён: %d тем", len(plan.items))
    return plan


def slice_plan(plan: TopicPlan, from_n: int, to_n: int) -> list[TopicPlanItem]:
    """Вырезать поддиапазон [from_n, to_n] (включительно) из плана.

    Если диапазон выходит за пределы — возвращается пересечение.
    """
    if from_n < 1 or to_n < from_n:
        raise ValueError(f"Некорректный диапазон: {from_n}..{to_n}")
    return [it for it in plan.items if from_n <= it.number <= to_n]


__all__ = [
    "TopicPlan",
    "TopicPlanItem",
    "extract_topic_plan",
    "slice_plan",
]
