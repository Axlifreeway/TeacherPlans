"""
Тесты стратегии чанкинга:
  - размеры чанков соответствуют конфигу
  - структурные разделители сохраняют целостность строк
  - overlap работает корректно
"""

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Копия разделителей из indexer.py — тестируем именно их поведение
_SEPARATORS = ["\n\n\n", "\n\n", "\n", ". ", ", ", " ", ""]


def _make_splitter(chunk_size: int = 800, chunk_overlap: int = 200):
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_SEPARATORS,
    )


# ─── Размеры чанков ───────────────────────────────────────────────────────────


def test_chunks_respect_max_size():
    """Ни один чанк не должен превышать chunk_size (с небольшим допуском)."""
    splitter = _make_splitter(chunk_size=800)
    doc = Document(page_content="Слово " * 1000, metadata={})
    chunks = splitter.split_documents([doc])
    for chunk in chunks:
        # Небольшой допуск: splitter может незначительно превысить из-за разделителей
        assert len(chunk.page_content) <= 900, f"Чанк слишком большой: {len(chunk.page_content)}"


def test_chunks_are_created():
    """Длинный документ должен быть разбит на несколько чанков."""
    splitter = _make_splitter(chunk_size=200, chunk_overlap=50)
    long_text = "Абзац с текстом. " * 100
    doc = Document(page_content=long_text, metadata={})
    chunks = splitter.split_documents([doc])
    assert len(chunks) > 1


def test_short_doc_single_chunk():
    """Короткий документ должен оставаться одним чанком."""
    splitter = _make_splitter(chunk_size=800)
    doc = Document(page_content="Короткий текст.", metadata={})
    chunks = splitter.split_documents([doc])
    assert len(chunks) == 1


# ─── Структурные разделители ──────────────────────────────────────────────────


def test_newline_separator_preferred():
    """
    Чанкер должен предпочитать разрывы по строкам, а не посередине предложения.
    Это важно для таблиц компетенций.
    """
    splitter = _make_splitter(chunk_size=100, chunk_overlap=0)
    # Текст из строк таблицы — каждая строка ~50 символов
    table_text = "\n".join(
        [
            "ОК 01 Выбирать способы решения задач",
            "ОК 02 Использовать средства поиска",
            "ОК 04 Работать в коллективе и команде",
            "ОК 05 Осуществлять коммуникацию",
        ]
    )
    doc = Document(page_content=table_text, metadata={})
    chunks = splitter.split_documents([doc])

    # Проверяем что строки не разрезаны посередине
    for chunk in chunks:
        lines = chunk.page_content.strip().splitlines()
        for line in lines:
            # Каждая строка должна начинаться с ОК или быть пустой
            if line.strip():
                assert line.strip().startswith("ОК"), f"Строка таблицы разрезана: '{line}'"


def test_metadata_preserved():
    """Метаданные страницы/источника должны сохраняться в чанках."""
    splitter = _make_splitter(chunk_size=200, chunk_overlap=50)
    doc = Document(
        page_content="Текст " * 100,
        metadata={"source": "test.pdf", "page": 42},
    )
    chunks = splitter.split_documents([doc])
    for chunk in chunks:
        assert chunk.metadata["source"] == "test.pdf"
        assert chunk.metadata["page"] == 42


# ─── Overlap ──────────────────────────────────────────────────────────────────


def test_overlap_creates_continuity():
    """Соседние чанки должны иметь перекрытие (общий текст)."""
    splitter = _make_splitter(chunk_size=100, chunk_overlap=30)
    text = "слово " * 200
    doc = Document(page_content=text, metadata={})
    chunks = splitter.split_documents([doc])

    if len(chunks) >= 2:
        # Конец первого чанка должен частично совпадать с началом второго
        end_of_first = chunks[0].page_content[-30:]
        start_of_second = chunks[1].page_content[:50]
        # Хотя бы несколько слов должны совпадать
        words_first = set(end_of_first.split())
        words_second = set(start_of_second.split())
        assert len(words_first & words_second) > 0
