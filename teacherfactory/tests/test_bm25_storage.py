"""
Тесты JSON-хранилища BM25:
  - save → load даёт идентичный набор чанков;
  - схема версионируется (миграции в будущем);
  - битый JSON / несовместимая версия → понятная ошибка;
  - метаданные чанков (source, page) сохраняются.
"""

import json
from pathlib import Path

import pytest
from langchain_core.documents import Document

from teacherfactory.retrieval import BM25_FORMAT_VERSION, load_bm25, save_bm25


def _chunks() -> list[Document]:
    return [
        Document(page_content="ОК 01 текст", metadata={"source": "a.pdf", "page": 1}),
        Document(page_content="ПК 1.2 текст", metadata={"source": "b.pdf", "page": 7}),
        Document(page_content="русский кириллица", metadata={"source": "c.docx", "page": 0}),
    ]


def test_save_then_load_preserves_chunks(tmp_path: Path):
    path = tmp_path / "bm25.json"
    save_bm25(_chunks(), path=path)
    index = load_bm25(path=path)

    assert index is not None
    assert len(index.chunks) == 3
    assert index.chunks[0].page_content == "ОК 01 текст"
    assert index.chunks[0].metadata == {"source": "a.pdf", "page": 1}


def test_load_missing_returns_none(tmp_path: Path):
    assert load_bm25(path=tmp_path / "nope.json") is None


def test_save_creates_parent_dirs(tmp_path: Path):
    path = tmp_path / "deep" / "bm25.json"
    save_bm25(_chunks(), path=path)
    assert path.exists()


def test_saved_file_is_valid_json(tmp_path: Path):
    path = tmp_path / "bm25.json"
    save_bm25(_chunks(), path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == BM25_FORMAT_VERSION
    assert isinstance(data["chunks"], list)


def test_load_rejects_incompatible_version(tmp_path: Path):
    path = tmp_path / "bm25.json"
    path.write_text(json.dumps({"version": 99, "chunks": []}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="несовместимой версии"):
        load_bm25(path=path)


def test_load_handles_missing_metadata(tmp_path: Path):
    """Старые/кривые файлы без metadata — используем пустой dict, не падаем."""
    path = tmp_path / "bm25.json"
    path.write_text(
        json.dumps({"version": BM25_FORMAT_VERSION, "chunks": [{"page_content": "x"}]}),
        encoding="utf-8",
    )
    index = load_bm25(path=path)
    assert index is not None
    assert index.chunks[0].metadata == {}


def test_bm25_returns_scores_after_load(tmp_path: Path):
    """BM25Okapi должен реально работать после round-trip."""
    from teacherfactory.text_utils import tokenize

    path = tmp_path / "bm25.json"
    save_bm25(_chunks(), path=path)
    index = load_bm25(path=path)
    assert index is not None

    scores = index.bm25.get_scores(tokenize("ОК 01"))
    # Чанк с «ОК 01» должен набрать больше баллов, чем чанк про кириллицу
    assert scores[0] > scores[2]


def test_no_pickle_in_saved_file(tmp_path: Path):
    """Регрессия: убедиться что мы не вернулись к pickle."""
    path = tmp_path / "bm25.json"
    save_bm25(_chunks(), path=path)
    content = path.read_bytes()
    # Pickle-формат начинается с не-печатных байтов; JSON начинается с `{`.
    assert content.lstrip().startswith(b"{")
