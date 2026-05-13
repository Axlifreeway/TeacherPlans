"""Печатаем контекст вокруг каждого {% for ... %} в предобработанном XML."""

import re
import sys

xml = open("scratch_preprocessed.xml", encoding="utf-8").read()
for m in re.finditer(r"\{%\s*(?:for\s+\w+|endfor)\s*[\w\s]*%\}", xml):
    start = max(0, m.start() - 100)
    end = min(len(xml), m.end() + 100)
    sys.stderr.write("=" * 60 + "\n")
    sys.stderr.write(repr(xml[start:end]) + "\n")
