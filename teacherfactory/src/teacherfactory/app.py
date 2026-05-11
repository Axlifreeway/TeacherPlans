"""
Streamlit-интерфейс TeacherFactory.

Запуск: poetry run streamlit run src/teacherfactory/app.py
"""

import io
import json
import sys
import traceback
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from config import CONFIG  # noqa: E402
from embeddings import describe_embeddings  # noqa: E402
from generator import (  # noqa: E402
    COMPETENCY_RE,
    generate_lesson_card,
    render_docx,
    stream_chat_response,
    validate_competencies,
)
from indexer import INDEX_DIR, build_index  # noqa: E402
from llm_provider import (  # noqa: E402
    LLMProviderType,
    get_llm_provider,
    list_available_providers,
)

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


def get_provider_for_session(temperature: float | None = None):
    """Получить LLM-провайдер по выбору пользователя в sidebar."""
    selected_type = st.session_state.get("selected_llm_type")
    provider_type = LLMProviderType(selected_type) if selected_type else None
    return get_llm_provider(provider_type=provider_type, temperature=temperature)


def _format_exception(e: BaseException) -> str:
    """Человекочитаемое описание ошибки (некоторые исключения LangChain имеют пустой str())."""
    msg = str(e).strip()
    return f"{type(e).__name__}: {msg}" if msg else type(e).__name__


def _is_rate_limit(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    return (
        "rate_limit" in msg
        or "rate limit" in msg
        or "tokens per minute" in msg
        or "tpm" in msg
        or getattr(exc, "status_code", None) in (413, 429)
        or "RateLimit" in name
    )


def _show_error(prefix: str, exc: BaseException) -> None:
    if _is_rate_limit(exc):
        st.error(
            f"⏱️ Groq упёрся в лимит токенов в минуту (TPM). "
            f"На бесплатном тарифе у `llama-3.3-70b-versatile` лимит — 12k токенов/мин.\n\n"
            f"Что можно сделать:\n"
            f"- подождать минуту и повторить запрос;\n"
            f"- переключиться на `llama-3.1-8b-instant` в `config.local.toml` "
            f"(у неё лимит существенно выше);\n"
            f"- уменьшить контекст: `chat_k` и `chat_specialty_k` в `[rag]` "
            f"в `config.local.toml`."
        )
        with st.expander("Ответ Groq"):
            st.code(_format_exception(exc))
        return

    st.error(f"{prefix}: {_format_exception(exc)}")
    with st.expander("Подробности (traceback)"):
        st.code(traceback.format_exc())


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
        teacher, specialty, course, group, students = _sidebar()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_one, tab_batch, tab_chat = st.tabs(
        ["Один урок", "Пакетная генерация", "Чат с документами"]
    )

    with tab_one:
        _tab_single(teacher, specialty, course, group, students)

    with tab_batch:
        _tab_batch(teacher, specialty, course, group, students)

    with tab_chat:
        _tab_chat()


def _sidebar() -> tuple[str, str, int, str, int]:
    """Боковая панель: выбор LLM, индекс, общие сведения."""
    st.header("🔧 Настройки LLM")

    providers = list_available_providers()
    available = [p for p in providers if p["available"]]

    if not available:
        st.error("❌ Ни один LLM-провайдер не доступен.")
        st.info(
            "**Как настроить:**\n\n"
            "- **Ollama**: запустите `ollama serve` и загрузите модель.\n"
            "- **Groq**: добавьте API-ключ в `config.local.toml` "
            "или в переменную окружения `GROQ_API_KEY`.\n\n"
            "Бесплатный ключ Groq: https://console.groq.com/keys"
        )
        st.stop()

    current_type = st.session_state.get("selected_llm_type")
    default_idx = next(
        (i for i, p in enumerate(available) if p["type"] == current_type),
        0,
    )

    selected_idx = st.radio(
        "Провайдер:",
        options=range(len(available)),
        format_func=lambda i: f"{available[i]['name']} ({available[i]['model']})",
        index=default_idx,
        help="Groq — быстро, требует интернет. Ollama — локально, приватно.",
    )

    new_type = available[selected_idx]["type"]
    if new_type != current_type:
        st.session_state["selected_llm_type"] = new_type

    st.divider()
    st.subheader("Статус провайдеров")
    for p in providers:
        icon = "✅" if p["available"] else "❌"
        st.write(f"{icon} {p['name']}: `{p['model']}`")

    st.divider()
    st.header("Индекс документов")
    if index_ready():
        st.success("Индекс готов")
    else:
        st.warning("Индекс не построен")

    st.caption(f"Эмбеддинги: `{describe_embeddings()}`")
    st.caption(
        "При смене embeddings.provider в config.local.toml — обязательно "
        "перестрой индекс."
    )

    if st.button("Перестроить индекс", use_container_width=True):
        st.session_state.pop("last_index_build", None)
        with st.spinner("Индексирую PDF/DOCX из папки docs/..."):
            try:
                stats = build_index()
                st.session_state["last_index_build"] = {"ok": True, "stats": stats}
            except Exception as e:
                st.session_state["last_index_build"] = {
                    "ok": False,
                    "error": _format_exception(e),
                    "traceback": traceback.format_exc(),
                }

    last = st.session_state.get("last_index_build")
    if last:
        if last["ok"]:
            stats = last["stats"]
            st.success(
                f"✅ Индекс построен: {stats['chunks']} чанков из "
                f"{stats['documents']} документов "
                f"({stats['embeddings']}, dim={stats['dim']})."
            )
            if stats["skipped_doc"]:
                st.warning(
                    f"⚠️ Пропущено {len(stats['skipped_doc'])} .doc файлов "
                    f"(нужна конвертация в .docx): "
                    + ", ".join(f"`{f}`" for f in stats["skipped_doc"])
                )
        else:
            st.error(f"❌ Ошибка индексации: {last['error']}")
            with st.expander("Подробности (traceback)"):
                st.code(last["traceback"])

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
    st.header("Общие сведения")
    teacher = st.text_input("Преподаватель", "Иванов И.И.")
    specialty = st.text_input(
        "Специальность",
        "09.01.03 Оператор информационных систем и ресурсов",
    )
    group = st.text_input("Группа", "ОИСИР-21")
    course = st.number_input("Курс", min_value=1, max_value=4, value=2)
    students = st.number_input("Студентов в группе", min_value=1, max_value=60, value=25)

    return teacher, specialty, course, group, students


# ─── Helpers для предпросмотра ────────────────────────────────────────────────

def _render_competencies(text: str, validation: dict[str, bool]) -> None:
    """Выводит текст компетенций, подсвечивая непроверенные коды."""
    if not text or text.strip() == "Не указано в документах":
        st.markdown(f"*{text}*")
        return

    for line in text.strip().splitlines():
        codes_in_line = COMPETENCY_RE.findall(line)
        if not codes_in_line:
            st.markdown(line)
            continue
        unverified = [c for c in codes_in_line if validation.get(c) is False]
        st.markdown(f"{'⚠️' if unverified else '✅'} {line}")


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
        st.session_state.pop("single_bytes", None)

        params = make_params(
            discipline, specialty, course, group, students,
            topic, number, lesson_date, teacher, lesson_type, lesson_kind, duration,
        )
        fname = docx_filename(number, discipline)
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
                provider = get_provider_for_session(
                    temperature=CONFIG["model"]["temperature"]
                )
                stage_slot.markdown(f"**Провайдер: {provider.name} ({provider.config.model_name})**")

                card = generate_lesson_card(
                    params, provider=provider, on_token=on_token, on_stage=on_stage,
                )
                stage_slot.markdown("**Рендерю DOCX...**")
                token_slot.empty()
                render_docx(card, out_path)

                st.session_state["single_bytes"] = out_path.read_bytes()
                st.session_state["single_fname"] = fname
                st.session_state["single_card"] = card

                stage_slot.markdown("**Проверяю компетенции...**")
                st.session_state["validation"] = validate_competencies(card)
                status.update(label="Готово!", state="complete")
            except Exception as e:
                status.update(label=f"Ошибка: {_format_exception(e)}", state="error")
                _show_error("Не удалось сгенерировать карту", e)

    if "single_bytes" in st.session_state:
        card = st.session_state["single_card"]
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
            st.markdown(f"**Цель:** {card.goal}")

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

        provider = get_provider_for_session(temperature=CONFIG["model"]["temperature"])

        for i, topic in enumerate(topics):
            n = start_num + i
            d = start_date + timedelta(days=i * date_step)
            log_slot.text(f"[{i + 1}/{len(topics)}] {topic[:70]}...")

            params = make_params(
                discipline, specialty, course, group, students,
                topic, n, d, teacher, lesson_type, lesson_kind, duration,
            )
            try:
                card = generate_lesson_card(params, provider=provider)
                fname = docx_filename(n, discipline)
                out_path = OUTPUT_DIR / fname
                render_docx(card, out_path)
                docx_files[fname] = out_path.read_bytes()
            except Exception as e:
                errors.append(f"Урок {n} «{topic}»: {_format_exception(e)}")

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
    st.subheader("💬 Чат с документами")
    st.caption(
        "Задавай вопросы по учебным программам, компетенциям, требованиям ФГОС — "
        "без генерации файлов. Ответы генерируются на основе ваших документов."
    )

    if not index_ready():
        st.warning("Сначала постройте индекс документов — кнопка в боковой панели.")
        return

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("Спроси о программе, компетенциях, требованиях...")

    if question:
        with st.chat_message("user"):
            st.markdown(question)
        st.session_state["chat_history"].append({"role": "user", "content": question})

        with st.chat_message("assistant"):
            try:
                provider = get_provider_for_session(
                    temperature=CONFIG["model"]["chat_temperature"]
                )
                response = st.write_stream(stream_chat_response(question, provider=provider))
            except Exception as e:
                response = f"Ошибка: {_format_exception(e)}"
                _show_error("Не удалось получить ответ", e)

        st.session_state["chat_history"].append({"role": "assistant", "content": response})

    if st.session_state["chat_history"]:
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🗑️ Очистить", type="secondary", key="clear_chat"):
                st.session_state["chat_history"] = []
                st.rerun()
        with col2:
            export_data = {
                "chat_history": st.session_state["chat_history"],
                "export_date": datetime.now().isoformat(),
                "llm_provider": st.session_state.get("selected_llm_type", "unknown"),
            }
            st.download_button(
                label="📥 Скачать JSON",
                data=json.dumps(export_data, ensure_ascii=False, indent=2),
                file_name=f"chat_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
