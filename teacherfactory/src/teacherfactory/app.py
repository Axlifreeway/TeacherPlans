"""
Streamlit-точка входа TeacherFactory.

Запуск: poetry run streamlit run src/teacherfactory/app.py
"""

import streamlit as st

from teacherfactory.auth import logout, render_user_admin, require_auth
from teacherfactory.views import batch, chat, single
from teacherfactory.views.sidebar import render_sidebar


def main() -> None:
    st.set_page_config(
        page_title="TeacherFactory",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Гейт: без логина дальше скрипт не идёт.
    user = require_auth()

    st.title("TeacherFactory")
    st.caption("Генератор технологических карт уроков для СПО")

    with st.sidebar:
        st.success(f"👤 {user.username} ({user.role})")
        if st.button("Выйти", use_container_width=True):
            logout()
            st.rerun()
        st.divider()
        teacher, specialty, course, group, students = render_sidebar()

    tabs = ["Один урок", "Пакетная генерация", "Чат с документами"]
    if user.role == "admin":
        tabs.append("Пользователи")

    rendered = st.tabs(tabs)

    with rendered[0]:
        single.render(teacher, specialty, course, group, students)
    with rendered[1]:
        batch.render(teacher, specialty, course, group, students)
    with rendered[2]:
        chat.render()
    if user.role == "admin":
        with rendered[3]:
            render_user_admin(user)


if __name__ == "__main__":
    main()
