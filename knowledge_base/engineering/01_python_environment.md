# 01 — Python Environment

This file documents the Python environment the framework targets. The operator runs Windows; commands assume PowerShell unless noted otherwise.

---

## Python version

**Required:** Python 3.12.x

**Why 3.12 specifically:**
- `httpx` 0.27+ requires 3.8+, no upper bound
- `playwright` 1.40+ requires 3.8+, no upper bound
- `pdfplumber` 0.10+ requires 3.8+, no upper bound
- 3.12 has the best performance for our parsing workloads (faster string ops, faster dict)
- 3.12 is current stable as of build time, not bleeding-edge (3.13 had pip ecosystem gaps when 3.12 was the standard)

**Where it's installed (Windows operator):**

```
C:\Users\Owner\AppData\Local\Programs\Python\Python312\python.exe
```

**Invocation alias:**

```powershell
py -3.12
```

The `py` launcher is part of the Python for Windows installer. It picks the right version from any `py -3.X` invocation. **Use `py -3.12` in all scripts and scheduled tasks**, never `python` alone — the latter resolves to whatever's first on PATH and can change.

---

## Why not virtualenv

The framework does NOT use virtualenvs by default. Reason: the operator's environment is single-purpose (the framework is the only Python project on this machine for this work), and the daily-refresh scheduled task is simpler when it doesn't have to activate a venv before running.

When the operator wants isolation (multiple projects on same machine), the framework supports venv via:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Then all `py -3.12` commands become `python` (because the venv's python is on PATH).

For now, the assumption is no venv. The framework documents this so a future operator doesn't have to guess.

---

## pip install conventions

**Always use `--break-system-packages` flag** when installing globally on the operator's machine. Some Python installations (particularly newer Linux ones, less so Windows) refuse global pip installs without this flag. Including it always is harmless and prevents one-off failures.

**Pattern:**
```powershell
py -3.12 -m pip install <package> --break-system-packages
```

**For Linux / macOS development environments:**
```bash
pip install <package> --break-system-packages
```

**Quiet mode for build scripts** (suppresses progress noise in scheduled-task logs):
```powershell
py -3.12 -m pip install -q <package> --break-system-packages
```

---

## Required packages — pinned versions

The framework depends on specific versions tested against the source landscape. Newer versions may work but are not verified.

**Core HTTP:**
```
requests==2.32.3
httpx==0.27.2
urllib3==2.2.3
```

**Parsing:**
```
beautifulsoup4==4.12.3
lxml==5.3.0
```

**Browser automation:**
```
playwright==1.49.0
```
After `pip install playwright`, run `py -3.12 -m playwright install chromium` to download the browser binary. This is a separate step that must run once per machine.

**PDF tooling:**
```
pdfplumber==0.11.4
PyMuPDF==1.24.13
pypdf==5.1.0
```

**Document tooling:**
```
python-docx==1.1.2
openpyxl==3.1.5
mammoth==1.8.0
```

**OCR (optional, only when scanned PDFs are encountered):**
```
pytesseract==0.3.13
pdf2image==1.17.0
```
Note: `pytesseract` requires the Tesseract binary installed separately on the OS. On Windows, install via `choco install tesseract`. On Linux, `apt-get install tesseract-ocr`.

`pdf2image` requires `poppler` installed separately. On Windows, install poppler binaries and add to PATH.

**Reporting:**
```
reportlab==4.2.5
```
Used by `pipeline/records_request.py` to generate signature-ready records-request PDFs.

**Data analysis (optional):**
```
pandas==2.2.3
numpy==2.1.3
```
Only needed when scrapers do statistical aggregation. Most scrapers don't need pandas; use it sparingly because it adds 30+ MB to the install.

**Dev / verification:**
```
jsonschema==4.23.0
```

---

## Installing all dependencies

**One-shot install command:**

```powershell
py -3.12 -m pip install --break-system-packages requests==2.32.3 httpx==0.27.2 beautifulsoup4==4.12.3 lxml==5.3.0 playwright==1.49.0 pdfplumber==0.11.4 PyMuPDF==1.24.13 pypdf==5.1.0 python-docx==1.1.2 openpyxl==3.1.5 mammoth==1.8.0 reportlab==4.2.5 jsonschema==4.23.0
```

Then:

```powershell
py -3.12 -m playwright install chromium
```

The framework also ships `requirements.txt` for `pip install -r` workflows.

---

## Windows-specific considerations

### Path handling

Always use `pathlib.Path` for cross-platform path handling, even on Windows-only deployments. This makes the framework portable to Linux when the operator eventually moves to a server.

```python
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
```

Avoid string concatenation with `\\` or hardcoded `C:\` paths.

### Encoding

Windows defaults to `cp1252` for file I/O when `encoding=` is not specified. **Always specify `encoding="utf-8"`** when reading or writing files. This prevents the cryptic `UnicodeDecodeError` on records containing non-ASCII characters (common in owner names, addresses).

```python
text = path.read_text(encoding="utf-8")
path.write_text(content, encoding="utf-8")
```

### Console output encoding

PowerShell defaults to `cp1252` console encoding. Print statements with non-ASCII characters fail with a cryptic encoding error. Force UTF-8 console output at script entry:

```python
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
```

This is required for any script that prints owner names, addresses, or scraper output to console.

### Line endings

Git on Windows defaults to converting LF → CRLF on checkout. The framework's files are LF (Unix-style). Set `core.autocrlf` to `input` to preserve LF:

```bash
git config --global core.autocrlf input
```

The framework's `.gitattributes` enforces LF for `.py`, `.md`, `.json`, `.yml` files regardless of the global setting.

---

## Scheduled task invocation

Daily refresh runs via Windows Task Scheduler. The task XML invokes:

```
Program: C:\Users\Owner\AppData\Local\Programs\Python\Python312\python.exe
Arguments: pipeline\refresh.py --push
Working Directory: C:\Dev\xcerebro-builds\projects\<county>-intel
```

**Critical:** the task must be configured to run with **stored credentials** (not interactive token), so it runs whether the operator is logged in or not. PowerShell command:

```powershell
schtasks /create /xml scripts\daily_refresh.xml /tn "<county>-intel-refresh" /ru <COMPUTERNAME>\<USER> /rp <password> /f
```

The autonomous build cannot acquire the password. The operator runs this command once after the framework lands.

---

## Environment variables

The framework reads from `.env` in the project root (gitignored). Required keys vary per county; common ones:

```
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_CHAT_ID=<operator user ID>

# Per-source as needed:
CLERK_SESSION_COOKIES=<seeded clerk cookies>
CLERK_SESSION_TOKEN=<X-RequestVerificationToken>
CLERK_SESSION_SEEDED_AT=<ISO timestamp>

# Optional CAPTCHA solver:
TWOCAPTCHA_API_KEY=<from 2captcha.com>
ANTICAPTCHA_API_KEY=<from anti-captcha.com>

# Optional residential proxy:
PROXY_USERNAME=
PROXY_PASSWORD=
PROXY_ENDPOINT=
```

The framework uses `python-dotenv` lazily — `.env` is loaded only when env vars aren't already set, allowing CI/CD environments to override via real environment variables.

---

## What not to do

- Don't pin `pip` itself. Let it update via `python -m pip install --upgrade pip`.
- Don't install with `--user` flag — the scheduled task runs as the operator user, so global install is correct.
- Don't mix `py -3.11` and `py -3.12` calls. Pick one (3.12) and use it everywhere.
- Don't use `pip3` — on Windows it's an inconsistent alias. Use `py -3.12 -m pip` always.
- Don't import packages that aren't in the pinned list without adding them to this file first. The framework's reproducibility depends on this list staying authoritative.
