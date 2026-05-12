"""
Поиск контекста для RAG.

Состав:
  - `load_index()`           — поднимает FAISS + BM25 с диска;
  - `retrieve_context()`     — гибридный поиск (FAISS + BM25 → RRF) + опциональный
                               cross-encoder reranking; принимает строку или
                               мультизапрос (list[str]);
  - `retrieve_by_specialty()` — фильтрация по коду специальности из имени
                               файла (для запросов вида «перечисли дисциплины
                               09.01.03»).

BM25-индекс хранится в JSON и пересобирается на load (BM25Okapi.fit — O(N) по
токенам, единицы миллисекунд на тысячи чанков). Это убирает `pickle.load` как
вектор атаки.

FAISS-индекс по-прежнему требует `allow_dangerous_deserialization=True` — это
устройство хранения FAISS в LangChain (docstore сериализуется через pickle).
Threat model: индекс лежит в `~/.teacherfactory/faiss_index/`, доступ туда
имеет только владелец машины. Если у атакующего есть write в твой home —
проект пора закрывать, а не индекс хешировать.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from teacherfactory.config import CONFIG
from teacherfactory.embeddings import get_embeddings
from teacherfactory.paths import BM25_PATH, INDEX_DIR
from teacherfactory.text_utils import tokenize

log = logging.getLogger(__name__)

# Стандартная константа RRF из статьи Cormack et al. 2009 — сглаживает
# вклад низкоранговых документов. Если хочется тюнить — выноси в конфиг.
_RRF_K = 60

# Версия on-disk формата BM25 — на случай миграций.
BM25_FORMAT_VERSION = 1

_reranker: CrossEncoder | None = None


@dataclass(frozen=True)
class BM25Index:
    """BM25-индекс: модель + соответствующие ей чанки."""

    bm25: BM25Okapi
    chunks: list[Document]


def _get_reranker() -> CrossEncoder | None:
    model_name = CONFIG["rag"].get("reranker_model")
    if not model_name:
        return None
    global _reranker
    if _reranker is None:
        log.info("Загружаю reranker: %s", model_name)
        _reranker = CrossEncoder(model_name)
    return _reranker


# ─── Сохранение / загрузка BM25 ───────────────────────────────────────────────


def save_bm25(chunks: list[Document], path: Path = BM25_PATH) -> None:
    """Сохранить чанки BM25 в JSON. Сама модель пересобирается при загрузке."""
    payload: dict[str, Any] = {
        "version": BM25_FORMAT_VERSION,
        "chunks": [{"page_content": c.page_content, "metadata": c.metadata} for c in chunks],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_bm25(path: Path = BM25_PATH) -> BM25Index | None:
    """Прочитать чанки из JSON и пересобрать BM25Okapi."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != BM25_FORMAT_VERSION:
        raise RuntimeError(
            f"BM25-индекс несовместимой версии ({data.get('version')!r}). Перестройте индекс."
        )
    chunks = [
        Document(page_content=c["page_content"], metadata=c.get("metadata", {}))
        for c in data["chunks"]
    ]
    corpus = [tokenize(c.page_content) for c in chunks]
    return BM25Index(bm25=BM25Okapi(corpus), chunks=chunks)


# ─── Загрузка индекса ─────────────────────────────────────────────────────────


def load_index() -> tuple[FAISS, BM25Index | None]:
    """Загрузить FAISS и (если есть) BM25 индекс."""
    if not INDEX_DIR.exists() or not any(INDEX_DIR.iterdir()):
        raise FileNotFoundError(
            f"FAISS-индекс не найден в {INDEX_DIR}. "
            "Сначала постройте индекс кнопкой «Перестроить индекс» в UI или "
            "запустите `poetry run python -m teacherfactory.indexer`."
        )
    embeddings = get_embeddings()
    # См. модульный docstring: pickle-deserialization FAISS сознательная,
    # threat model = доверяем содержимому домашней директории.
    db = FAISS.load_local(str(INDEX_DIR), embeddings, allow_dangerous_deserialization=True)

    index_dim = db.index.d
    current_dim = len(embeddings.embed_query("test"))
    if index_dim != current_dim:
        raise RuntimeError(
            f"FAISS-индекс несовместим с текущими эмбеддингами: "
            f"индекс построен с dim={index_dim}, а активный провайдер даёт dim={current_dim}. "
            f"Скорее всего, поменялся embeddings.provider в config — "
            f"перестройте индекс кнопкой «Перестроить индекс» в боковой панели."
        )

    bm25_index = load_bm25()
    if bm25_index is not None:
        log.info("BM25-индекс загружен (%d чанков)", len(bm25_index.chunks))
    else:
        log.warning("BM25-индекс не найден — используется только FAISS. Перестройте индекс.")

    return db, bm25_index


# ─── Основной поиск ───────────────────────────────────────────────────────────


def retrieve_context(
    db: FAISS,
    bm25_index: BM25Index | None,
    query: str | list[str],
    k: int | None = None,
) -> str:
    """
    Трёхступенчатый поиск: FAISS + BM25 → RRF → cross-encoder reranking.

    query может быть строкой или списком строк (мультизапрос). При
    мультизапросе результаты по всем запросам объединяются через RRF,
    что улучшает покрытие документа.
    """
    if k is None:
        k = CONFIG["rag"]["retrieval_k"]

    queries = [query] if isinstance(query, str) else query
    candidates = CONFIG["rag"].get("retrieval_candidates", k * 4)
    per_query = max(candidates // len(queries), k)

    score_map: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for q in queries:
        dense = db.similarity_search(q, k=per_query)

        if bm25_index is not None:
            tokens = tokenize(q)
            bm25_scores = bm25_index.bm25.get_scores(tokens)
            top_idx = sorted(
                range(len(bm25_scores)),
                key=lambda i: bm25_scores[i],
                reverse=True,
            )[:per_query]
            sparse = [bm25_index.chunks[i] for i in top_idx]
        else:
            sparse = []

        for rank, doc in enumerate(dense):
            key = doc.page_content[:120]
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
            doc_map[key] = doc

        for rank, doc in enumerate(sparse):
            key = doc.page_content[:120]
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
            doc_map[key] = doc

    rrf_top = sorted(score_map, key=score_map.__getitem__, reverse=True)[:candidates]
    candidate_docs = [doc_map[key] for key in rrf_top]

    primary_query = queries[0]
    reranker = _get_reranker()
    if reranker and len(candidate_docs) > k:
        pairs = [(primary_query, doc.page_content) for doc in candidate_docs]
        rerank_scores = reranker.predict(pairs)
        ranked = sorted(
            zip(rerank_scores, candidate_docs, strict=True),
            key=lambda x: x[0],
            reverse=True,
        )
        top_docs = [doc for _, doc in ranked[:k]]
        log.info("Reranking: %d кандидатов → топ-%d", len(candidate_docs), k)
    else:
        top_docs = candidate_docs[:k]

    return _format_docs(top_docs)


def retrieve_by_specialty(
    bm25_index: BM25Index,
    specialty_code: str,
    extra_query: str,
    db: FAISS,
    k: int | None = None,
) -> str:
    """
    Для запросов типа «перечисли дисциплины 09.01.03» — возвращает ВСЕ чанки
    из файлов, в чьём имени есть код специальности. Дополняем семантическим
    поиском по всем документам для надёжности.
    """
    if k is None:
        k = CONFIG["rag"].get("chat_specialty_k", 20)
    code_norm = specialty_code.replace(".", "")
    matching: list[Document] = []

    for chunk in bm25_index.chunks:
        src = chunk.metadata.get("source", "")
        src_norm = src.replace(".", "").replace("_", "").replace(" ", "")
        if code_norm in src_norm:
            matching.append(chunk)

    matching.sort(key=lambda c: (c.metadata.get("source", ""), c.metadata.get("page", 0)))

    semantic = db.similarity_search(f"{extra_query} {specialty_code}", k=15)
    existing_keys = {c.page_content[:120] for c in matching}
    for doc in semantic:
        if doc.page_content[:120] not in existing_keys:
            matching.append(doc)

    log.info(
        "Фильтрация по специальности %s: %d чанков",
        specialty_code,
        len(matching[:k]),
    )
    return _format_docs(matching[:k])


def _format_docs(docs: list[Document]) -> str:
    parts = []
    for doc in docs:
        source = Path(doc.metadata.get("source", "неизвестно")).name
        page = doc.metadata.get("page", "?")
        parts.append(f"[Источник: {source}, стр. {page}]\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)
