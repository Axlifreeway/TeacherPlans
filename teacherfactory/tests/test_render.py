"""
Тесты рендеринга в DOCX и санитизации имён файлов.

`render_document` тестируется на реальном шаблоне технологической карты
(см. paths.LESSON_CARD_TEMPLATE) — это помогает ловить регрессии при
правке шаблона.
"""

from pathlib import Path

from docx import Document as DocxRead

from teacherfactory.documents.lesson_card import LESSON_CARD
from teacherfactory.render import build_output_filename, render_document
from tests.conftest import build_stub_card


# ─── render_document: интеграция с реальным шаблоном ─────────────────────────


def test_render_produces_valid_docx(tmp_path: Path):
    out = tmp_path / "test.docx"
    render_document(LESSON_CARD, build_stub_card(), out)

    assert out.exists()
    # Файл должен быть валидным DOCX и читаться обратно.
    doc = DocxRead(str(out))
    text = " ".join(p.text for p in doc.paragraphs)
    text += " " + " ".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    # Подставленные значения должны присутствовать в выходе:
    assert "Тестовая дисциплина" in text
    assert "TEST-21" in text
    assert "Тестов" in text  # ФИО подставилось
    assert "ОК 01" in text  # компетенция
    assert "З-1" in text  # learning outcome


def test_render_creates_parent_dirs(tmp_path: Path):
    """Если папка вывода не существует — её должны создать."""
    out = tmp_path / "deep" / "nested" / "out.docx"
    render_document(LESSON_CARD, build_stub_card(), out)
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
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 1,
            "discipline": "..",
        },
    )
    assert ".." not in name
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
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 1,
            "discipline": "evil\x00name",
        },
    )
    assert "\x00" not in name


def test_filename_handles_empty_string():
    name = build_output_filename(
        LESSON_CARD,
        {
            "lesson_number": 1,
            "discipline": "",
        },
    )
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
    assert "Programming-Intro" in name
    assert "/" not in name


def test_filename_with_strict_pattern_strips_dirs():
    from dataclasses import replace

    bad_doc = replace(LESSON_CARD, filename_pattern="../../{lesson_number}.docx")
    name = build_output_filename(bad_doc, {"lesson_number": 5})
    assert name == "5.docx"
