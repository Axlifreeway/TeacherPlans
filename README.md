# TeacherPlans / TeacherFactory

Генератор образовательных документов для СПО на базе RAG.

Поверх нормативных документов (ФГОС, РПП, РПД) строится гибридный RAG-индекс
(FAISS + BM25 → RRF → cross-encoder), запросы идут к LLM (Ollama локально или
Groq в облаке), на выходе — структурированные DOCX. Сейчас умеет генерировать
**технологические карты урока**; архитектура спроектирована под расширение на
**РПД**, **аттестационные материалы**, **КОС** и другие типы документов.

Документация — в [`teacherfactory/`](teacherfactory/):

- [`teacherfactory/QUICKSTART.md`](teacherfactory/QUICKSTART.md) — установка и запуск
- [`teacherfactory/ARCHITECTURE.md`](teacherfactory/ARCHITECTURE.md) — слои, RAG-пайплайн, реестр документов
- [`teacherfactory/CONTRIBUTING.md`](teacherfactory/CONTRIBUTING.md) — как добавить новый тип документа
- [`teacherfactory/GROQ_README.md`](teacherfactory/GROQ_README.md) — подключение Groq
- [`teacherfactory/SECURITY.md`](teacherfactory/SECURITY.md) — secrets, threat model

## Статус

[![CI](https://github.com/Axlifreeway/TeacherPlans/actions/workflows/ci.yml/badge.svg)](https://github.com/Axlifreeway/TeacherPlans/actions/workflows/ci.yml)

Python 3.13. Лицензия — см. [`LICENSE`](LICENSE).
