"""
Вкладка «Один урок» — генерация одной технологической карты.

Сейчас захардкожена под `LessonCard`, но построена через общий пайплайн
`generate_document(LESSON_CARD, ...)`. Когда появятся РПД/аттестация — копия
этого файла + другой `DocumentType`.
"""

from datetime import date

import streamlit as st

from teacherfactory.config import CONFIG
from teacherfactory.documents.lesson_card import LESSON_CARD
from teacherfactory.model import LessonCard
from teacherfactory.paths import OUTPUT_DIR
from teacherfactory.pipeline import generate_document
from teacherfactory.prompts import LESSON_TYPE_AUTO_HINT, LESSON_TYPE_CHOICES
from teacherfactory.render import build_output_filename, render_document
from teacherfactory.validation import validate_competencies
from teacherfactory.views.common import get_provider_for_session, index_ready
from teacherfactory.views.errors import format_exception, show_error

LESSON_TYPE_AUTO = "Авто (определит ИИ)"
LESSON_TYPES = (LESSON_TYPE_AUTO, *LESSON_TYPE_CHOICES)

LESSON_KINDS = [
    "лекция",
    "практическое занятие",
    "лабораторная работа",
    "семинар",
    "урок-беседа",
    "урок-дискуссия",
]


def make_lesson_params(
    discipline: str,
    specialty: str,
    course: int,
    group: str,
    students: int,
    topic: str,
    number: int,
    lesson_date: date,
    teacher: str,
    lesson_type: str,
    lesson_kind: str,
    duration: int,
) -> dict:
    """
    Собрать словарь параметров для пайплайна генерации карты.

    `lesson_type` может быть LESSON_TYPE_AUTO — тогда в промпт уходит
    подсказка «выбери сам», и модель сама проставит поле в LessonCard.
    """
    if lesson_type == LESSON_TYPE_AUTO:
        type_hint = LESSON_TYPE_AUTO_HINT
    else:
        type_hint = lesson_type
    return {
        "discipline": discipline,
        "specialty": specialty,
        "course_number": course,
        "group_name": group,
        "students_count": students,
        "lesson_topic": topic,
        "lesson_number": number,
        "date": lesson_date.strftime("%d.%m.%Y"),
        "teacher_name": teacher,
        "lesson_type_hint": type_hint,
        "lesson_kind": lesson_kind,
        "duration": duration,
    }


def render(teacher: str, specialty: str, course: int, group: str, students: int) -> None:
    col1, col2 = st.columns(2)

    with col1:
        discipline = st.text_input("Дисциплина / МДК", "Компьютерные сети")
        topic = st.text_input("Тема занятия", "Основы сетевых протоколов")
        lesson_type = st.selectbox(
            "Тип урока",
            LESSON_TYPES,
            help="«Авто» — модель выберет подходящий тип на основе темы и вида занятия.",
        )
        lesson_kind = st.selectbox("Вид занятия", LESSON_KINDS)

    with col2:
        number = st.number_input("Номер занятия", min_value=1, value=1)
        lesson_date = st.date_input("Дата", value=date.today())
        duration = st.selectbox("Продолжительность (мин)", [45, 90], index=1)

    st.divider()

    if not index_ready():
        st.warning("Сначала постройте индекс документов — кнопка в боковой панели.")
        return

    if st.button("Сгенерировать карту", type="primary", use_container_width=True):
        st.session_state.pop("single_bytes", None)

        params = make_lesson_params(
            discipline,
            specialty,
            course,
            group,
            students,
            topic,
            number,
            lesson_date,
            teacher,
            lesson_type,
            lesson_kind,
            duration,
        )
        fname = build_output_filename(LESSON_CARD, params)
        out_path = OUTPUT_DIR / fname

        with st.status("Генерирую технологическую карту...", expanded=True) as status:
            stage_slot = st.empty()
            token_slot = st.empty()

            stage_labels = {
                "index": "1/3 — Загружаю индекс...",
                "context": "2/3 — Ищу контекст в документах...",
                "generate": "3/3 — Генерирую карту...",
            }

            def on_stage(name: str) -> None:
                stage_slot.markdown(f"**{stage_labels.get(name, name)}**")
                if name != "generate":
                    token_slot.empty()

            def on_token(count: int) -> None:
                token_slot.caption(f"токенов: {count}")

            try:
                provider = get_provider_for_session(temperature=CONFIG["model"]["temperature"])
                stage_slot.markdown(
                    f"**Провайдер: {provider.name} ({provider.config.model_name})**"
                )

                card = generate_document(
                    LESSON_CARD,
                    params,
                    provider=provider,
                    on_token=on_token,
                    on_stage=on_stage,
                )
                stage_slot.markdown("**Рендерю DOCX...**")
                token_slot.empty()
                render_document(LESSON_CARD, card, out_path)

                st.session_state["single_bytes"] = out_path.read_bytes()
                st.session_state["single_fname"] = fname
                st.session_state["single_card"] = card

                stage_slot.markdown("**Проверяю компетенции...**")
                st.session_state["validation"] = validate_competencies(card)
                status.update(label="Готово!", state="complete")
            except Exception as e:
                status.update(label=f"Ошибка: {format_exception(e)}", state="error")
                show_error("Не удалось сгенерировать карту", e)

    if "single_bytes" in st.session_state:
        _render_preview()


def _render_preview() -> None:
    card: LessonCard = st.session_state["single_card"]
    fname = st.session_state["single_fname"]
    validation: dict[str, bool] = st.session_state.get("validation", {})

    st.success(f"Карта готова: {card.lesson_topic}")

    unverified = [c for c, found in validation.items() if not found]
    if unverified:
        st.warning(
            f"⚠️ Следующие коды **не найдены** в документах — возможно выдуманы моделью: "
            f"`{'`, `'.join(unverified)}`"
        )

    with st.expander("Предпросмотр"):
        st.markdown(f"**Тип урока:** {card.lesson_type}")
        st.markdown(f"**Вид занятия:** {card.lesson_kind}")
        st.markdown(f"**Цель:** {card.goal}")
        if card.epigraph:
            st.markdown(f"> *«{card.epigraph}»* — {card.epigraph_author}")

        st.markdown("**Компетенции:**")
        for comp in card.competencies:
            ok = validation.get(comp.code)
            icon = "⚠️" if ok is False else "✅" if ok is True else "•"
            st.markdown(f"{icon} **{comp.code}** — {comp.name}")
            st.caption(comp.indicator)

        st.markdown("**Результаты обучения (З/У/Н):**")
        for out in card.learning_outcomes:
            st.markdown(f"- **{out.code}** ({out.type}) — {out.name}")
            st.caption(out.indicator)

        st.divider()
        st.markdown("**Ход занятия:**")
        for s in card.lesson_structure:
            with st.expander(f"{s.number}. {s.stage} — {s.substage} ({s.time} мин)"):
                c1, c2 = st.columns(2)
                c1.markdown(f"**Задачи этапа:**\n\n{s.tasks}")
                c1.markdown(f"**Деятельность преподавателя:**\n\n{s.teacher}")
                c1.markdown(f"**Приёмы:** {s.methods}")
                c1.markdown(f"**Средства:** {s.means}")
                c2.markdown(f"**Результат:**\n\n{s.result}")
                c2.markdown(f"**Деятельность студентов:**\n\n{s.student}")
                c2.markdown(f"**Контроль:** {s.control}")

    st.download_button(
        label="Скачать DOCX",
        data=st.session_state["single_bytes"],
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type="primary",
        use_container_width=True,
    )
