"""
Все пути проекта в одном месте.

PROJECT_ROOT и USER_DATA_DIR — единственные «корни», от которых выводится
всё остальное. Это позволяет не дублировать `Path(__file__).parent.parent.parent`
по модулям.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # teacherfactory/
SRC_DIR = PROJECT_ROOT / "src"
DOCS_DIR = PROJECT_ROOT / "docs"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Пользовательские данные (вне репозитория, перестраиваются при необходимости)
USER_DATA_DIR = Path.home() / ".teacherfactory"
INDEX_DIR = USER_DATA_DIR / "faiss_index"
# Хранится в JSON (см. retrieval.save_bm25). Старые `.pkl` от прошлых версий
# можно безопасно удалить — индекс пересоберётся.
BM25_PATH = INDEX_DIR / "bm25.json"
SKIPPED_DOC_PATH = INDEX_DIR / "skipped_doc_files.txt"
OUTPUT_DIR = USER_DATA_DIR / "output"

# Активный шаблон технологической карты урока — собирается из docx Алёшкина
# скриптом `scratch/make_template_v2.py`. Старое имя ALESHIKN_TEMPLATE
# сохранено как алиас для обратной совместимости с user-кодом, успевшим
# на него сослаться.
LESSON_CARD_TEMPLATE = DOCS_DIR / "template_aleshkin_v2.docx"
ALESHKIN_TEMPLATE = LESSON_CARD_TEMPLATE
ALESHIKN_TEMPLATE = LESSON_CARD_TEMPLATE  # noqa: deprecated alias, исправлена опечатка

# Шаблон оценочных материалов (КОС/ФОС). Собирается отдельным скриптом.
ASSESSMENT_TEMPLATE = TEMPLATES_DIR / "template_assessment.docx"
