import PyPDF2
from pathlib import Path
import re

pdf_path = Path(r"docs\KII_RPD_OPC_09.01.03_Operator_informacionnyx_sistem_i_resursov_OFO_2025_(28.02.2025)(1).pdf")
with open(pdf_path, "rb") as f:
    reader = PyPDF2.PdfReader(f)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"

# Search for "Базы данных" topics table
# Usually "ОПЦ.03 Базы данных" or similar.
lines = text.split('\n')
for i, line in enumerate(lines):
    if "ОПЦ.03" in line and "Базы данных" in line:
        print(f"Found at line {i}: {line}")
        print("\n".join(lines[i:i+30]))
        break
