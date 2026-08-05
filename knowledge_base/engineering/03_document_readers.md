# 03 — Document Readers

Reference for parsing the document formats the framework encounters: PDF (text and scanned), DOCX, XLSX, CSV, HTML.

---

## PDF — text-based with tabular content

**Examples:** Weekly sheriff sale PDFs, some records-request-delivered bulk extracts.

**Tool:** `pdfplumber==0.11.4`

**Pattern:**

```python
import pdfplumber

with pdfplumber.open(pdf_path) as pdf:
    all_rows = []
    for page in pdf.pages:
        # Extract a table per page (when layout is clear)
        table = page.extract_table()
        if table:
            all_rows.extend(table)
        else:
            # Fall back to text extraction + manual parsing
            text = page.extract_text()
            all_rows.extend(parse_text_lines(text))
```

**Quirks:**

1. **Multi-row records** — sheriff PDFs often have a record spanning 4-6 lines (case info on line 1, plaintiff on line 2, defendant on line 3, etc.). `extract_table()` won't catch this; you need to extract text and parse the multi-line groupings manually.

2. **Column-split bugs** — when the PDF's layout is column-based and a value crosses a column boundary, `extract_text()` mangles it. Use `page.extract_words()` and reconstruct rows from word coordinates:

```python
words = page.extract_words(keep_blank_chars=True)
# Group words by y-coordinate (same row)
rows = {}
for word in words:
    y = round(word["top"])
    rows.setdefault(y, []).append(word)
```

3. **Table extraction settings** — for complex layouts, tune `extract_table()`:

```python
table = page.extract_table({
    "vertical_strategy": "lines",  # use ruling lines as column separators
    "horizontal_strategy": "text",  # use text alignment for rows
    "min_words_vertical": 3,
})
```

4. **Encrypted/protected PDFs** — `pdfplumber` raises on encrypted PDFs. Detect and route to manual operator handling.

---

## PDF — scanned (no text layer)

**Examples:** older county documents, records-request responses delivered as scans.

**Tools:**
- `pdf2image==1.17.0` for converting pages to images (requires Poppler installed at OS level)
- `pytesseract==0.3.13` for OCR (requires Tesseract installed at OS level)

**Pattern:**

```python
from pdf2image import convert_from_path
import pytesseract

images = convert_from_path(pdf_path, dpi=300)  # 300 DPI is the OCR sweet spot
text_pages = []
for img in images:
    text = pytesseract.image_to_string(img, lang="eng")
    text_pages.append(text)
all_text = "\n".join(text_pages)
```

**Quirks:**

1. **Tesseract install** — required separately. On Windows: `choco install tesseract`. Set `pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"` if not on PATH.

2. **Poppler install** — required for `pdf2image`. On Windows: download Poppler binaries, add to PATH or pass `poppler_path=r"C:\path\to\poppler\bin"` to `convert_from_path`.

3. **Accuracy:** OCR is 95%+ on clean scans, drops fast on poor scans. Always validate field formats post-OCR (dates parse, dollar amounts parse, parcel IDs match expected pattern).

4. **Don't OCR PDFs that have a text layer.** Always try `pdfplumber` first; only fall back to OCR if `extract_text()` returns empty.

---

## PDF — fast text extraction (when speed matters)

**Tool:** `PyMuPDF==1.24.13` (imported as `fitz`)

**Use when:** text-only extraction on large PDFs (50+ pages), where `pdfplumber`'s table-extraction overhead isn't needed.

**Pattern:**

```python
import fitz

doc = fitz.open(pdf_path)
all_text = []
for page in doc:
    all_text.append(page.get_text())
doc.close()
text = "\n".join(all_text)
```

**Speed:** roughly 5-10x faster than `pdfplumber` for plain text extraction. Use for large bulk records-request responses.

---

## PDF — form filling and generation

**Examples:** records-request PDFs (`pipeline/records_request.py`).

**Tool:** `reportlab==4.2.5` for generation, `pypdf==5.1.0` for filling existing forms.

**Pattern (generation from scratch):**

```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate(out_path, pagesize=letter, topMargin=0.75*inch)
styles = getSampleStyleSheet()
story = [
    Paragraph("Public Records Request — County Clerk", styles["Title"]),
    Spacer(1, 0.2*inch),
    Paragraph("...", styles["Normal"]),
]
doc.build(story)
```

**Pattern (filling AcroForm fields):**

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader(template_path)
writer = PdfWriter(clone_from=reader)
writer.update_page_form_field_values(
    writer.pages[0],
    {"requester_name": "<OPERATOR_NAME>", "request_date": "2026-05-05"},
)
with open(out_path, "wb") as f:
    writer.write(f)
```

---

## DOCX — Word documents

**Tools:**
- `python-docx==1.1.2` for read/write
- `mammoth==1.8.0` for converting DOCX to plain text or HTML (cleaner output for ingest)

**Read pattern:**

```python
from docx import Document

doc = Document(docx_path)
paragraphs = [p.text for p in doc.paragraphs]
tables = []
for table in doc.tables:
    rows = [[cell.text for cell in row.cells] for row in table.rows]
    tables.append(rows)
```

**Mammoth (HTML conversion):**

```python
import mammoth

with open(docx_path, "rb") as f:
    result = mammoth.convert_to_html(f)
html = result.value
```

**Write pattern:**

```python
from docx import Document

doc = Document()
doc.add_heading("Title", level=1)
doc.add_paragraph("Body text.")
doc.save(out_path)
```

**Quirks:**

1. **Table extraction** — merged cells in DOCX tables produce duplicate text in `cell.text`. Detect via `cell._tc` and the `gridSpan` element.

2. **DOC (legacy) format** — `python-docx` does not handle .doc (binary) files. Operator must convert .doc → .docx first (Word does this automatically on save-as).

---

## XLSX — Excel spreadsheets

**Tool:** `openpyxl==3.1.5`

**Read pattern:**

```python
import openpyxl

wb = openpyxl.load_workbook(xlsx_path, data_only=True)  # data_only resolves formulas
ws = wb.active  # or wb["SheetName"]
header = [cell.value for cell in ws[1]]
rows = []
for row in ws.iter_rows(min_row=2, values_only=True):
    rows.append(dict(zip(header, row)))
```

**Write pattern:**

```python
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Leads"
ws.append(["pid", "owner", "score"])
for record in records:
    ws.append([record["pid"], record["owner"], record["score"]])
wb.save(out_path)
```

**Quirks:**

1. **`data_only=True`** is essential when reading formula cells. Without it, `cell.value` returns the formula string (`=SUM(A1:A10)`) instead of the computed value. The cached value is only present if Excel saved the file (not all sources do).

2. **Date handling:** openpyxl returns dates as Python `datetime` objects when the cell is date-formatted. When the cell is text-formatted but contains a date string, you get a string. Always check type before parsing.

3. **Large files:** openpyxl loads everything in memory. For files > 100 MB, use `read_only=True`:
```python
wb = openpyxl.load_workbook(path, read_only=True)
```

---

## CSV

**Tool:** `csv` module (stdlib) — always sufficient.

**Read pattern:**

```python
import csv
from pathlib import Path

with Path(csv_path).open(encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        process(row)
```

**Quirks:**

1. **Encoding** — always specify `encoding="utf-8"`. Operator-delivered CSVs from county portals are sometimes `cp1252` (Windows default). Detect by trying utf-8 first, falling back to `cp1252` on `UnicodeDecodeError`:

```python
try:
    text = path.read_text(encoding="utf-8")
except UnicodeDecodeError:
    text = path.read_text(encoding="cp1252")
```

2. **Delimiter detection** — most CSVs are comma-delimited, but some county exports use semicolons or tabs. Use `csv.Sniffer`:

```python
sample = path.read_text(encoding="utf-8")[:8192]
dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
```

3. **Header normalization** — county CSVs use inconsistent column names (sometimes `parcel_id`, sometimes `parcel id`, sometimes `Parcel ID`, sometimes `PID`). Normalize at read time:

```python
def normalize_header(s):
    return s.strip().lower().replace(" ", "_").replace("-", "_")
```

The framework keeps a synonym map per source: `engineering/synonyms/<source>.json`.

---

## HTML

**Tools:**
- `BeautifulSoup4==4.12.3` with `lxml==5.3.0` parser

**Pattern:**

```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(html_text, "lxml")
rows = soup.select("table.results tr")
for row in rows:
    cells = [td.get_text(strip=True) for td in row.select("td")}
```

**Selector preferences (in order):**

1. CSS selectors via `.select()` and `.select_one()` — most maintainable
2. Find by attribute via `.find(attrs={"data-id": "..."})` — when CSS selectors are ambiguous
3. XPath via `lxml.etree` — only when CSS can't express what you need

**Quirks:**

1. **Mixed content** — `cell.get_text()` returns concatenated text from all child elements. Use `cell.get_text(separator=" ", strip=True)` to insert spaces between elements (preserves multi-line cell content).

2. **Encoded entities** — `&amp;`, `&nbsp;`, `&#39;` — BeautifulSoup decodes them automatically. If you see them in output, you're probably reading raw HTML, not parsed.

3. **Malformed HTML** — `lxml` parser is forgiving; `html.parser` (stdlib) sometimes fails on bad input. If `lxml` fails too, try `html5lib` (slowest, most forgiving): `pip install html5lib`.

---

## JSON / JSONL

**Tool:** `json` module (stdlib)

**Pattern (one record per line, the framework's standard):**

```python
import json
from pathlib import Path

# Write
with Path(out_path).open("w", encoding="utf-8") as f:
    for record in records:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

# Read
records = []
with Path(in_path).open(encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))
```

**Quirks:**

1. **`ensure_ascii=False`** — without this, non-ASCII characters get escaped as `\uXXXX`. The framework's data is human-readable JSONL so we keep them literal.

2. **`indent=2`** for `leads.json` only (the dashboard input). JSONL files are one-record-per-line with no indent.

3. **Atomic writes** — when overwriting `leads.json`, write to `leads.json.tmp` first, then rename:

```python
tmp = out_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
tmp.replace(out_path)
```

This prevents the dashboard from reading a half-written file if the build is interrupted.

---

## Schema validation

**Tool:** `jsonschema==4.23.0`

**Pattern:**

```python
import jsonschema

schema = json.loads(Path("schema/leads.schema.json").read_text())
data = json.loads(Path("data/leads.json").read_text())
jsonschema.validate(data, schema)  # raises ValidationError on mismatch
```

**Strategy:** the framework ships a JSON Schema for `leads.json` and validates before write. Schema drift is caught at build time, not at dashboard load time.
