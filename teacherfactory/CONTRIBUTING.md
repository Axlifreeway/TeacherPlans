# Contributing

## Локальная разработка

```bash
poetry install
poetry run pre-commit install   # хуки на pre-commit
make check                      # lint + type + test
```

Перед PR — обязательно `make check`. CI прогоняет то же самое.

## Добавление нового типа документа

Цель: чтобы добавить **РПД**, **аттестационные материалы** или **КОС**, не
надо трогать `pipeline.py`, `retrieval.py` или `views/`. Только новый файл в
`documents/` и регистрация.

### Шаг 1 — Pydantic-модель

Опиши схему ответа LLM. Лучше отдельным файлом, если модель крупная.

```python
# src/teacherfactory/models/rpd.py
from pydantic import BaseModel, Field

class RPDSection(BaseModel):
    title: str = Field(description="Название раздела")
    hours: int = Field(description="Часы")
    content: str = Field(description="Содержание")

class RPD(BaseModel):
    discipline: str
    specialty: str
    total_hours: int
    sections: list[RPDSection]
    competencies_ok: str
    competencies_pk: str
```

### Шаг 2 — Шаблон DOCX

Положи `templates/rpd.docx` с jinja-плейсхолдерами через `docxtpl`:

```
{{ discipline }} — {{ specialty }}

{% tr for s in sections %}
{{ s.title }} | {{ s.hours }} ч
{% tr endfor %}
```

### Шаг 3 — Промпты

```python
# src/teacherfactory/prompts.py (дополни)
RPD_SYSTEM_PROMPT = """Ты — методист СПО. Составь РПД на основе ФГОС..."""

RPD_USER_PROMPT = """Дисциплина: {discipline}
Специальность: {specialty}
Всего часов: {total_hours}
..."""
```

### Шаг 4 — Регистрация типа

```python
# src/teacherfactory/documents/rpd.py
from teacherfactory.documents.base import DocumentType
from teacherfactory.models.rpd import RPD
from teacherfactory.paths import TEMPLATES_DIR
from teacherfactory.prompts import RPD_SYSTEM_PROMPT, RPD_USER_PROMPT


def build_rpd_queries(params: dict) -> list[str]:
    return [
        f"РПД {params['discipline']} {params['specialty']}",
        f"содержание дисциплины {params['discipline']}",
        f"компетенции {params['specialty']}",
    ]


RPD_TYPE: DocumentType[RPD] = DocumentType(
    slug="rpd",
    title="Рабочая программа дисциплины",
    model=RPD,
    template_path=TEMPLATES_DIR / "rpd.docx",
    system_prompt=RPD_SYSTEM_PROMPT,
    user_prompt=RPD_USER_PROMPT,
    build_queries=build_rpd_queries,
    filename_pattern="РПД_{discipline}_{specialty}.docx",
    required_params=("discipline", "specialty", "total_hours"),
)
```

### Шаг 5 — Подключение к реестру

```python
# src/teacherfactory/documents/__init__.py
from teacherfactory.documents.rpd import RPD_TYPE

_REGISTRY: dict[str, DocumentType[Any]] = {
    LESSON_CARD.slug: LESSON_CARD,
    RPD_TYPE.slug: RPD_TYPE,         # ← одна строка
}
```

### Шаг 6 — Тесты

В `tests/test_documents.py` тесты проходят автоматически (они итерируют по
реестру). Добавь специфичные для РПД тесты по образцу `test_pipeline.py`:

- required_params реально валидируются;
- build_queries возвращает осмысленные запросы;
- `to_template_context` (если нужен кастомный) рендерится корректно.

### Шаг 7 — UI (опционально)

Если хочется отдельную вкладку — скопируй `views/single.py` и поменяй
ссылку с `LESSON_CARD` на `RPD_TYPE`. Либо сделай универсальную вкладку
с dropdown по `list_document_types()`.

## Code style

- **Ruff** — линт и форматирование. `make format` чинит автоматом.
- **Mypy** — типы. Сейчас не `--strict`, но `check_untyped_defs=true`.
- Type hints обязательны на публичных функциях; для приватных — желательны.
- Импорты — пакетные (`from teacherfactory.X import Y`). `sys.path` —
  смерть на месте.
- Docstrings на русском (это языковой контекст проекта). Стиль — компактный.

## Тесты

- Каждый новый модуль → отдельный `tests/test_<module>.py`.
- Минимум на новый `DocumentType` — проверки regех'ов, queries, required_params.
- Покрытие ниже 65% → CI красный.

## Коммиты

- Маленькие, атомарные. Один логический change = один коммит.
- Сообщение: что и зачем (не «обновил файлы»).
