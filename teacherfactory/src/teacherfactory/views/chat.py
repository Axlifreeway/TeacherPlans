"""
Вкладка «Чат с документами».
"""

import json
from datetime import datetime

import streamlit as st

from teacherfactory.config import CONFIG
from teacherfactory.pipeline import stream_chat_response
from teacherfactory.views.common import get_provider_for_session, index_ready
from teacherfactory.views.errors import format_exception, show_error


def render() -> None:
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
                provider = get_provider_for_session(temperature=CONFIG["model"]["chat_temperature"])
                response = st.write_stream(stream_chat_response(question, provider=provider))
            except Exception as e:
                response = f"Ошибка: {format_exception(e)}"
                show_error("Не удалось получить ответ", e)

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
