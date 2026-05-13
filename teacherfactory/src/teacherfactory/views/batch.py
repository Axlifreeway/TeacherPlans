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
from teacherfactory.views.common import get_provider_for_session, index_ready
from teacherfactory.views.errors import format_exception
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

    topics_raw = st.text_area(
        "Темы уроков",
        "Основы сетевых протоколов\n"
        "Адресация в IP-сетях | практическое занятие | 90\n"
        "Маршрутизация | лабораторная работа | 90",
        height=200,
        key="b_topics",
    )
    items = parse_batch_topics(topics_raw, default_kind, default_duration)

    if items:
        n_docs = len(items) + (1 if with_assessment else 0)
        st.info(f"Будет сгенерировано: **{n_docs}** документов ({len(items)} карт)")
        with st.expander("Разбор строк (проверь, что вид распознан правильно)"):
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
