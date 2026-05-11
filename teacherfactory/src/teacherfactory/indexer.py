"""
Индексатор документов для RAG.

Загружает PDF и DOCX из папки docs/, нарезает на чанки с учётом структуры
российских нормативных документов (разделы, таблицы, абзацы),
создаёт FAISS-индекс (семантический) и BM25-индекс (ключевые слова).

Запуск: poetry run python src/teacherfactory/indexer.py
"""

import logging
import pickle
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi

from config import CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
INDEX_DIR = Path.home() / ".teacherfactory" / "faiss_index"
BM25_PATH = INDEX_DIR / "bm25.pkl"

# Разделители в порядке приоритета: сначала крупные структурные границы,
# потом мелкие. Строки (\n) идут раньше точек — это помогает не резать
# таблицы компетенций посередине строки.
_SEPARATORS = [
    "\n\n\n",   # крупные разделы
    "\n\n",     # абзацы
    "\n",       # строки (важно для таблиц)
    ". ",       # предложения
    ", ",       # перечисления
    " ",        # слова
    "",         # символы (крайний случай)
]


def _tokenize(text: str) -> list[str]:
    """Токенизация с нормализацией кодов компетенций (ОК01 == ОК 01)."""
    import re
    # Нормализуем коды: "ОК01" → "ОК 01", "ПК1.2" → "ПК 1.2"
    text = re.sub(r'([ОП][КМ])\s*(\d)', r'\1 \2', text)
    return text.lower().split()


def _load_pdf(pdf_path: Path) -> list[Document]:
    """Загрузить PDF через pdfplumber — сохраняет структуру таблиц компетенций."""
    import pdfplumber

    docs = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                parts: list[str] = []

                # Сначала извлекаем таблицы — они содержат коды ОК/ПК
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row:
                            continue
                        cells = [str(c).strip() for c in row if c and str(c).strip()]
                        if cells:
                            parts.append("\t".join(cells))

                # Затем основной текст страницы
                text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                if text.strip():
                    parts.append(text.strip())

                full_text = "\n".join(parts).strip()
                if full_text:
                    docs.append(Document(
                        page_content=full_text,
                        metadata={"source": str(pdf_path), "page": i},
                    ))
    except Exception as e:
        log.warning("pdfplumber не смог прочитать %s: %s — пробую PyPDF", pdf_path.name, e)
        docs = _load_pdf_fallback(pdf_path)

    return docs


def _load_pdf_fallback(pdf_path: Path) -> list[Document]:
    """Запасной вариант — PyPDF (хуже обрабатывает таблицы)."""
    from langchain_community.document_loaders import PyPDFLoader
    try:
        loader = PyPDFLoader(str(pdf_path))
        return loader.load()
    except Exception as e:
        log.error("PyPDF fallback failed for %s: %s", pdf_path.name, e)
        return []


def _load_docx(docx_path: Path) -> list[Document]:
    """Загрузить DOCX с сохранением структуры таблиц компетенций."""
    try:
        from docx import Document as DocxDoc
    except ImportError:
        log.warning("python-docx не установлен, пропускаю %s", docx_path.name)
        return []

    try:
        word_doc = DocxDoc(str(docx_path))
        parts: list[str] = []

        for para in word_doc.paragraphs:
            text = para.text.strip()
            if text:
                parts.append(text)

        for table in word_doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    # Убираем дубли (merged cells дублируют содержимое)
                    unique_cells = list(dict.fromkeys(cells))
                    parts.append("\t".join(unique_cells))

        full_text = "\n".join(parts).strip()
        if full_text:
            return [Document(
                page_content=full_text,
                metadata={"source": str(docx_path), "page": 0},
            )]
    except Exception as e:
        log.warning("Не удалось прочитать %s: %s", docx_path.name, e)

    return []


def build_index() -> None:
    """Построить FAISS + BM25 индексы из PDF и DOCX в папке docs/."""

    # 1. Загрузка документов
    all_docs: list[Document] = []
    skipped_doc: list[str] = []

    pdf_files = sorted(DOCS_DIR.glob("*.pdf"))
    docx_files = sorted(DOCS_DIR.glob("*.docx"))
    doc_files = sorted(DOCS_DIR.glob("*.doc"))

    if not pdf_files and not docx_files:
        log.warning("Нет PDF/DOCX файлов в %s", DOCS_DIR)
        return

    for pdf_path in pdf_files:
        log.info("  PDF: %s", pdf_path.name)
        pages = _load_pdf(pdf_path)
        all_docs.extend(pages)
        log.info("    → %d страниц", len(pages))

    for docx_path in docx_files:
        log.info("  DOCX: %s", docx_path.name)
        pages = _load_docx(docx_path)
        all_docs.extend(pages)
        log.info("    → %d фрагментов", len(pages))

    for doc_path in doc_files:
        log.warning("  ⚠ .doc пропущен (конвертируй в .docx или .pdf): %s", doc_path.name)
        skipped_doc.append(doc_path.name)

    if skipped_doc:
        log.warning(
            "Пропущено %d .doc файлов: %s. "
            "Сконвертируй их в .docx через Word или LibreOffice.",
            len(skipped_doc), skipped_doc,
        )

    log.info(
        "Загружено %d фрагментов из %d PDF + %d DOCX файлов",
        len(all_docs), len(pdf_files), len(docx_files),
    )

    if not all_docs:
        log.error("Не удалось загрузить ни одного документа")
        return

    # 2. Структурный чанкинг — уважает границы строк и абзацев
    chunk_size = CONFIG["rag"]["chunk_size"]
    chunk_overlap = CONFIG["rag"]["chunk_overlap"]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_SEPARATORS,
    )
    chunks = splitter.split_documents(all_docs)
    log.info("Нарезано %d чанков (size=%d, overlap=%d)", len(chunks), chunk_size, chunk_overlap)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # 3. FAISS (dense — семантический поиск)
    embed_model = CONFIG["model"]["embeddings"]
    log.info("Создаю эмбеддинги с моделью %s...", embed_model)
    embeddings = OllamaEmbeddings(model=embed_model)
    db = FAISS.from_documents(chunks, embeddings)
    db.save_local(str(INDEX_DIR))
    log.info("FAISS-индекс сохранён в %s", INDEX_DIR)

    # 4. BM25 (sparse — точный поиск кодов ОК/ПК и ключевых терминов)
    corpus = [_tokenize(chunk.page_content) for chunk in chunks]
    bm25 = BM25Okapi(corpus)
    with open(BM25_PATH, "wb") as f:
        pickle.dump({"bm25": bm25, "chunks": chunks}, f)
    log.info("BM25-индекс сохранён: %s", BM25_PATH)

    # Сохраняем список .doc файлов для отображения в UI
    skipped_path = INDEX_DIR / "skipped_doc_files.txt"
    if skipped_doc:
        skipped_path.write_text("\n".join(skipped_doc), encoding="utf-8")
    elif skipped_path.exists():
        skipped_path.unlink()

    # 5. Тестовый поиск
    log.info("--- Тестовый поиск: 'профессиональные компетенции ПК' ---")
    results = db.similarity_search("профессиональные компетенции ПК", k=3)
    for i, doc in enumerate(results, 1):
        source = Path(doc.metadata.get("source", "?")).name
        log.info(
            "[%d] %s (стр. %s): %s...",
            i, source, doc.metadata.get("page", "?"), doc.page_content[:150],
        )


if __name__ == "__main__":
    build_index()
