"""Smoke-check для UI запуска: всё импортируется, шаблоны на месте."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Импорты, на которые опирается app.py
import teacherfactory.app  # noqa: F401
from teacherfactory.documents import list_document_types
from teacherfactory.model import LessonCard

sys.stderr.write("imports OK\n")

# Сколько required полей в схеме LessonCard?
schema = LessonCard.model_json_schema()
required = schema.get("required", [])
sys.stderr.write(f"\nLessonCard.required: {len(required)} полей\n")
for f in required:
    sys.stderr.write(f"  - {f}\n")

sys.stderr.write("\nDocumentType registry:\n")
for dt in list_document_types():
    ok = dt.template_path.exists()
    sys.stderr.write(f"  - {dt.slug}: template={dt.template_path.name} ({'OK' if ok else 'MISSING'})\n")
