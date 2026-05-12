"""
Тесты рендеринга в DOCX и санитизации имён файлов.

`render_document` тестируется на реальном шаблоне `template_fixed.docx`,
а не на мок-DocxTemplate — это поможет ловить регрессии при правке шаблона.
"""

from pathlib import Path

from docx import Document as DocxRead

from teacherfactory.documents.lesson_card import LESSON_CARD
from teacherfactory.model import LessonCard, LessonStep, LessonTasks, PlannedOutcomes, Resources
from teacherfactory.render import build_output_filename, render_document


def _stub_card() -> LessonCard:
    return LessonCard(
        lesson_number=42,
        date="08.05.2026",
        group_name="TEST-21",
        students_count=20,
        discipline="Тестовая дисциплина",
        specialty="00.00.00 Тест",
        course_number=2,
        lesson_topic="Тестовая тема",
        lesson_type="комбинированный урок",
        lesson_kind="лекция",
        duration=90,
        teacher_name="Тестов Т.Т.",
        goal="Цель",
        tasks=LessonTasks(
            educational="Е",
            developmental="Р",
            upbringing="В",
            pedagogical="П",
        ),
        competencies_ok="ОК 01",
        competencies_pk="ПК 1.2",
        outcomes=PlannedOutcomes(
            knowledge_indicator="зн",
            knowledge_control="опрос",
            skill_indicator="ум",
            skill_control="ПР",
            ability_indicator="нав",
            ability_control="ЛР",
        ),
        resources=Resources(literature="л", internet_resources="и", other_materials="м"),
        lesson_structure=[
            LessonStep(
                number=1, stage="A", time="5", teacher="t", student="s", methods="m", result="r"
            ),
            LessonStep(
                number=2,
                stage="B",
                time="40",
                teacher="tt",
                student="ss",
                methods="mm",
                result="rr",
            ),
        ],
    )


# ─── render_document: интеграция с реальным шаблоном ─────────────────────────


def test_render_produces_valid_docx(tmp_path: Path):
    out = tmp_path / "test.docx"
    render_document(LESSON_CARD, _stub_card(), out)

    assert out.exists()
    # Файл должен быть валидным DOCX и читаться обратно.
    doc = DocxRead(str(out))
    # Хотя бы один параграф или таблица в файле.
    text = " ".join(p.text for p in doc.paragraphs)
    text += " " + " ".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    # Подставленные значения должны присутствовать в выходе:
    assert "Тестовая дисциплина" in text
    assert "TEST-21" in text
    assert "Тестова" in text  # ФИО подставилось


def test_render_creates_parent_dirs(tmp_path: Path):
    """Если папка вывода не существует — её должны создать."""
    out = tmp_path / "deep" / "nested" / "out.docx"
    render_document(LESSON_CARD, _stub_card(), out)
    assert out.exists()


# ─── build_output_filename: санитизация ──────────────────────────────────────


def test_filename_basic():
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 1,
            "discipline": "Базы данных",
        },
    )
    assert name == "Урок_1_Базы данных.docx"


def test_filename_strips_path_separators():
    """`/` и `\\` в дисциплине не должны давать выход за пределы каталога."""
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 1,
            "discipline": "../../etc/passwd",
        },
    )
    assert "/" not in name
    assert "\\" not in name
    assert ".." not in name
    assert name.endswith(".docx")


def test_filename_handles_only_dangerous_chars():
    """Дисциплина из одних `..` — не должна стать пустой или содержать только точки."""
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 1,
            "discipline": "..",
        },
    )
    assert ".." not in name
    # Имя файла после форматирования валидное.
    assert name.endswith(".docx")


def test_filename_collapses_multiple_dots():
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 1,
            "discipline": "foo..bar...baz",
        },
    )
    assert "..." not in name
    assert ".." not in name


def test_filename_handles_null_bytes():
    """NULL-байт в имени некоторые ФС считают концом строки — обязан быть убран."""
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 1,
            "discipline": "evil\x00name",
        },
    )
    assert "\x00" not in name


def test_filename_handles_empty_string():
    """Полностью пустая строка — fallback на 'untitled'."""
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 1,
            "discipline": "",
        },
    )
    # Пустая дисциплина → имя не падает, не пустое
    assert name
    assert name.endswith(".docx")


def test_filename_preserves_safe_chars():
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 7,
            "discipline": "C++ Programming-Intro",
        },
    )
    # `+` запрещён нашей строгой санитизацией → станет `_`.
    # Главное: имя не сломалось и без path-traversal.
    assert "Programming-Intro" in name
    assert "/" not in name


def test_filename_with_strict_pattern_strips_dirs():
    """
    Даже если кто-то умышленно положит `..` в pattern (DocumentType.filename_pattern),
    финальный _strip_to_filename режет до базового имени.
    """
    from dataclasses import replace

    bad_doc = replace(LESSON_CARD, filename_pattern="../../{lesson_number}.docx")
    name = build_output_filename(bad_doc, {"lesson_number": 5})
    assert name == "5.docx"
