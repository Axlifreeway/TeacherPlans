"""Дамп предобработанного docxtpl XML — увидеть, что jinja получает."""

from pathlib import Path

from docxtpl import DocxTemplate

src = "docs/template_aleshkin_v2.docx"
doc = DocxTemplate(src)

# Воспроизведём первый шаг render: получим XML, прогнанный через docxtpl patches.
doc.init_docx()
xml = doc.get_xml()
xml = doc.patch_xml(xml)
out = Path("scratch_preprocessed.xml")
out.write_text(xml, encoding="utf-8")
print(f"Дамп: {out} ({len(xml)} симв.)")
