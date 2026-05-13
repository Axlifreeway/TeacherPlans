"""
Pydantic-модели документов.

Каждая модель соответствует переменным в соответствующем шаблоне docx
(см. `documents/<slug>.py`). LLM генерирует данные в формате этих моделей,
Pydantic валидирует структуру, а docxtpl подставляет в шаблон.

Файл содержит:
  - LessonCard — технологическая карта урока (эталон Алёшкина);
  - AssessmentMaterials — оценочные материалы (КОС/ФОС) по дисциплине.
"""

from pydantic import BaseModel, Field

class LessonTasks(BaseModel):
    """Задачи занятия."""
    educational: str = Field(description="Образовательные (дидактические) задачи (список через ;)")
    developmental: str = Field(description="Развивающие задачи (список через ;)")
    upbringing: str = Field(description="Воспитательные задачи (список через ;)")
    perspective: str = Field(description="Перспективные задачи (список через ;)")
    personal: str = Field(description="Развитие персональных навыков преподавания (список через ;)")

class LearningOutcome(BaseModel):
    """Результаты обучения: знания, умения, навыки (Таблица 3)."""
    type: str = Field(description="Тип результата: 'Знания', 'Умения' или 'Навыки'")
    code: str = Field(description="Код результата (например, З-8, У-8, Н-3)")
    name: str = Field(description="Формулировка результата (что именно знает/умеет)")
    indicator: str = Field(description="Показатель результата (конкретное измеримое действие студента)")

class Competency(BaseModel):
    """Формируемые общие и профессиональные компетенции (Таблица 4)."""
    code: str = Field(description="Код компетенции (например, ОК.01, ПК 1.2)")
    name: str = Field(description="Наименование компетенции")
    indicator: str = Field(description="Показатель результата сформированности компетенции")

class InterdisciplinaryConnection(BaseModel):
    """Межпредметные связи (Таблица 5)."""
    outcome_source: str = Field(description="Результат обучения из смежной дисциплины (код и текст)")
    discipline: str = Field(description="Наименование смежной дисциплины / МДК")
    topic: str = Field(description="Раздел, тема дисциплины по межпредметной связи")
    outcome_target: str = Field(description="Результат обучения на текущем занятии, который формируется благодаря связи")
    indicator: str = Field(description="Показатель обучения")

class TeachingMethodsTable(BaseModel):
    """Методы обучения (Таблица 6)."""
    by_source: str = Field(description="По источникам получения знаний (словесные, наглядные, практические)")
    by_character: str = Field(description="По характеру познавательной деятельности (проблемные, частично-поисковые)")
    by_independence: str = Field(description="По степени самостоятельности")
    health_saving: str = Field(description="Здоровьесберегающие методы")

class LessonStep(BaseModel):
    """Этап хода урока (строка таблицы 7).

    Только number/stage/time/teacher/student обязательны — остальные поля
    опциональны: иначе одна пропущенная ячейка в одном из 7-10 этапов
    валит весь Groq tool call.
    """

    number: int = Field(description="Порядковый номер этапа занятия")
    stage: str = Field(description="Название этапа (например: 'Организационный')")
    time: str = Field(description="Время, отведённое на этап (например: '5')")
    teacher: str = Field(description="Деятельность преподавателя")
    student: str = Field(description="Деятельность обучающихся")
    substage: str = Field(
        default="", description="Подэтап (например: 'Актуализация опорных знаний')"
    )
    tasks: str = Field(default="", description="Задачи этапа")
    result: str = Field(default="", description="Планируемые результаты этапа")
    methods: str = Field(default="", description="Приёмы обучения на этапе")
    means: str = Field(default="", description="Средства обучения на этапе")
    control: str = Field(default="", description="Форма и метод контроля")

class Resources(BaseModel):
    """Учебно-методическое обеспечение занятия. Все списки опциональны —
    Groq strict tool-validation падает, если LLM дропнет хоть один required-список."""

    literature_main: list[str] = Field(
        default_factory=list,
        description="Основная литература (реальные книги с ISBN и URL)",
    )
    literature_additional: list[str] = Field(
        default_factory=list,
        description="Дополнительная литература (реальные книги с ISBN и URL)",
    )
    databases: list[str] = Field(
        default_factory=list,
        description="Современные профессиональные базы данных и справочные системы",
    )
    normative_docs: list[str] = Field(
        default_factory=list,
        description="Нормативно-правовая документация (ГОСТы, стандарты)",
    )
    software: list[str] = Field(
        default_factory=list,
        description="Лицензионное и свободно распространяемое ПО",
    )
    internet_resources: list[str] = Field(default_factory=list, description="Интернет-ресурсы")

class LessonCard(BaseModel):
    """
    Технологическая карта урока — корневая модель.
    """
    # Заголовок и инфо
    discipline: str = Field(description="Наименование дисциплины / МДК")
    specialty: str = Field(description="Специальность (код и наименование)")
    course_number: int = Field(description="Номер курса обучения")
    group_name: str = Field(description="Название учебной группы")
    students_count: int = Field(description="Количество студентов")
    lesson_topic: str = Field(description="Тема занятия")
    duration: int = Field(description="Продолжительность занятия в минутах")
    teacher_name: str = Field(description="ФИО преподавателя")
    
    lesson_type: str = Field(description="Тип урока")
    lesson_kind: str = Field(description="Вид урока")
    # Декоративные поля делаем опциональными: Groq strict tool-validation падает,
    # если LLM пропустит хоть одно required-поле, а llama-3.3-70b при 30+
    # полевой схеме иногда дропает именно «второстепенные». Дефолт = ""
    # → поле не required в JSON-схеме, ничего не ломается, LLM всё равно
    # пытается заполнить по подсказкам в промпте.
    pedagogical_technologies: str = Field(
        default="", description="Педагогическая технология (её элементы)"
    )

    # Цель, задачи, эпиграф
    goal: str = Field(description="Цель занятия")
    tasks: LessonTasks = Field(description="Задачи занятия")
    epigraph: str = Field(default="", description="Эпиграф к уроку (цитата)")
    epigraph_author: str = Field(default="", description="Автор эпиграфа")

    # Формы, приёмы, средства
    organization_forms: list[str] = Field(
        default_factory=list,
        description="Формы организации учебной деятельности",
    )
    teaching_techniques: list[str] = Field(
        default_factory=list, description="Приёмы обучения (через дефис)"
    )
    methodological_support: list[str] = Field(
        default_factory=list, description="Методическое обеспечение"
    )
    teaching_means: str = Field(
        default="", description="Средства обучения (компьютеры, ПО, доска)"
    )
    
    # Таблицы 3-7
    learning_outcomes: list[LearningOutcome] = Field(description="Результаты обучения (Таблица 3)")
    competencies: list[Competency] = Field(description="Компетенции (Таблица 4)")
    interdisciplinary_connections: list[InterdisciplinaryConnection] = Field(
        default_factory=list, description="Межпредметные связи (Таблица 5)"
    )
    teaching_methods_table: TeachingMethodsTable = Field(description="Методы обучения (Таблица 6)")
    lesson_structure: list[LessonStep] = Field(description="Ход занятия (Таблица 7)")

    # Ресурсы
    resources: Resources = Field(description="Обеспечение занятия (книги, базы, ПО)")

    def to_template_context(self) -> dict:
        def _bulleted(items: list[str]) -> str:
            """Список строк → многострочный текст с маркером «— » у каждой."""
            return "\n".join(f"— {item}" for item in items if item)

        def _task_field(value: str) -> str:
            """Строку задач (LLM возвращает через «; ») красим в маркеры «— »."""
            parts = [p.strip(" ;") for p in value.replace("\n", ";").split(";")]
            parts = [p for p in parts if p]
            return _bulleted(parts) if parts else value

        return {
            "discipline": self.discipline,
            "specialty": self.specialty,
            "course_number": self.course_number,
            "group_name": self.group_name,
            "students_count": self.students_count,
            "lesson_topic": self.lesson_topic,
            "lesson_type": self.lesson_type,
            "lesson_kind": self.lesson_kind,
            "duration": self.duration,
            "teacher_name": self.teacher_name,
            "pedagogical_technologies": self.pedagogical_technologies,
            "goal": self.goal,
            "task_educational": _task_field(self.tasks.educational),
            "task_developmental": _task_field(self.tasks.developmental),
            "task_upbringing": _task_field(self.tasks.upbringing),
            "task_perspective": _task_field(self.tasks.perspective),
            "task_personal": _task_field(self.tasks.personal),
            "epigraph": self.epigraph,
            "epigraph_author": self.epigraph_author,
            "teaching_means": self.teaching_means,
            "organization_forms": _bulleted(self.organization_forms),
            "teaching_techniques": _bulleted(self.teaching_techniques),
            "methodological_support": _bulleted(self.methodological_support),
            "learning_outcomes": [item.model_dump() for item in self.learning_outcomes],
            "competencies": [item.model_dump() for item in self.competencies],
            "interdisciplinary_connections": [
                item.model_dump() for item in self.interdisciplinary_connections
            ],
            "method_source": self.teaching_methods_table.by_source,
            "method_character": self.teaching_methods_table.by_character,
            "method_independence": self.teaching_methods_table.by_independence,
            "method_health": self.teaching_methods_table.health_saving,
            "lesson_structure": [step.model_dump() for step in self.lesson_structure],
            "lit_main": _bulleted(self.resources.literature_main),
            "lit_add": _bulleted(self.resources.literature_additional),
            "databases": _bulleted(self.resources.databases),
            "normative_docs": _bulleted(self.resources.normative_docs),
            "software": _bulleted(self.resources.software),
            "internet_resources": _bulleted(self.resources.internet_resources),
        }


# ─── Оценочные материалы (КОС / ФОС) ──────────────────────────────────────────


class AssessmentPassportRow(BaseModel):
    """Одна строка «Паспорта ОМ» (таблица 1 в шаблоне)."""

    topic: str = Field(description="Тема дисциплины из тематического плана РПД")
    tool: str = Field(
        description="Оценочное средство (например: 'Тест в количестве 15 заданий', "
        "'Контрольная работа', 'Реферат')"
    )
    competencies: str = Field(
        description="Коды и формулировки компетенций для темы (через перевод строки)"
    )
    criteria: str = Field(
        description="Критерии оценивания: чёткое описание шкалы (отл/хор/удовл/неуд)"
    )


class AssessmentCompetencySummary(BaseModel):
    """Сводка по компетенции (таблица 'Код | Наименование | Количество заданий')."""

    code: str = Field(description="Код компетенции (ОК 01, ПК 1.2 и т.п.)")
    name: str = Field(description="Полное наименование компетенции")
    items_count: int = Field(description="Количество тестовых заданий по компетенции")


class AssessmentTestItem(BaseModel):
    """Типовое тестовое задание (для тестовой формы контроля)."""

    competency_code: str = Field(description="Код компетенции, к которой относится задание")
    number: int = Field(description="Порядковый номер задания в тесте")
    instruction_and_task: str = Field(
        description="Инструкция + текст задания. Например: "
        "'Выберите правильный вариант ответа. Чему равна производная sin(x)? а) cos x ...'"
    )
    answer_key: str = Field(description="Правильный ответ (ключ), однозначный")


class AssessmentMaterials(BaseModel):
    """Оценочные материалы (ОМ / ФОС) по дисциплине — корневая модель."""

    discipline: str = Field(description="Наименование дисциплины / МДК")
    specialty: str = Field(description="Специальность (код и наименование)")
    semester: int = Field(description="Номер семестра, в котором проводится контроль")
    final_form: str = Field(
        description="Форма промежуточной аттестации: 'зачёт', "
        "'дифференцированный зачёт', 'экзамен'"
    )

    grading_system: str = Field(
        description="Описание системы оценивания (2-3 предложения): "
        "применяемая шкала, краткое описание подхода"
    )

    passport_rows: list[AssessmentPassportRow] = Field(
        description="Паспорт ОМ: список оценочных средств по темам (минимум 5)"
    )
    competency_summary: list[AssessmentCompetencySummary] = Field(
        description="Сводка по компетенциям: код, наименование, число заданий"
    )
    test_items: list[AssessmentTestItem] = Field(
        description="Типовые тестовые задания (минимум 10 для тестовой формы)"
    )

    def to_template_context(self) -> dict:
        total_items = sum(s.items_count for s in self.competency_summary)
        return {
            "discipline": self.discipline,
            "specialty": self.specialty,
            "semester": self.semester,
            "final_form": self.final_form,
            "grading_system": self.grading_system,
            "passport_rows": [row.model_dump() for row in self.passport_rows],
            "competency_summary": [s.model_dump() for s in self.competency_summary],
            "competency_total": total_items,
            "test_items": [item.model_dump() for item in self.test_items],
        }
