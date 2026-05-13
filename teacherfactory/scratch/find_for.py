import re
import sys

xml = open("scratch_preprocessed.xml", encoding="utf-8").read()
sys.stderr.write(f"len: {len(xml)}\n")
# Любые упоминания for/endfor/tr/step
for kw in [r"\{%[^%]*%\}", r"step", r"%tr", r"for "]:
    matches = list(re.finditer(kw, xml))
    sys.stderr.write(f"\nkw={kw!r}: {len(matches)} matches\n")
    for m in matches[:8]:
        s, e = max(0, m.start() - 60), min(len(xml), m.end() + 60)
        sys.stderr.write(f"  ...{xml[s:e]!r}...\n")
