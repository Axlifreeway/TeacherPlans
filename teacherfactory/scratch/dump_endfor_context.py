"""Печатаем контекст вокруг каждого {% endfor %} в предобработанном XML."""

import re
import sys

xml = open("scratch_preprocessed.xml", encoding="utf-8").read()
for m in re.finditer(r"\{%\s*endfor\s*%\}", xml):
    start = max(0, m.start() - 200)
    end = min(len(xml), m.end() + 200)
    sys.stderr.write("=" * 80 + "\n")
    sys.stderr.write(xml[start:end] + "\n")
