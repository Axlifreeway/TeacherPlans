# Security

## Threat model

TeacherFactory предназначен для запуска:
- **локально на машине преподавателя** (основной сценарий);
- **в Docker-контейнере на доверенной инфраструктуре** (с туннелем для удалённого доступа).

**Доверяем:**
- содержимому `~/.teacherfactory/` и рабочей директории — кто туда пишет, у того уже есть полный доступ к учётной записи;
- LLM-провайдеру (Groq / локальной Ollama) — мы отправляем им контекст и параметры карты.

**Не доверяем:**
- пользовательскому вводу (имена дисциплин, темы, пр.) → санитизируем при формировании имён файлов;
- содержимому документов в `docs/` — это нормативные PDF/DOCX, могут быть malformed → ловим исключения, не падаем.

## Управление секретами

### Где брать `GROQ_API_KEY`

Приоритет (от высокого к низкому):
1. `config.local.toml` секция `[groq] api_key`
2. environment variable `GROQ_API_KEY`

В коде ключ хранится в **`pydantic.SecretStr`** — он:
- не показывается в `repr()` / `str()` / трейсбеках;
- доступен только через явный `.get_secret_value()`;
- не пишется в логи при default-форматировании Pydantic-объектов.

### Что в `.gitignore`

```
.env
config.local.toml
*.pkl
faiss_index/
output/
```

### Что в pre-commit

- **`gitleaks`** — ищет утечки секретов *до* коммита. Конфиг в [`.gitleaks.toml`](../.gitleaks.toml).
  Правило `groq-api-key` ловит ключи `gsk_...`.
- **`detect-private-key`** — встроенный хук pre-commit.
- **`check-added-large-files`** — отсекает попытки закоммитить >500 КБ.

Установка:
```bash
poetry run pre-commit install
poetry run pre-commit run --all-files
```

### В CI

GitHub Actions job `secrets-scan` гоняет `gitleaks` на каждый push/PR.
Красный CI → нельзя смержить.

## Если ключ утёк

1. Отзови ключ в https://console.groq.com/keys (одна кнопка).
2. Выпусти новый.
3. Положи только в **одно место** (`.env` или env var) — не дублируй.
4. Если ключ попал в git-историю: `git filter-repo` / BFG, форс-пуш, и
   считай ключ скомпрометированным навсегда (Groq уже ничего не вернёт).

## Десериализация

### BM25 — JSON, не pickle

С версии после рефакторинга BM25 хранится как JSON, при загрузке модель
пересобирается из `BM25Okapi(corpus)` (миллисекунды). Pickle убран.

### FAISS — `allow_dangerous_deserialization=True`

FAISS внутри LangChain хранит docstore через pickle — это устройство либы, его
не обойти. **Threat model**: индекс лежит в `~/.teacherfactory/`, доступ туда
имеет только владелец машины. Если у атакующего есть write в твой home —
проект пора закрывать, а не индекс хешировать.

В контейнере индекс лежит в named volume `teacherfactory_data`. Доступ к нему
имеет только пользователь `app` (uid 1000).

## Санитизация ввода

`render.build_output_filename`:
- заменяет всё кроме `[A-Za-z0-9 ._-]` на `_`;
- схлопывает `..` (защита от path traversal);
- режет результат до последнего компонента (`PurePosixPath(...).name`);
- fallback на `"untitled"` для пустых строк.

Тесты в `tests/test_render.py` проверяют:
- `../../etc/passwd` → безопасное имя;
- NULL-байты убраны;
- multi-dots не остаются;
- pattern с `../` в `DocumentType.filename_pattern` всё равно даёт чистое имя.

## Доступ через интернет

`ARCHITECTURE.md` упоминает Cloudflare Tunnel для удалённого доступа методиста.
**Без аутентификации Streamlit публично доступен любому**, кто узнал URL.

Минимум для production:
- `streamlit-authenticator` или basic-auth через reverse-proxy (nginx/traefik);
- IP allow-list на стороне туннеля;
- HTTPS обязательно (Cloudflare Tunnel это делает сам).

Не выкатывай без аутентификации — это твой ключ Groq тратится.

## Куда сообщать

Найдена уязвимость или утечка? Открой private GitHub Security Advisory или
напиши на 129040902+Axlifreeway@users.noreply.github.com.
