"""
Вкладка «Пакетная генерация» — список тем → ZIP с docx-файлами.

Поддерживает два формата ввода:
  - простой: `Тема` (одна на строку, тип/вид/часы — из дефолтов);
  - расширенный: `Тема | Вид | Часы` (часы — 45/90; вид — из LESSON_KINDS).
"""

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta

import streamlit as st

from teacherfactory.config import CONFIG
from teacherfactory.documents.assessment_materials import ASSESSMENT_MATERIALS
from teacherfactory.documents.lesson_card import LESSON_CARD
from teacherfactory.paths import OUTPUT_DIR
from teacherfactory.pipeline import generate_document
from teacherfactory.render import build_output_filename, render_document
from teacherfactory.topic_plan import TopicPlanItem, extract_topic_plan, slice_plan
from teacherfactory.views.common import get_provider_for_session, index_ready
from teacherfactory.views.errors import format_exception, show_error
from teacherfactory.views.single import (
    LESSON_KINDS,
    LESSON_TYPES,
    LESSON_TYPE_AUTO,
    make_lesson_params,
)

_LECTURE_HINTS = re.compile(
    r"(введени|основ|обзор|понятие|истори|теори|архитектур|классификац)",
    re.IGNORECASE,
)
_PRACTICE_HINTS = re.compile(
    r"(лаборатор|практик|разработ|реализац|задач|составлен|написан|настройк)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BatchItem:
    """Одна строка батча: тема + локальные переопределения вида/часов."""

    topic: str
    kind: str
    duration: int


def parse_batch_topics(raw: str, default_kind: str, default_duration: int) -> list[BatchItem]:
    """
    Распарсить ввод вкладки «Пакет».

    Каждая строка: `Тема` либо `Тема | Вид | Часы` (любые лишние пробелы
    обрезаются). Если в строке только тема — берутся значения по умолчанию.
    Если вид/часы заданы не полностью — отсутствующие поля берутся из дефолтов.
    Если вид НЕ задан и НЕ распознан эвристикой → используется `default_kind`.
    """
    items: list[BatchItem] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        topic = parts[0]
        if not topic:
            continue

        kind = parts[1] if len(parts) > 1 and parts[1] else _guess_kind(topic, default_kind)
        duration_raw = parts[2] if len(parts) > 2 and parts[2] else str(default_duration)
        duration = _parse_duration(duration_raw, default_duration)
        items.append(BatchItem(topic=topic, kind=kind, duration=duration))
    return items


def _guess_kind(topic: str, default_kind: str) -> str:
    """Простая эвристика по ключевым словам в названии темы."""
    if _PRACTICE_HINTS.search(topic):
        return "лабораторная работа" if "лаборатор" in topic.lower() else "практическое занятие"
    if _LECTURE_HINTS.search(topic):
        return "лекция"
    return default_kind


def _parse_duration(raw: str, default: int) -> int:
    """Из «90», «90 мин», «2 ч» — извлечь минуты."""
    raw_lower = raw.lower().strip()
    if "ч" in raw_lower:  # «2 ч», «1.5 часа»
        match = re.search(r"(\d+(?:[.,]\d+)?)", raw_lower)
        if match:
            return int(round(float(match.group(1).replace(",", ".")) * 45))
    match = re.search(r"(\d+)", raw_lower)
    return int(match.group(1)) if match else default


def render(teacher: str, specialty: str, course: int, group: str, students: int) -> None:
    st.subheader("Пакетная генерация")
    st.caption(
        "Формат строки: `Тема` или `Тема | Вид | Часы`. Если вид не задан — "
        "определится по ключевым словам в теме."
    )

    col1, col2 = st.columns(2)

    with col1:
        discipline = st.text_input("Дисциплина / МДК", "Компьютерные сети", key="b_disc")
        lesson_type = st.selectbox(
            "Тип урока (общий)",
            LESSON_TYPES,
            key="b_type",
            help="«Авто» — модель выберет тип для каждой темы. Иначе тип "
            "применится ко всем урокам батча.",
        )
        default_kind = st.selectbox(
            "Вид занятия по умолчанию",
            LESSON_KINDS,
            key="b_kind",
            help="Применится к темам, для которых вид не указан и не "
            "определился эвристикой.",
        )
        default_duration = st.selectbox(
            "Часы по умолчанию (мин)", [45, 90], index=1, key="b_dur"
        )
        with_assessment = st.checkbox(
            "Сгенерировать УМК (карта + оценочные материалы)",
            value=False,
            key="b_umk",
            help="К каждой дисциплине добавится один комплект оценочных "
            "материалов (КОС/ФОС).",
        )

    with col2:
        start_num = st.number_input("Начальный номер урока", min_value=1, value=1, key="b_num")
        start_date = st.date_input("Дата первого урока", value=date.today(), key="b_date")
        date_step = st.number_input(
            "Интервал между уроками (дней)", min_value=1, value=7, key="b_step"
        )
        semester = st.number_input(
            "Семестр (для ОМ)",
            min_value=1,
            max_value=12,
            value=1,
            key="b_semester",
            disabled=not with_assessment,
        )
        final_form = st.selectbox(
            "Форма промежуточной аттестации (для ОМ)",
            ["дифференцированный зачёт", "зачёт", "экзамен"],
            key="b_final",
            disabled=not with_assessment,
        )

    st.divider()
    mode = st.radio(
        "Источник тем",
        ["Авто (из РПД)", "Ручной список"],
        horizontal=True,
        key="b_mode",
        help=(
            "Авто — система достанет тематический план из проиндексированных РПД "
            "по дисциплине и специальности. Ручной — вписать темы построчно."
        ),
    )

    if mode == "Авто (из РПД)":
        items = _render_auto_topics_block(
            discipline, specialty, default_kind, default_duration
        )
    else:
        items = _render_manual_topics_block(default_kind, default_duration)

    if items:
        n_docs = len(items) + (1 if with_assessment else 0)
        st.info(f"Будет сгенерировано: **{n_docs}** документов ({len(items)} карт)")
        with st.expander("Разбор тем (проверь перед генерацией)"):
            for it in items:
                st.text(f"• {it.topic} → {it.kind}, {it.duration} мин")

    st.divider()

    if not index_ready():
        st.warning("Сначала постройте индекс документов — кнопка в боковой панели.")
        return

    if st.button(
        "Сгенерировать все",
        type="primary",
        disabled=not items,
        use_container_width=True,
    ):
        _run_batch(
            items,
            teacher,
            specialty,
            course,
            group,
            students,
            discipline,
            lesson_type,
            start_num,
            start_date,
            date_step,
            with_assessment=with_assessment,
            semester=semester,
            final_form=final_form,
        )


# ─── Источники тем ────────────────────────────────────────────────────────────


def _render_manual_topics_block(default_kind: str, default_duration: int) -> list[BatchItem]:
    topics_raw = st.text_area(
        "Темы уроков",
        "Основы сетевых протоколов\n"
        "Адресация в IP-сетях | практическое занятие | 90\n"
        "Маршрутизация | лабораторная работа | 90",
        height=200,
        key="b_topics",
        help="Формат: `Тема` или `Тема | Вид | Часы`. Одна тема на строку.",
    )
    return parse_batch_topics(topics_raw, default_kind, default_duration)


def _render_auto_topics_block(
    discipline: str,
    specialty: str,
    default_kind: str,
    default_duration: int,
) -> list[BatchItem]:
    """Авто-режим: достать темы из РПД и предложить отредактировать.

    Состояние извлечённого плана лежит в `st.session_state['auto_plan']` —
    переживает rerender'ы Streamlit без повторного дёргания LLM.
    """
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        from_n = st.number_input("С урока №", min_value=1, value=1, key="b_auto_from")
    with c2:
        to_n = st.number_input(
            "По урок №", min_value=int(from_n), value=max(int(from_n), 10), key="b_auto_to"
        )
    with c3:
        st.caption(
            "Система сама достанет темы из тематического плана РПД "
            "и нумерует их сквозным счётчиком."
        )

    fetch = st.button("🔍 Найти темы в РПД", use_container_width=True, key="b_auto_fetch")

    if fetch:
        if not discipline.strip():
            st.error("Укажи дисциплину.")
        elif not specialty.strip():
            st.error("Укажи специальность в боковой панели.")
        elif not index_ready():
            st.warning("Сначала постройте индекс документов.")
        else:
            with st.spinner(f"Ищу тематический план «{discipline}» в РПД..."):
                try:
                    provider = get_provider_for_session(temperature=0.0)
                    plan = extract_topic_plan(discipline, specialty, provider=provider)
                    st.session_state["auto_plan"] = plan
                    st.session_state["auto_plan_key"] = (discipline, specialty)
                except Exception as e:
                    show_error("Не удалось извлечь тематический план", e)
                    st.session_state.pop("auto_plan", None)

    plan = st.session_state.get("auto_plan")
    plan_key = st.session_state.get("auto_plan_key")
    if plan is None or plan_key != (discipline, specialty):
        st.caption("Нажми «Найти темы в РПД», чтобы загрузить тематический план.")
        return []

    if not plan.items:
        st.warning(
            "Тематический план для этой дисциплины в индексе не найден. "
            "Проверь, что РПД дисциплины проиндексировано, или используй ручной режим."
        )
        return []

    selected = slice_plan(plan, int(from_n), int(to_n))
    st.success(
        f"Найдено всего тем: **{len(plan.items)}**, "
        f"в диапазон {from_n}..{to_n} попало: **{len(selected)}**."
    )

    with st.expander(f"Все найденные темы (полный план: {len(plan.items)})"):
        for it in plan.items:
            mark = " ✓" if from_n <= it.number <= to_n else ""
            hours = f", {it.hours} ч" if it.hours else ""
            kind = f" [{it.kind}]" if it.kind else ""
            section = f" — раздел: {it.section}" if it.section else ""
            st.caption(f"{it.number}. {it.title}{kind}{hours}{section}{mark}")

    # Возможность подредактировать выбранные темы перед запуском.
    return _plan_items_to_batch_items(selected, default_kind, default_duration)


def _plan_items_to_batch_items(
    plan_items: list[TopicPlanItem],
    default_kind: str,
    default_duration: int,
) -> list[BatchItem]:
    """Перевод TopicPlanItem (из РПД) в BatchItem (для пайплайна)."""
    items: list[BatchItem] = []
    for p in plan_items:
        kind = p.kind or _guess_kind(p.title, default_kind)
        # Часы → продолжительность в минутах. 1 ак.ч = 45 мин.
        # Если в плане 2 ч на занятие — это 90 мин (один спаренный урок).
        # Если 1 ч — берём 45. Если не указано — default.
        if p.hours == 1:
            duration = 45
        elif p.hours >= 2:
            duration = 90
        else:
            duration = default_duration
        items.append(BatchItem(topic=p.title, kind=kind, duration=duration))
    return items


def _run_batch(
    items: list[BatchItem],
    teacher: str,
    specialty: str,
    course: int,
    group: str,
    students: int,
    discipline: str,
    lesson_type: str,
    start_num: int,
    start_date: date,
    date_step: int,
    *,
    with_assessment: bool,
    semester: int,
    final_form: str,
) -> None:
    """
    Сгенерировать все карты (и опционально комплект ОМ) и сложить в один ZIP.

    Структура ZIP:
      lesson_cards/ — все технологические карты;
      assessment/   — оценочные материалы (если запрошены).
    """
    docx_files: dict[str, bytes] = {}
    errors: list[str] = []

    total = len(items) + (1 if with_assessment else 0)
    progress = st.progress(0.0, text="Начинаю генерацию...")
    log_slot = st.empty()

    provider = get_provider_for_session(temperature=CONFIG["model"]["temperature"])

    for i, item in enumerate(items):
        n = start_num + i
        d = start_date + timedelta(days=i * date_step)
        log_slot.text(f"[{i + 1}/{total}] {item.topic[:70]}... ({item.kind}, {item.duration} мин)")

        params = make_lesson_params(
            discipline,
            specialty,
            course,
            group,
            students,
            item.topic,
            n,
            d,
            teacher,
            lesson_type,
            item.kind,
            item.duration,
        )
        try:
            card = generate_document(LESSON_CARD, params, provider=provider)
            fname = build_output_filename(LESSON_CARD, params)
            out_path = OUTPUT_DIR / fname
            render_document(LESSON_CARD, card, out_path)
            docx_files[f"lesson_cards/{fname}"] = out_path.read_bytes()
        except Exception as e:
            errors.append(f"Урок {n} «{item.topic}»: {format_exception(e)}")

        progress.progress((i + 1) / total, text=f"{i + 1}/{total} готово")

    if with_assessment:
        log_slot.text(f"[{total}/{total}] Оценочные материалы по дисциплине...")
        assessment_params = {
            "discipline": discipline,
            "specialty": specialty,
            "semester": semester,
            "final_form": final_form,
        }
        try:
            materials = generate_document(
                ASSESSMENT_MATERIALS, assessment_params, provider=provider
            )
            fname = build_output_filename(ASSESSMENT_MATERIALS, assessment_params)
            out_path = OUTPUT_DIR / fname
            render_document(ASSESSMENT_MATERIALS, materials, out_path)
            docx_files[f"assessment/{fname}"] = out_path.read_bytes()
        except Exception as e:
            errors.append(f"Оценочные материалы: {format_exception(e)}")
        progress.progress(1.0, text=f"{total}/{total} готово")

    log_slot.empty()
    progress.empty()

    for err in errors:
        st.warning(err)

    if docx_files:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in docx_files.items():
                zf.writestr(name, data)

        st.success(f"Готово: {len(docx_files)} из {total} файлов сгенерировано.")
        st.download_button(
            label="Скачать все (ZIP)",
            data=buf.getvalue(),
            file_name=f"{discipline}_УМК.zip" if with_assessment else f"{discipline}_карты.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )
