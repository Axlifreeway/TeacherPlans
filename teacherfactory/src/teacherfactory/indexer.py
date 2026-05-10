"""
Индексатор документов для RAG.

Загружает PDF из папки docs/, нарезает на чанки,
создаёт эмбеддинги через Ollama и сохраняет FAISS-индекс на диск.

Запуск: poetry run python src/teacherfactory/indexer.py
"""

from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS


# Пути относительно корня проекта
DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
# FAISS не может работать с кириллическими путями,
# поэтому сохраняем индекс в домашней папке пользователя
INDEX_DIR = Path.home() / ".teacherfactory" / "faiss_index"


def build_index():
    """Построить FAISS-индекс из всех PDF в папке docs/."""

    # 1. Загрузка PDF
    all_docs = []
    pdf_files = list(DOCS_DIR.glob("*.pdf"))

    if not pdf_files:
        print(f"Нет PDF файлов в {DOCS_DIR}")
        return

    for pdf_path in pdf_files:
        print(f"  Загружаю: {pdf_path.name}")
        loader = PyPDFLoader(str(pdf_path))
        all_docs.extend(loader.load())

    print(f"Загружено {len(all_docs)} страниц из {len(pdf_files)} файлов")

    # 2. Нарезка на чанки
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=200)
    chunks = splitter.split_documents(all_docs)
    print(f"Нарезано {len(chunks)} чанков")

    # 3. Эмбеддинги + FAISS
    print("Создаю эмбеддинги (это может занять 1-2 минуты)...")
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    db = FAISS.from_documents(chunks, embeddings)

    # 4. Сохранение на диск
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    db.save_local(str(INDEX_DIR))
    print(f"Индекс сохранён в {INDEX_DIR}")

    # 5. Тестовый поиск
    print("\n--- Тестовый поиск: 'общие компетенции' ---")
    results = db.similarity_search("общие компетенции", k=3)
    for i, doc in enumerate(results, 1):
        source = Path(doc.metadata.get("source", "?")).name
        print(f"\n[{i}] {source} (стр. {doc.metadata.get('page', '?')})")
        print(doc.page_content[:300])
        print("---")


if __name__ == "__main__":
    build_index()
