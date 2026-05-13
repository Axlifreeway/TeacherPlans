import re
import sys

xml = open("scratch_preprocessed.xml", encoding="utf-8").read()
matches = re.findall(r"\{%[^%]+%\}", xml)
sys.stderr.write(f"total: {len(matches)}\n")
for m in matches:
    sys.stderr.write(m + "\n")
