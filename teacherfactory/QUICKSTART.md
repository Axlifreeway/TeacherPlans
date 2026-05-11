# 🚀 Быстрый старт TeacherFactory

## Установка

```bash
poetry install
```

Все зависимости берутся из `pyproject.toml` (включая `langchain-groq`).

## Вариант 1. Groq (рекомендуется для работы с методистом)

Плюсы: быстро, не нагружает ПК, бесплатно в рамках лимитов.

1. **Получи API-ключ** на <https://console.groq.com/keys>.
2. **Пропиши ключ** одним из способов:

   **A. Переменная окружения**

   ```powershell
   $env:GROQ_API_KEY = "gsk_..."   # PowerShell
   ```

   ```bash
   export GROQ_API_KEY="gsk_..."    # bash / zsh
   ```

   **B. `.env`**

   ```bash
   cp .env.example .env
   # открой .env и замени gsk_... на свой ключ
   ```

   **C. `config.local.toml`** (рядом с `config.default.toml`):

   ```toml
   [groq]
   api_key = "gsk_..."
   model = "llama-3.1-8b-instant"
   ```

   > **Важно:** ключ должен лежать в секции `[groq]`, а не в `[model]`. Иначе Groq молча уйдёт в недоступные.

3. **Запусти**:
   ```bash
   poetry run streamlit run src/teacherfactory/app.py
   ```
4. В сайдбаре проверь, что напротив `Groq` стоит ✅, и выбери его как активный провайдер.

## Вариант 2. Ollama (полностью локально и приватно)

Плюсы: нет лимитов, работает без интернета, данные не покидают ПК.

1. Установи Ollama: <https://ollama.com/>.
2. Загрузи модель:
   ```bash
   ollama pull llama3.1:8b
   ```
3. Запусти сервер (обычно стартует автоматически):
   ```bash
   ollama serve
   ```
4. В другом терминале:
   ```bash
   poetry run streamlit run src/teacherfactory/app.py
   ```
5. В сайдбаре должна быть ✅ напротив `Ollama`.

## Дать доступ методисту

Запусти TeacherFactory у себя (с Groq, чтобы не нагружать машину методиста) и прокинь HTTP-туннель.

**Cloudflare Tunnel** — рекомендуемый вариант:

```bash
cloudflared tunnel --url http://localhost:8501
```

Скопируй ссылку вида `https://random-name.trycloudflare.com` и пришли методисту.

**ngrok** — попроще, ссылка временная:

```bash
ngrok http 8501
```

Методист открывает ссылку в браузере — никаких установок не нужно.

## Структура проекта

```
teacherfactory/
├── src/teacherfactory/
│   ├── app.py              # Streamlit интерфейс
│   ├── llm_provider.py     # Единый интерфейс к Ollama/Groq
│   ├── generator.py        # Генерация карт + чат + RAG
│   ├── indexer.py          # Построение FAISS + BM25 индекса
│   ├── model.py            # Pydantic-модели карты урока
│   ├── config.py           # Загрузка конфигурации
│   └── rebuild_template.py # Регенерация template_fixed.docx (одноразовый)
├── tests/                  # Pytest-тесты
├── docs/                   # PDF/DOCX, по которым строится индекс
├── config.default.toml     # Настройки по умолчанию
├── config.local.toml       # Твои настройки (в .gitignore)
├── config.groq.example.toml
├── .env.example
└── template_fixed.docx     # DOCX-шаблон карты урока
```

## Подсказки по моделям Groq

| Модель | Когда брать |
|--------|-------------|
| `llama-3.1-8b-instant` | Дефолт. Быстро, дёшево, для типовых карт. |
| `llama-3.3-70b-versatile` | Сложные/спорные темы, когда 8B плывёт. |
| `gemma2-9b-it` | Альтернатива 8B. |
| `deepseek-r1-distill-llama-70b` | Когда нужно «рассуждение» по сложной педагогической задаче. |

Список моделей и лимиты Groq меняются — актуальное:
- модели: <https://console.groq.com/docs/models>
- лимиты: <https://console.groq.com/docs/rate-limits>

## Решение проблем

**❌ Ни один LLM-провайдер не доступен**

- Groq: проверь, что ключ лежит в секции `[groq]` (не `[model]`), без лишних пробелов/кавычек.
- Ollama: убедись, что `ollama serve` запущен, проверь `curl http://localhost:11434/api/tags`.

**❌ Ошибка аутентификации Groq**

- Возможно, ключ отозван — перевыпусти на <https://console.groq.com/keys>.
- Ключ должен начинаться с `gsk_`.

**❌ Model `xxx` is decommissioned**

- Groq иногда выпиливает старые модели (так было с `mixtral-8x7b-32768`, `gemma-7b-it`). Поставь актуальную из <https://console.groq.com/docs/models>.

**❌ Медленная генерация**

- Ollama: включи GPU — в `config.local.toml` поставь `num_gpu = -1`.
- Groq: переключись на `llama-3.1-8b-instant`, проверь интернет.

## Где почитать дальше

- `GROQ_README.md` — детально по Groq, моделям, безопасности и альтернативам.
- `ARCHITECTURE.md` — устройство пайплайна (RAG, провайдеры, валидация).
