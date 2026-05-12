# Архитектура TeacherFactory

## Слои

```
┌────────────────────────────────────────────────────────────────┐
│  views/                  Streamlit UI                          │
│  sidebar · single · batch · chat · errors · common             │
└──────────────────────────────┬─────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────┐
│  pipeline.py             Оркестрация                           │
│  generate_document(doc_type, params) ─┐                        │
│  stream_chat_response(question) ──────┤                        │
└──────────────────────────────┬────────┴────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
  ┌───────────┐         ┌────────────┐         ┌────────────┐
  │ retrieval │         │ documents/ │         │   render   │
  │           │         │            │         │            │
  │ load_     │         │ Document-  │         │ render_    │
  │ index     │         │ Type[T]    │         │ document   │
  │           │         │ +REGISTRY  │         │ +sanitize  │
  │ retrieve_ │         │            │         │ filename   │
  │ context   │         │ • lesson_  │         │            │
  │           │         │   card     │         │            │
  │ BM25Index │         │ • <future> │         │            │
  └─────┬─────┘         └─────┬──────┘         └────────────┘
        │                     │
        ▼                     ▼
  ┌────────────┐        ┌──────────┐
  │ embeddings │        │  model   │   (Pydantic-схемы)
  │  llm_      │        │          │
  │ provider   │        └──────────┘
  └────────────┘
```

## Ключевые модули

| Модуль | Ответственность |
|---|---|
| `paths.py` | Все Path-константы. Никто другой не делает `Path.home() / ...`. |
| `text_utils.py` | `tokenize`, `COMPETENCY_RE`, `LIST_INTENT_RE`, `SPECIALTY_CODE_RE`, `normalize_code`. |
| `config.py` | Лениво читает `config.default.toml` + опциональный `config.local.toml`. |
| `embeddings.py` | Фабрика эмбеддингов (Ollama / HuggingFace). |
| `llm_provider.py` | `LLMProvider` ABC, `OllamaProvider`, `GroqProvider`, фабрика `get_llm_provider()`. `api_key` хранится в `SecretStr`. |
| `model.py` | Pydantic-схемы (сейчас `LessonCard`). |
| `retrieval.py` | `BM25Index` (JSON), `load_index`, `retrieve_context` (FAISS + BM25 → RRF → reranker), `retrieve_by_specialty`. |
| `documents/` | Реестр типов документов: `DocumentType[T]` + регистрации (сейчас только `LESSON_CARD`). |
| `pipeline.py` | `generate_document` (универсальный по `DocumentType[T]`), `stream_chat_response` (с HyDE). |
| `validation.py` | Пост-валидация (проверка кодов компетенций по индексу). |
| `render.py` | `render_document` (docxtpl) + `build_output_filename` с санитизацией. |
| `indexer.py` | CLI/функция построения индекса из `docs/`. |
| `views/` | Streamlit-вкладки. Не содержат бизнес-логики, только UI поверх pipeline. |
| `app.py` | Точка входа Streamlit. |

## Поток одного запроса

`generate_document(LESSON_CARD, params)`:

1. **Проверка params**: `DocumentType.required_params` → если чего-то нет, `ValueError` *до* вызова LLM.
2. **Загрузка индекса**: `load_index()` → FAISS + `BM25Index` (или `None`).
3. **Построение запросов**: `LESSON_CARD.build_queries(params)` → мультизапрос.
4. **Retrieval**: для каждого запроса — FAISS dense + BM25 sparse → RRF слияние → cross-encoder reranking → топ-K.
5. **LLM**: `ChatPromptTemplate(system + user) | client.with_structured_output(LessonCard)` → Pydantic-объект.
6. **(опционально) Валидация**: `LESSON_CARD.validate(card)` → словарь `{код: bool}`.
7. **Рендеринг**: `render_document(LESSON_CARD, card, out_path)` → DOCX.

## Реестр типов документов

Каждый тип документа — это `DocumentType[T]` (см. [`CONTRIBUTING.md`](CONTRIBUTING.md)):

```python
@dataclass(frozen=True)
class DocumentType[T: BaseModel]:
    slug: str
    title: str
    model: type[T]
    template_path: Path
    system_prompt: str
    user_prompt: str
    build_queries: Callable[[dict], list[str]]
    filename_pattern: str
    validate: Callable[[T], dict[str, bool]] | None
    to_template_context: Callable[[T], dict] | None
    required_params: tuple[str, ...]
```

`pipeline.generate_document` параметризован по `T: BaseModel` — благодаря PEP 695
он точно знает, что возвращает именно `T` (а не `BaseModel`), и mypy это видит.

## RAG-стек

- **Чанкинг** (`indexer.py`): `RecursiveCharacterTextSplitter` с приоритетом строк
  и абзацев — чтобы не резать таблицы компетенций.
- **Dense поиск**: FAISS + эмбеддинги (Ollama `nomic-embed-text` либо HF
  `paraphrase-multilingual-MiniLM-L12-v2`).
- **Sparse поиск**: BM25Okapi с нормализацией кодов ОК/ПК (`ОК01` ↔ `ОК 01`).
- **Слияние**: Reciprocal Rank Fusion с `K=60` (Cormack et al. 2009).
- **Reranking**: cross-encoder `mmarco-mMiniLMv2` (~120 МБ, ленивая загрузка).
- **HyDE** (для чата): гипотетический документ-ответ как доп. запрос.
- **Спец-фильтр**: код специальности `09.01.03` в имени файла → таргетный поиск.

## Хранилище

- FAISS — `~/.teacherfactory/faiss_index/` (бинарь + pickle docstore из LangChain).
- BM25 — `~/.teacherfactory/faiss_index/bm25.json` (с версионированной схемой).
- Сгенерированные DOCX — `~/.teacherfactory/output/`.

Никаких pickle в нашем коде. FAISS использует pickle внутри — мы документируем
threat model в [`SECURITY.md`](SECURITY.md).

## Безопасность

См. [`SECURITY.md`](SECURITY.md) — отдельный документ.

## Что НЕ так в архитектуре прямо сейчас

Честный список (для контрибьюторов):

- `CONFIG` грузится на импорт модуля. Это удобно, но создаёт скрытую зависимость.
  Сейчас mitigations: `get_llm_provider(config_dict=...)` принимает явный конфиг
  для тестов. Долгосрочно — DI-контейнер.
- `views/` зависят от глобального `st.session_state`. Стриминговая природа
  Streamlit плохо тестируется — UI-смок только руками.
- В `embeddings.py` глобальный `_cache` без блокировок. Streamlit single-thread,
  но если когда-то отделим backend от UI — пересмотреть.
- `validate_competencies` делает по одному retrieval-запросу на код. На карте
  с 7 кодами это 7 запросов к индексу. Не критично, но кешировать стоит.
