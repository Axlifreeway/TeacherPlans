"""
Рендеринг сгенерированной модели в DOCX через docxtpl.

Работает с любым `DocumentType`: контекст шаблона берётся либо из
`doc_type.to_template_context(instance)`, либо из `instance.model_dump()`
по умолчанию.
"""

import logging
import re
from pathlib import Path, PurePosixPath

from docxtpl import DocxTemplate
from jinja2 import UndefinedError
from pydantic import BaseModel

from teacherfactory.documents.base import DocumentType

log = logging.getLogger(__name__)


def render_document[T: BaseModel](
    doc_type: DocumentType[T],
    instance: T,
    output_path: Path,
) -> Path:
    """Отрендерить документ в DOCX по шаблону `doc_type.template_path`."""
    if doc_type.to_template_context is not None:
        context = doc_type.to_template_context(instance)
    else:
        context = instance.model_dump()

    doc = DocxTemplate(str(doc_type.template_path))

    try:
        doc.render(context)
    except UndefinedError as e:
        # Шаблон ссылается на поле, которого нет в модели. Падать с
        # пустым ходом занятия — ужас (на это нарывалась прошлая
        # реализация). Лучше шумно сообщить наверх.
        log.error(
            "Шаблон %s ссылается на поле, которого нет в модели: %s", doc_type.template_path.name, e
        )
        raise

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    log.info("Документ сохранён: %s", output_path)
    return output_path


def build_output_filename[T: BaseModel](doc_type: DocumentType[T], params: dict) -> str:
    """Имя выходного файла по `filename_pattern` документа.

    Санитизирует значения, чтобы избежать path traversal: убираем
    разделители путей, NULL-байты, последовательности `..` и сводим
    результат к одному имени файла (без подпапок).
    """
    safe_params = {k: _sanitize(v) if isinstance(v, str) else v for k, v in params.items()}
    name = doc_type.filename_pattern.format(**safe_params)
    # Финальный страховочный слой: даже если pattern содержит «/», обрезаем.
    return _strip_to_filename(name)


_BAD_NAME_CHARS = re.compile(r"[^\w\-. ]")
_MULTI_DOTS = re.compile(r"\.{2,}")


def _sanitize(value: str) -> str:
    """Заменяем всё, что не буква/цифра/пробел/дефис/точка, на «_»."""
    cleaned = _BAD_NAME_CHARS.sub("_", value)
    # Запрещаем `..` — даже после замены `/` пользователь мог подсунуть
    # `..` (если бы pattern их пропускал). Лучше схлопнуть до одной точки.
    cleaned = _MULTI_DOTS.sub(".", cleaned).strip(" .")
    return cleaned or "untitled"


def _strip_to_filename(name: str) -> str:
    """Из полного имени-с-разделителями оставляем только последний компонент."""
    return PurePosixPath(name.replace("\\", "/")).name or "untitled"
