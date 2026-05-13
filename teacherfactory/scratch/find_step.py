import re
import sys

xml = open("scratch_preprocessed.xml", encoding="utf-8").read()
sys.stderr.write(f"raw len: {len(xml)}\n")
for kw in ["step", "lesson_structure", "for ", "{%", "{{r ", "%}", "comp", "out."]:
    matches = list(re.finditer(re.escape(kw), xml))
    sys.stderr.write(f"{kw!r}: {len(matches)} matches\n")
    for m in matches[:3]:
        s, e = max(0, m.start() - 50), min(len(xml), m.end() + 50)
        sys.stderr.write(f"   ...{xml[s:e]!r}...\n")
