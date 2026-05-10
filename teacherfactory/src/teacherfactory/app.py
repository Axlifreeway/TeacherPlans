"""
Streamlit-интерфейс TeacherFactory.

Запуск: poetry run streamlit run src/teacherfactory/app.py
"""

import io
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from config import CONFIG  # noqa: E402
from generator import generate_lesson_card, render_docx, stream_chat_response  # noqa: E402
from indexer import INDEX_DIR, build_index  # noqa: E402

OUTPUT_DIR = Path.home() / ".teacherfactory" / "output"

LESSON_TYPES = [
    "комбинированный урок",
    "урок изучения нового материала",
    "урок закрепления знаний",
    "урок обобщения и систематизации знаний",
    "урок контроля знаний",
]

LESSON_KINDS = [
    "лекция",
    "практическое занятие",
    "лабораторная работа",
    "семинар",
    "урок-беседа",
    "урок-дискуссия",
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def index_ready() -> bool:
    return INDEX_DIR.exists() and any(INDEX_DIR.iterdir())


def make_params(
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
        "lesson_type": lesson_type,
        "lesson_kind": lesson_kind,
        "duration": duration,
    }


def docx_filename(number: int, discipline: str) -> str:
    return f"Урок_{number}_{discipline}.docx"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="TeacherFactory",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("TeacherFactory")
    st.caption("Генератор технологических карт уроков для СПО")

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Индекс документов")
        if index_ready():
            st.success("Индекс готов")
        else:
            st.warning("Индекс не построен")

        if st.button("Перестроить индекс", use_container_width=True):
            with st.spinner("Индексирую PDF из папки docs/..."):
                try:
                    build_index()
                    st.success("Индекс построен!")
                except Exception as e:
                    st.error(f"Ошибка индексации: {e}")
            st.rerun()

        st.divider()
        st.header("Общие сведения")
        teacher = st.text_input("Преподаватель", "Иванов И.И.")
        specialty = st.text_input(
            "Специальность",
            "09.01.03 Оператор информационных систем и ресурсов",
        )
        group = st.text_input("Группа", "ОИСИР-21")
        course = st.number_input("Курс", min_value=1, max_value=4, value=2)
        students = st.number_input("Студентов в группе", min_value=1, max_value=60, value=25)

        st.divider()
        st.caption(f"Модель: `{CONFIG['model']['llm']}`")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_one, tab_batch, tab_chat = st.tabs(["Один урок", "Пакетная генерация", "Чат с документами"])

    with tab_one:
        _tab_single(teacher, specialty, course, group, students)

    with tab_batch:
        _tab_batch(teacher, specialty, course, group, students)

    with tab_chat:
        _tab_chat()


# ─── Вкладка: один урок ───────────────────────────────────────────────────────

def _tab_single(teacher, specialty, course, group, students) -> None:
    col1, col2 = st.columns(2)

    with col1:
        discipline = st.text_input("Дисциплина / МДК", "Компьютерные сети")
        topic = st.text_input("Тема занятия", "Основы сетевых протоколов")
        lesson_type = st.selectbox("Тип урока", LESSON_TYPES)
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
        # Сбрасываем предыдущий результат при новой генерации
        st.session_state.pop("single_bytes", None)

        params = make_params(
            discipline, specialty, course, group, students,
            topic, number, lesson_date, teacher, lesson_type, lesson_kind, duration,
        )
        fname = docx_filename(number, discipline)
        out_path = OUTPUT_DIR / fname

        with st.status("Генерирую технологическую карту...", expanded=True) as status:
            try:
                st.write("Загружаю индекс и ищу релевантный контекст...")
                card = generate_lesson_card(params)
                st.write("Рендерю DOCX...")
                render_docx(card, out_path)
                with open(out_path, "rb") as f:
                    st.session_state["single_bytes"] = f.read()
                st.session_state["single_fname"] = fname
                st.session_state["single_card"] = card
                status.update(label="Готово!", state="complete")
            except Exception as e:
                status.update(label=f"Ошибка: {e}", state="error")
                st.error(str(e))

    if "single_bytes" in st.session_state:
        card = st.session_state["single_card"]
        fname = st.session_state["single_fname"]

        st.success(f"Карта готова: {card.lesson_topic}")

        with st.expander("Предпросмотр"):
            st.markdown(f"**Цель:** {card.goal}")
            st.markdown(f"**ОК:** {card.competencies_ok}")
            st.markdown(f"**ПК:** {card.competencies_pk}")
            st.markdown("**Ход занятия:**")
            st.table([
                {"№": s.number, "Этап": s.stage, "Время": s.time, "Методы": s.methods}
                for s in card.lesson_structure
            ])

        st.download_button(
            label="Скачать DOCX",
            data=st.session_state["single_bytes"],
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
            use_container_width=True,
        )


# ─── Вкладка: пакетная генерация ─────────────────────────────────────────────

def _tab_batch(teacher, specialty, course, group, students) -> None:
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
        date_step = st.number_input("Интервал между уроками (дней)", min_value=1, value=7, key="b_step")

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
        docx_files: dict[str, bytes] = {}
        errors: list[str] = []

        progress = st.progress(0.0, text="Начинаю генерацию...")
        log_slot = st.empty()

        for i, topic in enumerate(topics):
            n = start_num + i
            d = start_date + timedelta(days=i * date_step)
            log_slot.text(f"[{i + 1}/{len(topics)}] {topic[:70]}...")

            params = make_params(
                discipline, specialty, course, group, students,
                topic, n, d, teacher, lesson_type, lesson_kind, duration,
            )
            try:
                card = generate_lesson_card(params)
                fname = docx_filename(n, discipline)
                out_path = OUTPUT_DIR / fname
                render_docx(card, out_path)
                with open(out_path, "rb") as f:
                    docx_files[fname] = f.read()
            except Exception as e:
                errors.append(f"Урок {n} «{topic}»: {e}")

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


# ─── Вкладка: чат с документами ──────────────────────────────────────────────

def _tab_chat() -> None:
    st.subheader("Чат с документами")
    st.caption(
        "Задавай вопросы по учебным программам, компетенциям, требованиям ФГОС — "
        "без генерации файлов."
    )

    if not index_ready():
        st.warning("Сначала постройте индекс документов — кнопка в боковой панели.")
        return

    # Инициализация истории чата
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    # Отображаем историю
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Поле ввода
    question = st.chat_input("Спроси о программе, компетенциях, требованиях...")

    if question:
        # Показываем вопрос
        with st.chat_message("user"):
            st.markdown(question)
        st.session_state["chat_history"].append({"role": "user", "content": question})

        # Стримим ответ
        with st.chat_message("assistant"):
            try:
                response = st.write_stream(stream_chat_response(question))
            except Exception as e:
                response = f"Ошибка: {e}"
                st.error(response)

        st.session_state["chat_history"].append({"role": "assistant", "content": response})

    # Кнопка очистки истории
    if st.session_state["chat_history"]:
        if st.button("Очистить историю", type="secondary"):
            st.session_state["chat_history"] = []
            st.rerun()


if __name__ == "__main__":
    main()
