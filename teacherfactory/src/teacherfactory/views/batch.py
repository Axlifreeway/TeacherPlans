"""
Вкладка «Пакетная генерация» — список тем → ZIP с docx-файлами.
"""

import io
import zipfile
from datetime import date, timedelta

import streamlit as st

from teacherfactory.config import CONFIG
from teacherfactory.documents.lesson_card import LESSON_CARD
from teacherfactory.paths import OUTPUT_DIR
from teacherfactory.pipeline import generate_document
from teacherfactory.render import build_output_filename, render_document
from teacherfactory.views.common import get_provider_for_session, index_ready
from teacherfactory.views.errors import format_exception
from teacherfactory.views.single import (
    LESSON_KINDS,
    LESSON_TYPES,
    make_lesson_params,
)


def render(teacher: str, specialty: str, course: int, group: str, students: int) -> None:
    st.subheader("Пакетная генерация")
    st.caption("Введите список тем — по одной на строке — и получите ZIP со всеми картами.")

    col1, col2 = st.columns(2)

    with col1:
        discipline = st.text_input("Дисциплина / МДК", "Компьютерные сети", key="b_disc")
        lesson_type = st.selectbox("Тип урока", LESSON_TYPES, key="b_type")
        lesson_kind = st.selectbox("Вид занятия", LESSON_KINDS, key="b_kind")
        duration = st.selectbox("Продолжительность (мин)", [45, 90], index=1, key="b_dur")

    with col2:
        start_num = st.number_input("Начальный номер урока", min_value=1, value=1, key="b_num")
        start_date = st.date_input("Дата первого урока", value=date.today(), key="b_date")
        date_step = st.number_input(
            "Интервал между уроками (дней)", min_value=1, value=7, key="b_step"
        )

    topics_raw = st.text_area(
        "Темы уроков (одна тема = одна строка)",
        "Основы сетевых протоколов\nАдресация в IP-сетях\nМаршрутизация",
        height=200,
        key="b_topics",
    )
    topics = [t.strip() for t in topics_raw.strip().splitlines() if t.strip()]

    if topics:
        st.info(f"Будет сгенерировано: **{len(topics)}** карт")

    st.divider()

    if not index_ready():
        st.warning("Сначала постройте индекс документов — кнопка в боковой панели.")
        return

    if st.button(
        "Сгенерировать все",
        type="primary",
        disabled=not topics,
        use_container_width=True,
    ):
        _run_batch(
            topics,
            teacher,
            specialty,
            course,
            group,
            students,
            discipline,
            lesson_type,
            lesson_kind,
            duration,
            start_num,
            start_date,
            date_step,
        )


def _run_batch(
    topics: list[str],
    teacher: str,
    specialty: str,
    course: int,
    group: str,
    students: int,
    discipline: str,
    lesson_type: str,
    lesson_kind: str,
    duration: int,
    start_num: int,
    start_date: date,
    date_step: int,
) -> None:
    docx_files: dict[str, bytes] = {}
    errors: list[str] = []

    progress = st.progress(0.0, text="Начинаю генерацию...")
    log_slot = st.empty()

    provider = get_provider_for_session(temperature=CONFIG["model"]["temperature"])

    for i, topic in enumerate(topics):
        n = start_num + i
        d = start_date + timedelta(days=i * date_step)
        log_slot.text(f"[{i + 1}/{len(topics)}] {topic[:70]}...")

        params = make_lesson_params(
            discipline,
            specialty,
            course,
            group,
            students,
            topic,
            n,
            d,
            teacher,
            lesson_type,
            lesson_kind,
            duration,
        )
        try:
            card = generate_document(LESSON_CARD, params, provider=provider)
            fname = build_output_filename(LESSON_CARD, params)
            out_path = OUTPUT_DIR / fname
            render_document(LESSON_CARD, card, out_path)
            docx_files[fname] = out_path.read_bytes()
        except Exception as e:
            errors.append(f"Урок {n} «{topic}»: {format_exception(e)}")

        progress.progress((i + 1) / len(topics), text=f"{i + 1}/{len(topics)} готово")

    log_slot.empty()
    progress.empty()

    for err in errors:
        st.warning(err)

    if docx_files:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in docx_files.items():
                zf.writestr(name, data)

        st.success(f"Готово: {len(docx_files)} из {len(topics)} карт сгенерировано.")
        st.download_button(
            label="Скачать все (ZIP)",
            data=buf.getvalue(),
            file_name=f"{discipline}_карты.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )
