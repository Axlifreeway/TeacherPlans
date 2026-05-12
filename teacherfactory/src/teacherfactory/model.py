"""
Pydantic-модели для технологической карты урока.

Каждая модель соответствует переменным в template.docx.
LLM генерирует данные в формате этих моделей,
Pydantic валидирует структуру, а docxtpl подставляет в шаблон.
"""

from pydantic import BaseModel, Field


class LessonStep(BaseModel):
    """Этап хода урока (строка таблицы 'Ход занятия')."""

    number: int = Field(description="Порядковый номер этапа занятия")
    stage: str = Field(
        description="Название этапа (например: 'Организационный момент', "
        "'Актуализация знаний', 'Изучение нового материала')"
    )
    time: str = Field(description="Время, отведённое на этап (например: '5 мин', '20 мин')")
    teacher: str = Field(description="Деятельность преподавателя на данном этапе")
    student: str = Field(description="Деятельность студентов на данном этапе")
    methods: str = Field(description="Методы и приёмы обучения, применяемые на этапе")
    result: str = Field(description="Планируемый результат этапа")


class LessonTasks(BaseModel):
    """Задачи занятия: образовательная, развивающая, воспитательная, педагогическая."""

    educational: str = Field(description="Образовательная задача занятия")
    developmental: str = Field(description="Развивающая задача занятия")
    upbringing: str = Field(description="Воспитательная задача занятия")
    pedagogical: str = Field(description="Педагогическая задача (методическая цель преподавателя)")


class PlannedOutcomes(BaseModel):
    """Планируемые результаты: знания, умения, навыки с индикаторами и формами контроля."""

    knowledge_indicator: str = Field(
        description="Индикатор достижения результата по знаниям (что студент должен знать)"
    )
    knowledge_control: str = Field(
        description="Форма контроля знаний (например: 'устный опрос', 'тестирование')"
    )
    skill_indicator: str = Field(
        description="Индикатор достижения результата по умениям (что студент должен уметь)"
    )
    skill_control: str = Field(
        description="Форма контроля умений (например: 'практическая работа', 'решение задач')"
    )
    ability_indicator: str = Field(
        description="Индикатор достижения результата по навыкам "
        "(практический опыт, которым должен владеть студент)"
    )
    ability_control: str = Field(
        description="Форма контроля навыков (например: 'лабораторная работа', 'демонстрация')"
    )


class Resources(BaseModel):
    """Учебно-методическое обеспечение занятия."""

    literature: str = Field(description="Основная и дополнительная литература")
    internet_resources: str = Field(description="Интернет-ресурсы (ЭБС, сайты, порталы)")
    other_materials: str = Field(description="Другие материалы (раздатки, оборудование, ПО)")


class LessonCard(BaseModel):
    """
    Технологическая карта урока — корневая модель.

    Все поля маппятся на jinja-переменные шаблона template.docx
    через метод to_template_context().
    """

    # --- Заголовок ---
    lesson_number: int = Field(description="Порядковый номер занятия")
    date: str = Field(description="Дата проведения занятия (формат: 'ДД.ММ.ГГГГ')")
    group_name: str = Field(description="Название учебной группы")
    students_count: int = Field(description="Количество студентов в группе")

    # --- Основная информация ---
    discipline: str = Field(description="Наименование дисциплины / МДК")
    specialty: str = Field(
        description="Специальность (код и наименование, "
        "например: '09.02.07 Информационные системы и программирование')"
    )
    course_number: int = Field(description="Номер курса обучения")
    lesson_topic: str = Field(description="Тема занятия")
    lesson_type: str = Field(
        description="Тип занятия (например: 'комбинированный урок', "
        "'урок изучения нового материала')"
    )
    lesson_kind: str = Field(
        description="Вид занятия (например: 'лекция', 'практическое занятие', "
        "'лабораторная работа')"
    )
    duration: int = Field(description="Продолжительность занятия в минутах (обычно 45 или 90)")
    teacher_name: str = Field(description="ФИО преподавателя")

    # --- Цель и задачи ---
    goal: str = Field(description="Цель занятия")
    tasks: LessonTasks = Field(description="Задачи занятия")

    # --- Компетенции ---
    competencies_ok: str = Field(
        description="Общие компетенции (ОК) с кодами и формулировками, формируемые на занятии"
    )
    competencies_pk: str = Field(
        description="Профессиональные компетенции (ПК) с кодами и формулировками, "
        "формируемые на занятии"
    )

    # --- Планируемые результаты ---
    outcomes: PlannedOutcomes = Field(description="Планируемые результаты (знания, умения, навыки)")

    # --- Ресурсы ---
    resources: Resources = Field(description="Учебно-методическое обеспечение")

    # --- Ход занятия ---
    lesson_structure: list[LessonStep] = Field(description="Ход занятия — список этапов урока")

    def to_template_context(self) -> dict:
        """
        Преобразует модель в плоский словарь для docxtpl.

        Ключи словаря точно совпадают с именами jinja-переменных в template.docx.
        """
        return {
            # Заголовок
            "lesson_number": self.lesson_number,
            "date": self.date,
            "group_name": self.group_name,
            "students_count": self.students_count,
            # Основная информация
            "discipline": self.discipline,
            "specialty": self.specialty,
            "course_number": self.course_number,
            "lesson_topic": self.lesson_topic,
            "lesson_type": self.lesson_type,
            "lesson_kind": self.lesson_kind,
            "duration": self.duration,
            "teacher_name": self.teacher_name,
            # Цель и задачи
            "goal": self.goal,
            "task_educational": self.tasks.educational,
            "task_developmental": self.tasks.developmental,
            "task_upbringing": self.tasks.upbringing,
            "task_pedagogical": self.tasks.pedagogical,
            # Компетенции
            "competencies_ok": self.competencies_ok,
            "competencies_pk": self.competencies_pk,
            # Планируемые результаты
            "knowledge_indicator": self.outcomes.knowledge_indicator,
            "knowledge_control": self.outcomes.knowledge_control,
            "skill_indicator": self.outcomes.skill_indicator,
            "skill_control": self.outcomes.skill_control,
            "ability_indicator": self.outcomes.ability_indicator,
            "ability_control": self.outcomes.ability_control,
            # Ресурсы
            "literature": self.resources.literature,
            "internet_resources": self.resources.internet_resources,
            "other_materials": self.resources.other_materials,
            # Ход занятия (список словарей для {% tr for step in lesson_structure %})
            "lesson_structure": [step.model_dump() for step in self.lesson_structure],
        }
