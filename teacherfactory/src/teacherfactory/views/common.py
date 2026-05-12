"""
Утилиты, общие для всех вкладок UI.
"""

import streamlit as st

from teacherfactory.llm_provider import (
    LLMProvider,
    LLMProviderType,
    get_llm_provider,
)
from teacherfactory.paths import INDEX_DIR


def index_ready() -> bool:
    return INDEX_DIR.exists() and any(INDEX_DIR.iterdir())


def get_provider_for_session(temperature: float | None = None) -> LLMProvider:
    """LLM-провайдер по выбору пользователя в sidebar."""
    selected_type = st.session_state.get("selected_llm_type")
    provider_type = LLMProviderType(selected_type) if selected_type else None
    return get_llm_provider(provider_type=provider_type, temperature=temperature)
