"""Быстрая проверка: рендерим LessonCard-заглушку через docxtpl на шаблоне.

Запуск: poetry run python scratch/test_render.py
"""

from pathlib import Path

from teacherfactory.documents.lesson_card import LESSON_CARD
from teacherfactory.model import (
    Competency,
    InterdisciplinaryConnection,
    LearningOutcome,
    LessonCard,
    LessonStep,
    LessonTasks,
    Resources,
    TeachingMethodsTable,
)
from teacherfactory.render import render_document


def stub() -> LessonCard:
    return LessonCard(
        discipline="ОПЦ.03 Базы данных",
        specialty="09.01.03 Оператор информационных систем и ресурсов",
        course_number=1,
        group_name="ОИС-25-1",
        students_count=22,
        lesson_topic="Основы SQL: SELECT с WHERE и ORDER BY",
        duration=45,
        teacher_name="Алёшкин А.А.",
        lesson_type="Урок закрепления знаний",
        lesson_kind="Лабораторное занятие",
        pedagogical_technologies="Метод контекстного обучения, ИКТ",
        goal="Сформировать умение составлять SQL-запросы SELECT с условием WHERE и сортировкой ORDER BY.",
        tasks=LessonTasks(
            educational="Повторить понятия таблицы, поля, первичного ключа; объяснить синтаксис SELECT",
            developmental="Развивать аналитическое мышление; умение переводить задачу в SQL",
            upbringing="Воспитывать точность и аккуратность",
            perspective="Применение SQL в профессиональной деятельности оператора ИС",
            personal="Отработать приём контекстного обучения",
        ),
        epigraph="Искусство программирования — организовать сложность.",
        epigraph_author="Дональд Кнут",
        organization_forms=["групповая работа", "индивидуальная работа"],
        teaching_techniques=[
            "обсуждение проблемных ситуаций",
            "конструктор ГОСТ-терминов",
            "составление SQL-запросов в браузере",
        ],
        methodological_support=["методическая разработка занятия", "электронная тетрадь"],
        teaching_means="Компьютер, проектор, Яндекс.Браузер, электронная тетрадь.",
        learning_outcomes=[
            LearningOutcome(
                type="Знания",
                code="З-8",
                name="принципа организации информации в БД",
                indicator="Объясняет структуру таблицы и понятия поле/запись",
            ),
            LearningOutcome(
                type="Знания",
                code="З-9",
                name="синтаксиса SQL",
                indicator="Знает назначение SELECT, WHERE, ORDER BY",
            ),
            LearningOutcome(
                type="Умения",
                code="У-8",
                name="составлять SQL-запросы",
                indicator="Пишет SELECT с WHERE без ошибок",
            ),
            LearningOutcome(
                type="Навыки",
                code="Н-4",
                name="формирования запросов к БД",
                indicator="Самостоятельно формирует запросы и читает результат",
            ),
        ],
        competencies=[
            Competency(
                code="ОК 01",
                name="Выбирать способы решения задач профессиональной деятельности",
                indicator="Анализирует задачу и выбирает SQL-конструкцию",
            ),
            Competency(
                code="ПК 1.6",
                name="Формировать запросы для получения информации в базах данных",
                indicator="Составляет SELECT-запросы с условиями и сортировкой",
            ),
        ],
        interdisciplinary_connections=[
            InterdisciplinaryConnection(
                outcome_source="З-1 лексика по теме данных",
                discipline="Иностранный язык в проф. деятельности",
                topic="Тема 2.3. Терминология БД",
                outcome_target="Понимает англоязычные ключевые слова SQL",
                indicator="Объясняет назначение SELECT/WHERE на английском",
            ),
        ],
        teaching_methods_table=TeachingMethodsTable(
            by_source="Словесные: беседа\nНаглядные: схема БД\nПрактические: SQL-конструктор",
            by_character="Проблемные: целеполагание\nЧастично-поисковый: ГОСТ-конструктор",
            by_independence="Тьюторское сопровождение\nИндивидуальная работа",
            health_saving="Физкультминутка, ТБ, эргономика рабочего места",
        ),
        lesson_structure=[
            LessonStep(
                number=1, stage="Организационный", substage="Организационный", time="2",
                tasks="Организовать обучающихся, проверить готовность",
                result="Группа готова к работе",
                methods="Беседа, внешний осмотр",
                means="Слово, электронная тетрадь",
                teacher="Приветствует студентов, проверяет посещаемость, объясняет порядок работы с электронной тетрадью.",
                student="Приветствуют преподавателя, готовят рабочие места, знакомятся с тетрадью.",
                control="Зрительный контроль, внешний осмотр.",
            ),
            LessonStep(
                number=2, stage="Основной", substage="Демонстрация", time="20",
                tasks="Показать структуру таблицы и SELECT-запросы",
                result="Студенты увидели разбор SELECT, WHERE, ORDER BY",
                methods="Показательный пример, наглядный",
                means="Проектор, доска",
                teacher="Показывает схему таблицы (поля, типы данных, PK). Демонстрирует SELECT *, SELECT WHERE id=5, SELECT ORDER BY name.",
                student="Наблюдают, конспектируют, прогнозируют результат запроса.",
                control="Демонстрация, проверка прогнозов",
            ),
            LessonStep(
                number=3, stage="Заключительный", substage="Рефлексия", time="23",
                tasks="Обобщить, оценить",
                result="ПОПС-эссе написано, оценки выставлены",
                methods="ПОПС-формула",
                means="Электронная тетрадь",
                teacher="Возвращается к цели; просит написать ПОПС-эссе «Зачем нужен SQL оператору ИС».",
                student="Пишут эссе, сверяют работу с эталоном.",
                control="Самооценка по критериям",
            ),
        ],
        resources=Resources(
            literature_main=["Советов Б.Я. Базы данных. Юрайт, 2025. ISBN 978-5-534-18784-7."],
            literature_additional=["Илюшечкин В.М. Основы баз данных. Юрайт, 2025."],
            databases=["КонсультантПлюс — http://www.consultant.ru/"],
            normative_docs=["ГОСТ 33707—2016. Информационные технологии. Словарь."],
            software=["Антивирусное ПО Kaspersky"],
            internet_resources=["https://axlifreeway.github.io/lesson"],
        ),
    )


def main() -> None:
    out = Path("scratch/test_output.docx")
    out.parent.mkdir(exist_ok=True)
    render_document(LESSON_CARD, stub(), out)
    print(f"OK render -> {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
