"""
Тестовый скрипт для проверки связки LLM + Pydantic.

Запуск: poetry run python src/teacherfactory/test_llm.py
"""

from langchain_ollama import ChatOllama
from model import LessonCard


llm = ChatOllama(model="llama3.1:8b", temperature=0.1)
structured_llm = llm.with_structured_output(LessonCard)

try:
    result = structured_llm.invoke(
        "Составь технологическую карту урока по информатике на русском языке. "
        "Специальность: 09.02.07. Тема: Основы алгоритмизации. "
        "Преподаватель: Иванов И.И. Группа: ИСП-21. Курс: 2. "
        "Продолжительность: 90 минут. Включи 5 этапов."
    )
    print(f"Тема: {result.lesson_topic}")
    print(f"Цель: {result.goal}")
    print(f"Этапов: {len(result.lesson_structure)}")
    for step in result.lesson_structure:
        print(f"  {step.number}. {step.stage} ({step.time})")
    print("\nОК — модели работают!")
except Exception as e:
    print(f"Ошибка: {e}")