"""
Индексатор документов для RAG.

Загружает PDF из папки docs/, нарезает на чанки,
создаёт FAISS-индекс (семантический) и BM25-индекс (ключевые слова).

Запуск: poetry run python src/teacherfactory/indexer.py
"""

import logging
import pickle
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi

from config import CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
# FAISS не работает с кириллическими путями — сохраняем в домашней папке
INDEX_DIR = Path.home() / ".teacherfactory" / "faiss_index"
BM25_PATH = INDEX_DIR / "bm25.pkl"


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def build_index() -> None:
    """Построить FAISS + BM25 индексы из всех PDF в папке docs/."""

    # 1. Загрузка PDF
    all_docs = []
    pdf_files = list(DOCS_DIR.glob("*.pdf"))

    if not pdf_files:
        log.warning("Нет PDF файлов в %s", DOCS_DIR)
        return

    for pdf_path in pdf_files:
        log.info("  Загружаю: %s", pdf_path.name)
        loader = PyPDFLoader(str(pdf_path))
        all_docs.extend(loader.load())

    log.info("Загружено %d страниц из %d файлов", len(all_docs), len(pdf_files))

    # 2. Нарезка на чанки
    chunk_size = CONFIG["rag"]["chunk_size"]
    chunk_overlap = CONFIG["rag"]["chunk_overlap"]
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = splitter.split_documents(all_docs)
    log.info("Нарезано %d чанков (size=%d, overlap=%d)", len(chunks), chunk_size, chunk_overlap)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # 3. FAISS (dense — семантический поиск)
    embed_model = CONFIG["model"]["embeddings"]
    log.info("Создаю эмбеддинги с моделью %s (это может занять 1-2 минуты)...", embed_model)
    embeddings = OllamaEmbeddings(model=embed_model)
    db = FAISS.from_documents(chunks, embeddings)
    db.save_local(str(INDEX_DIR))
    log.info("FAISS-индекс сохранён в %s", INDEX_DIR)

    # 4. BM25 (sparse — поиск по ключевым словам, важен для кодов ОК/ПК)
    corpus = [_tokenize(chunk.page_content) for chunk in chunks]
    bm25 = BM25Okapi(corpus)
    with open(BM25_PATH, "wb") as f:
        pickle.dump({"bm25": bm25, "chunks": chunks}, f)
    log.info("BM25-индекс сохранён: %s", BM25_PATH)

    # 5. Тестовый поиск
    log.info("--- Тестовый поиск: 'общие компетенции' ---")
    results = db.similarity_search("общие компетенции", k=3)
    for i, doc in enumerate(results, 1):
        source = Path(doc.metadata.get("source", "?")).name
        log.info(
            "[%d] %s (стр. %s): %s...",
            i, source, doc.metadata.get("page", "?"), doc.page_content[:120],
        )


if __name__ == "__main__":
    build_index()
