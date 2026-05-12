"""
Боковая панель: выбор LLM, управление индексом, общие сведения.
"""

import traceback

import streamlit as st

from teacherfactory.embeddings import describe_embeddings
from teacherfactory.indexer import build_index
from teacherfactory.llm_provider import list_available_providers
from teacherfactory.paths import INDEX_DIR, SKIPPED_DOC_PATH
from teacherfactory.views.common import index_ready
from teacherfactory.views.errors import format_exception


def render_sidebar() -> tuple[str, str, int, str, int]:
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
    _render_index_block()

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


def _render_index_block() -> None:
    st.header("Индекс документов")
    if index_ready():
        st.success("Индекс готов")
    else:
        st.warning("Индекс не построен")

    st.caption(f"Эмбеддинги: `{describe_embeddings()}`")
    st.caption("При смене embeddings.provider в config.local.toml — обязательно перестрой индекс.")

    if st.button("Перестроить индекс", use_container_width=True):
        st.session_state.pop("last_index_build", None)
        with st.spinner("Индексирую PDF/DOCX из папки docs/..."):
            try:
                stats = build_index()
                st.session_state["last_index_build"] = {"ok": True, "stats": stats}
            except Exception as e:
                st.session_state["last_index_build"] = {
                    "ok": False,
                    "error": format_exception(e),
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

    if SKIPPED_DOC_PATH.exists():
        skipped = SKIPPED_DOC_PATH.read_text(encoding="utf-8").strip().splitlines()
        if skipped:
            st.warning(
                f"⚠️ {len(skipped)} файл(ов) **не проиндексированы** "
                f"(формат .doc не поддерживается):\n\n"
                + "\n".join(f"- `{f}`" for f in skipped)
                + "\n\nСконвертируй через Word → «Сохранить как .docx»."
            )

    _ = INDEX_DIR  # touch — пригодится в будущем для очистки.
