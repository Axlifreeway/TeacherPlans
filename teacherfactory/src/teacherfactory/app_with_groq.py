"""
Streamlit-интерфейс TeacherFactory с поддержкой Groq API.

Запуск: poetry run streamlit run src/teacherfactory/app_with_groq.py

Особенности:
- Выбор источника LLM: Ollama (локально) или Groq (облако, бесплатно)
- Для Groq требуется API ключ: https://console.groq.com/keys
- Ключ добавляется в config.local.toml или через интерфейс
"""

import io
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from config import CONFIG  # noqa: E402
from generator import (  # noqa: E402
    generate_lesson_card,
    render_docx,
    stream_chat_response,
    validate_competencies,
)
from indexer import INDEX_DIR, build_index, DOCS_DIR  # noqa: E402

# Пытаемся импортировать Groq-клиент
try:
    from groq_client import (
        generate_with_groq,
        stream_chat_with_groq,
        is_groq_configured,
        get_groq_model_info,
    )
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

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


def get_llm_source() -> str:
    """Определить текущий источник LLM."""
    if GROQ_AVAILABLE and is_groq_configured():
        return st.session_state.get("llm_source", "groq")
    return st.session_state.get("llm_source", "ollama")


def set_llm_source(source: str) -> None:
    st.session_state["llm_source"] = source


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
            with st.spinner("Индексирую PDF/DOCX из папки docs/..."):
                try:
                    build_index()
                    st.success("Индекс построен!")
                except Exception as e:
                    st.error(f"Ошибка индексации: {e}")
            st.rerun()

        # Предупреждение о .doc файлах
        skipped_path = INDEX_DIR / "skipped_doc_files.txt"
        if skipped_path.exists():
            skipped = skipped_path.read_text(encoding="utf-8").strip().splitlines()
            if skipped:
                st.warning(
                    f"⚠️ {len(skipped)} файл(ов) **не проиндексированы** "
                    f"(формат .doc не поддерживается):\n\n"
                    + "\n".join(f"- `{f}`" for f in skipped)
                    + "\n\nСконвертируй через Word → «Сохранить как .docx»."
                )

        st.divider()
        
        # ── Выбор LLM ───────────────────────────────────────────────────────
        st.header("Источник LLM")
        
        llm_options = ["Ollama (локально)"]
        if GROQ_AVAILABLE:
            llm_options.append("Groq (облако)")
        
        selected_llm = st.radio(
            "Выберите модель:",
            llm_options,
            index=1 if (GROQ_AVAILABLE and is_groq_configured()) else 0,
        )
        
        if "Groq" in selected_llm:
            set_llm_source("groq")
            groq_info = get_groq_model_info()
            if groq_info["configured"]:
                st.success(f"✅ Groq: {groq_info['model']}")
            else:
                st.error("❌ API ключ не настроен")
                st.info(
                    "1. Получи ключ: https://console.groq.com/keys\n"
                    "2. Добавь в config.local.toml:\n"
                    "```toml\n[groq]\napi_key = \"gsk_...\"\n```"
                )
        else:
            set_llm_source("ollama")
            st.caption(f"Модель: `{CONFIG['model']['llm']}`")

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

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_one, tab_batch, tab_chat = st.tabs(["Один урок", "Пакетная генерация", "Чат с документами"])

    with tab_one:
        _tab_single(teacher, specialty, course, group, students)

    with tab_batch:
        _tab_batch(teacher, specialty, course, group, students)

    with tab_chat:
        _tab_chat()


# ─── Helpers для предпросмотра ────────────────────────────────────────────────

def _render_competencies(text: str, validation: dict[str, bool]) -> None:
    """Выводит текст компетенций, подсвечивая непроверенные коды."""
    import re
    from generator import COMPETENCY_RE

    if not text or text.strip() == "Не указано в документах":
        st.markdown(f"*{text}*")
        return

    lines = text.strip().splitlines()
    for line in lines:
        codes_in_line = COMPETENCY_RE.findall(line)
        if codes_in_line:
            unverified = [c for c in codes_in_line if validation.get(c) is False]
            if unverified:
                st.markdown(f"⚠️ {line}")
            else:
                st.markdown(f"✅ {line}")
        else:
            st.markdown(line)


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

    llm_source = get_llm_source()
    
    if st.button("Сгенерировать карту", type="primary", use_container_width=True):
        st.session_state.pop("single_bytes", None)

        params = make_params(
            discipline, specialty, course, group, students,
            topic, number, lesson_date, teacher, lesson_type, lesson_kind, duration,
        )
        fname = docx_filename(number, discipline)
        out_path = OUTPUT_DIR / fname

        STAGE_LABELS = {
            "index":    "1/3 — Загружаю индекс...",
            "context":  "2/3 — Ищу контекст в документах...",
            "generate": f"3/3 — {'Groq' if llm_source == 'groq' else 'LLM'} генерирует карту...",
        }

        with st.status("Генерирую технологическую карту...", expanded=True) as status:
            stage_slot = st.empty()
            token_slot = st.empty()

            def on_stage(name: str) -> None:
                stage_slot.markdown(f"**{STAGE_LABELS.get(name, name)}**")
                if name != "generate":
                    token_slot.empty()

            def on_token(count: int) -> None:
                token_slot.caption(f"токенов: {count}")

            try:
                # Поиск контекста (RAG)
                from generator import load_index, retrieve_context, _lesson_search_queries
                
                db, bm25_data = load_index()
                queries = _lesson_search_queries(params["discipline"], params["specialty"])
                context = retrieve_context(db, bm25_data, queries)
                
                # Генерация через выбранный источник
                if llm_source == "groq" and GROQ_AVAILABLE:
                    card = generate_with_groq(params, context, on_token=on_token)
                else:
                    card = generate_lesson_card(params, on_token=on_token, on_stage=lambda x: None)
                
                stage_slot.markdown("**Рендерю DOCX...**")
                token_slot.empty()
                render_docx(card, out_path)
                with open(out_path, "rb") as f:
                    st.session_state["single_bytes"] = f.read()
                st.session_state["single_fname"] = fname
                st.session_state["single_card"] = card

                stage_slot.markdown("**Проверяю компетенции...**")
                st.session_state["validation"] = validate_competencies(card)
                status.update(label="Готово!", state="complete")
            except Exception as e:
                status.update(label=f"Ошибка: {e}", state="error")
                st.error(str(e))

    if "single_bytes" in st.session_state:
        card = st.session_state["single_card"]
        fname = st.session_state["single_fname"]
        validation: dict[str, bool] = st.session_state.get("validation", {})

        st.success(f"Карта готова: {card.lesson_topic}")

        # Предупреждение о непроверенных компетенциях
        unverified = [c for c, found in validation.items() if not found]
        if unverified:
            st.warning(
                f"⚠️ Следующие коды **не найдены** в документах — возможно выдуманы моделью: "
                f"`{'`, `'.join(unverified)}`"
            )

        with st.expander("Предпросмотр"):
            st.markdown(f"**Цель:** {card.goal}")

            # Компетенции с индикаторами валидации
            st.markdown("**Общие компетенции (ОК):**")
            _render_competencies(card.competencies_ok, validation)
            st.markdown("**Профессиональные компетенции (ПК):**")
            _render_competencies(card.competencies_pk, validation)

            st.divider()
            st.markdown("**Ход занятия:**")
            for s in card.lesson_structure:
                with st.expander(f"{s.number}. {s.stage} — {s.time}"):
                    c1, c2 = st.columns(2)
                    c1.markdown(f"**Преподаватель:**\n\n{s.teacher}")
                    c1.markdown(f"**Методы:** {s.methods}")
                    c2.markdown(f"**Студенты:**\n\n{s.student}")
                    c2.markdown(f"**Результат:** {s.result}")

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

    llm_source = get_llm_source()

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

        # Импорты для генерации
        from generator import load_index, retrieve_context, _lesson_search_queries, render_docx
        
        db, bm25_data = load_index()

        for i, topic in enumerate(topics):
            n = start_num + i
            d = start_date + timedelta(days=i * date_step)
            log_slot.text(f"[{i + 1}/{len(topics)}] {topic[:70]}...")

            params = make_params(
                discipline, specialty, course, group, students,
                topic, n, d, teacher, lesson_type, lesson_kind, duration,
            )
            try:
                # Поиск контекста
                queries = _lesson_search_queries(params["discipline"], params["specialty"])
                context = retrieve_context(db, bm25_data, queries)
                
                # Генерация
                if llm_source == "groq" and GROQ_AVAILABLE:
                    card = generate_with_groq(params, context)
                else:
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
            llm_source = get_llm_source()
            
            try:
                if llm_source == "groq" and GROQ_AVAILABLE:
                    from groq_client import stream_chat_with_groq
                    from generator import load_index, retrieve_context
                    
                    db, bm25_data = load_index()
                    context = retrieve_context(db, bm25_data, question, k=15)
                    
                    response = st.write_stream(stream_chat_with_groq(question, context))
                else:
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
