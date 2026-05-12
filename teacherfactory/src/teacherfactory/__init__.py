"""TeacherFactory — генератор документов СПО на базе RAG."""

from teacherfactory.documents import (
    DocumentType,
    get_document_type,
    list_document_types,
)
from teacherfactory.pipeline import generate_document, stream_chat_response
from teacherfactory.render import build_output_filename, render_document

__all__ = [
    "DocumentType",
    "build_output_filename",
    "generate_document",
    "get_document_type",
    "list_document_types",
    "render_document",
    "stream_chat_response",
]
