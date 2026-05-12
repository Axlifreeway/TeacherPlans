"""
Streamlit-точка входа TeacherFactory.

Запуск: poetry run streamlit run src/teacherfactory/app.py
"""

import streamlit as st

from teacherfactory.views import batch, chat, single
from teacherfactory.views.sidebar import render_sidebar


def main() -> None:
    st.set_page_config(
        page_title="TeacherFactory",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("TeacherFactory")
    st.caption("Генератор технологических карт уроков для СПО")

    with st.sidebar:
        teacher, specialty, course, group, students = render_sidebar()

    tab_one, tab_batch, tab_chat = st.tabs(["Один урок", "Пакетная генерация", "Чат с документами"])

    with tab_one:
        single.render(teacher, specialty, course, group, students)

    with tab_batch:
        batch.render(teacher, specialty, course, group, students)

    with tab_chat:
        chat.render()


if __name__ == "__main__":
    main()
