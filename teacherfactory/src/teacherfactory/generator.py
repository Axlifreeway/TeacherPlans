"""
Генератор технологических карт уроков.

Пайплайн: RAG-поиск по документам → LLM-генерация → DOCX-рендеринг.

Запуск: poetry run python src/teacherfactory/generator.py
"""

from pathlib import Path
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from docxtpl import DocxTemplate

from model import LessonCard


# Пути
PROJECT_ROOT = Path(__file__).parent.parent.parent
# FAISS не может работать с кириллическими путями
INDEX_DIR = Path.home() / ".teacherfactory" / "faiss_index"
TEMPLATE_PATH = PROJECT_ROOT / "template_fixed.docx"
OUTPUT_DIR = Path.home() / ".teacherfactory" / "output"


SYSTEM_PROMPT = """Ты — опытный методист среднего профессионального образования (СПО) в России.
Твоя задача — составить технологическую карту урока строго на русском языке.

Используй ТОЛЬКО информацию из предоставленного контекста нормативных документов.
Компетенции (ОК, ПК), знания, умения и навыки бери ТОЛЬКО из контекста.
Не выдумывай коды компетенций — если в контексте нет нужной информации, напиши "Не указано в документах".

КОНТЕКСТ ИЗ НОРМАТИВНЫХ ДОКУМЕНТОВ:
{context}
"""

USER_PROMPT = """Составь технологическую карту урока со следующими параметрами:

Дисциплина: {discipline}
Специальность: {specialty}
Курс: {course_number}
Группа: {group_name}
Количество студентов: {students_count}
Тема занятия: {lesson_topic}
Номер занятия: {lesson_number}
Дата: {date}
Преподаватель: {teacher_name}
Тип урока: {lesson_type}
Вид занятия: {lesson_kind}
Продолжительность: {duration} минут

Включи 5-7 этапов в ход занятия. Все тексты — на русском языке.
"""


def load_index() -> FAISS:
    """Загрузить FAISS-индекс с диска."""
    if not INDEX_DIR.exists() or not any(INDEX_DIR.iterdir()):
        raise FileNotFoundError(
            f"FAISS-индекс не найден в {INDEX_DIR}. "
            "Сначала запусти indexer.py: poetry run python src/teacherfactory/indexer.py"
        )
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    return FAISS.load_local(str(INDEX_DIR), embeddings, allow_dangerous_deserialization=True)


def retrieve_context(db: FAISS, query: str, k: int = 5) -> str:
    """Найти релевантные куски из документов."""
    docs = db.similarity_search(query, k=k)
    context_parts = []
    for doc in docs:
        source = Path(doc.metadata.get("source", "неизвестно")).name
        page = doc.metadata.get("page", "?")
        context_parts.append(f"[Источник: {source}, стр. {page}]\n{doc.page_content}")
    return "\n\n---\n\n".join(context_parts)


def generate_lesson_card(params: dict) -> LessonCard:
    """
    Сгенерировать технологическую карту урока.

    params — словарь с параметрами урока:
        discipline, specialty, course_number, group_name, students_count,
        lesson_topic, lesson_number, date, teacher_name,
        lesson_type, lesson_kind, duration
    """
    # 1. Загрузка индекса
    print("Загружаю индекс...")
    db = load_index()

    # 2. RAG: поиск релевантного контекста
    search_query = f"{params['discipline']} {params['specialty']} компетенции знания умения навыки"
    print(f"Ищу контекст по запросу: {search_query[:80]}...")
    context = retrieve_context(db, search_query)
    print(f"Найдено {context.count('[Источник:')} релевантных фрагментов")

    # 3. Формирование промпта
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT),
    ])

    # 4. LLM с structured output
    llm = ChatOllama(model="llama3.1:8b", temperature=0.1, num_gpu=0)
    structured_llm = llm.with_structured_output(LessonCard)

    # 5. Собираем цепочку: промпт → LLM
    chain = prompt | structured_llm

    # 6. Вызов
    print("Генерирую технологическую карту (это может занять 1-2 минуты)...")
    result = chain.invoke({
        "context": context,
        **params,
    })

    print(f"Карта сгенерирована: {result.lesson_topic}")
    return result


def render_docx(card: LessonCard, output_path: Path) -> Path:
    """Отрендерить технологическую карту в DOCX через шаблон."""
    doc = DocxTemplate(str(TEMPLATE_PATH))
    context = card.to_template_context()

    # docxtpl автоматически обрабатывает {% tr %} тег при рендеринге,
    # но нужно убедиться что шаблон корректно загружен
    try:
        doc.render(context)
    except Exception as e:
        # Если шаблон имеет проблемы с {% tr %}, попробуем без таблицы
        print(f"Предупреждение при рендеринге: {e}")
        print("Пробую сохранить без рендеринга таблицы хода занятия...")
        # Убираем lesson_structure и рендерим без неё
        context_without_table = {k: v for k, v in context.items() if k != "lesson_structure"}
        context_without_table["lesson_structure"] = []
        doc = DocxTemplate(str(TEMPLATE_PATH))
        doc.render(context_without_table)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    print(f"Документ сохранён: {output_path}")
    return output_path


def main():
    """Пример генерации одной карты."""

    # Параметры урока — меняй под свои нужды
    params = {
        "discipline": "Компьютерные сети",
        "specialty": "09.01.03 Оператор информационных систем и ресурсов",
        "course_number": 2,
        "group_name": "ОИСИР-21",
        "students_count": 25,
        "lesson_topic": "Основы сетевых протоколов",
        "lesson_number": 1,
        "date": "08.05.2026",
        "teacher_name": "Иванов И.И.",
        "lesson_type": "комбинированный урок",
        "lesson_kind": "лекция",
        "duration": 90,
    }

    try:
        # Генерация
        card = generate_lesson_card(params)

        # Рендеринг в DOCX
        output_file = OUTPUT_DIR / f"Урок_{params['lesson_number']}_{params['discipline']}.docx"
        render_docx(card, output_file)

        # Вывод результата
        print("\n=== РЕЗУЛЬТАТ ===")
        print(f"Тема: {card.lesson_topic}")
        print(f"Цель: {card.goal}")
        print(f"ОК: {card.competencies_ok}")
        print(f"ПК: {card.competencies_pk}")
        print(f"Этапов: {len(card.lesson_structure)}")
        for step in card.lesson_structure:
            print(f"  {step.number}. {step.stage} ({step.time})")

    except FileNotFoundError as e:
        print(f"Ошибка: {e}")
    except Exception as e:
        print(f"Ошибка генерации: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
