"""Дамп сырого document.xml из template_aleshkin_v2.docx."""

import sys
import zipfile
from pathlib import Path

dst = Path("scratch_raw.xml")
with zipfile.ZipFile("docs/template_aleshkin_v2.docx") as zf:
    xml = zf.read("word/document.xml").decode("utf-8")

dst.write_text(xml, encoding="utf-8")
sys.stderr.write(f"raw size: {len(xml)}\n")

# Найти {%tr  / {%p  в сыром XML
import re

for kw in [r"\{%tr", r"\{%p", r"\{\{", r"step", r"\{%", "endfor"]:
    matches = list(re.finditer(kw, xml))
    sys.stderr.write(f"{kw!r}: {len(matches)} matches\n")
