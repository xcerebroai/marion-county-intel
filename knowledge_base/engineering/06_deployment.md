# 06 — Deployment

The framework deploys every county build to GitHub Pages. This file documents the conventions, the scheduled-task setup, and the alerting wiring.

---

## Why GitHub Pages

- Free, zero infrastructure
- CDN-backed (CloudFront-equivalent, sub-100ms TTFB worldwide)
- HTTPS automatic via Let's Encrypt
- Static-site model matches the framework's output shape (one `index.html`, one `data/leads.json`, supporting assets)
- Versioned via git — every build is a commit, history is the audit trail
- Auto-rollback is just `git revert + push`

The framework does NOT use Vercel, Netlify, Cloudflare Pages, S3, or any other static host by default. Only switch if the operator has a specific reason (custom domain SSL chain, server-side rendering need, etc.).

---

## Repository layout

```
<county>-intel/
├── index.html                      # dashboard entrypoint
├── methodology.html                # how-this-works page (rendered from build_methodology.py)
├── data/
│   ├── leads.json                  # primary dashboard input
│   ├── quality_metrics.json        # per-build metric snapshot
│   ├── review_queue.jsonl          # records held back from auto-export
│   └── raw/                        # raw scraper outputs (gitignored)
├── pipeline/                       # build scripts
│   ├── build_leads.py
│   ├── build_methodology.py
│   ├── refresh.py
│   ├── verify.py
│   ├── records_request.py
│   └── deal_path_classifier.py
├── scrapers/                       # one module per source
│   ├── parcel_master.py
│   ├── sheriff_pdf.py
│   ├── tax_collector.py
│   ├── clerk_seeded.py
│   └── clerk_records_delivery_ingest.py
├── records_delivery/               # generated request PDFs (gitignored except templates)
│   └── _templates/
├── scripts/
│   ├── daily_refresh.xml           # Windows Task Scheduler XML
│   └── watchdog.xml                # watchdog scheduled task XML
├── HEARTBEAT.json                  # last successful refresh per source
├── LIVE_VERIFIED.txt               # last verifier success record (committed)
├── BUILD_BROKEN.md                 # written on auto-rollback (committed)
├── BUILD_SUMMARY.md                # written on successful build (committed)
├── RECON.md                        # source map + access patterns (committed)
├── README.md
├── requirements.txt
└── .gitignore
```

---

## Repository naming convention

`<county>-intel` for a single-county build (e.g., `<county_id>-intel`).

For multi-county work, `<state_code>-<region>-intel` (substituting the target state and region identifiers).

GitHub username: `xcerebroai` (operator's primary org).

---

## GitHub Pages enablement

After the first commit:

1. Go to `https://github.com/xcerebroai/<repo>/settings/pages`
2. Set **Source** to "Deploy from a branch"
3. Set **Branch** to `main`, folder `/` (root)
4. Save

GitHub returns a Pages URL like `https://xcerebroai.github.io/<repo>/`. This is the live dashboard URL.

**The first deploy takes 1-3 minutes.** Subsequent deploys flush in 30-90 seconds.

---

## CDN cache headers

GitHub Pages serves static files with default cache headers (10 minutes for HTML, longer for assets). The dashboard fetches `data/leads.json` with a cache-buster:

```javascript
fetch(`data/leads.json?t=${Date.now()}`).then(r => r.json())
```

This bypasses the CDN cache and ensures fresh data on every page load.

The verifier (`pipeline/verify.py`) similarly uses `Cache-Control: no-cache` headers when polling for CDN flush:

```python
r = requests.get(LEADS_URL, headers={"Cache-Control": "no-cache"})
```

---

## Push pattern

The framework uses `git push origin main` for every successful build. No PR workflow, no protected branches — the operator is the only committer, the verifier is the gate.

```python
def commit_and_push(message):
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=True)
```

**Commit message convention:**

```
build: refresh <county>-intel <YYYY-MM-DD HH:MM> | leads=<N> | sources=<N>/<N> ok
```

Examples:
```
build: refresh <county_id>-intel 2026-05-05 18:32 | leads=79 | sources=4/5 ok
ops: BUILD_BROKEN.md - auto-rollback
build: methodology refresh
```

The `build:`, `ops:`, `feat:`, `fix:` prefixes match conventional commits and make `git log` greppable.

---

## Force-push (rollback only)

The framework only force-pushes when auto-rollback fires. The pattern:

```python
subprocess.run(["git", "revert", "--no-edit", "HEAD"], check=True)
subprocess.run(["git", "push", "origin", "main"], check=True)  # not force - revert is a forward commit
```

`git revert HEAD` creates a new commit that undoes the last one. This is preferred over `git reset --hard` + force-push because it preserves the broken commit in history for debugging.

---

## Windows Task Scheduler — daily refresh

The framework runs daily via Task Scheduler. The XML lives at `scripts/daily_refresh.xml`.

**Key fields:**

```xml
<Triggers>
  <CalendarTrigger>
    <StartBoundary>2026-05-05T06:00:00</StartBoundary>
    <ScheduleByDay>
      <DaysInterval>1</DaysInterval>
    </ScheduleByDay>
  </CalendarTrigger>
</Triggers>

<Actions>
  <Exec>
    <Command>C:\Users\Owner\AppData\Local\Programs\Python\Python312\python.exe</Command>
    <Arguments>pipeline\refresh.py --push</Arguments>
    <WorkingDirectory>C:\Dev\xcerebro-builds\projects\&lt;county&gt;-intel</WorkingDirectory>
  </Exec>
</Actions>

<Settings>
  <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
  <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
  <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
  <Priority>7</Priority>
</Settings>
```

**Critical:** the task must run with **stored credentials** (RunLevel="LeastPrivilege" with password stored), not "Run only when user is logged on." Otherwise, the task silently fails when the operator is logged out.

**Registration command:**

```powershell
schtasks /create /xml scripts\daily_refresh.xml /tn "<county>-intel-refresh" /ru <COMPUTERNAME>\<USER> /rp <password> /f
```

The autonomous build cannot acquire the password. The framework writes a setup script that prompts the operator once.

---

## Watchdog scheduled task

Independent of the daily refresh, a watchdog runs every 6 hours to verify the live URL is still healthy.

`scripts/watchdog.xml`:

```xml
<Triggers>
  <CalendarTrigger>
    <StartBoundary>2026-05-05T03:00:00</StartBoundary>
    <ScheduleByDay>
      <DaysInterval>1</DaysInterval>
    </ScheduleByDay>
    <Repetition>
      <Interval>PT6H</Interval>
      <Duration>P1D</Duration>
    </Repetition>
  </CalendarTrigger>
</Triggers>

<Actions>
  <Exec>
    <Command>C:\Users\Owner\AppData\Local\Programs\Python\Python312\python.exe</Command>
    <Arguments>pipeline\watchdog.py</Arguments>
    <WorkingDirectory>C:\Dev\xcerebro-builds\projects\&lt;county&gt;-intel</WorkingDirectory>
  </Exec>
</Actions>
```

Watchdog logic (in `pipeline/watchdog.py`):

```python
def run():
    # Run live-browser checks against the deployed URL
    ok = run_verification_checks_only()  # subset of verify.py — no CDN-flush wait
    if not ok:
        # Find last LIVE_VERIFIED commit and revert to it
        last_good = find_last_live_verified_commit()
        subprocess.run(["git", "reset", "--hard", last_good], check=True)
        subprocess.run(["git", "push", "--force-with-lease", "origin", "main"], check=True)
        telegram_send(f"<b>[{COUNTY}-intel]</b> Watchdog rolled back to {last_good[:7]}")
        sys.exit(1)
    sys.exit(0)
```

The watchdog is a safety net for cases where:
- A source change exercises a dashboard code path the build verifier didn't cover
- A GitHub Pages outage cleared
- Manual operator commit broke something

It catches drift between scheduled refreshes.

---

## Telegram alerts

The framework sends alerts to the operator's Telegram bot for:

- Source failure (any scraper exits non-zero)
- Run-over-run regression (>50% drop on any pattern)
- Heartbeat staleness (>36 hours without successful refresh)
- Session expiry (seeded session needs re-seeding)
- New high-stack leads (any lead with stack depth ≥ 3 appearing for first time)
- Auto-rollback fired (build verification failed)
- Watchdog rollback (continuous verification failed)
- Hallucination risk Critical (build halted)

**Implementation pattern:**

```python
import os
import requests

def telegram_send(text, parse_mode="HTML"):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(f"[telegram] alert (not sent — env missing): {text}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
    except Exception as e:
        print(f"[telegram] send failed: {e}")
```

Operator credentials live in `.env`:
```
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_CHAT_ID=<from getUpdates after bot creation>
```

(That chat_id is the operator's Telegram user ID. Use a group chat ID for team alerts.)

**Bot:** `@<your_telegram_bot>` is the operator's existing bot. Reuse it across all county builds; the chat_id distinguishes which county the alert is for via the `[<county>-intel]` prefix.

---

## Repository hygiene

**`.gitignore` essentials:**

```
.env
data/raw/
records_delivery/*.pdf
!records_delivery/_templates/
*.log
.venv/
__pycache__/
*.pyc
.DS_Store
Thumbs.db
LIVE_VERIFIED.txt   # see below — actually NOT gitignored
```

`LIVE_VERIFIED.txt` is committed. It serves as the watchdog's reference for the last known-good state.

**Branch protection:** off. The operator is sole committer. The verifier is the gate.

**Repo visibility:** start private. Make public only when methodology is mature and the operator wants to demonstrate the framework to clients.

---

## First-time setup checklist

When deploying a new county to production:

1. Create empty `<county>-intel` repo on GitHub (private)
2. Clone locally to `C:\Dev\xcerebro-builds\projects\<county>-intel`
3. Copy framework scaffold into the repo
4. Populate `config/counties/<county>.json` with source map
5. Run Phase 0–9 of the master prompt
6. Run `pipeline/refresh.py --push` once manually to verify end-to-end
7. Enable GitHub Pages (Settings → Pages → main branch, root)
8. Wait for first deploy to flush
9. Run `pipeline/verify.py` against live URL
10. If verify passes: `LIVE_VERIFIED.txt` is committed
11. Register daily refresh: `schtasks /create /xml scripts\daily_refresh.xml ...`
12. Register watchdog: `schtasks /create /xml scripts\watchdog.xml ...`
13. Smoke-test scheduled tasks: `schtasks /run /tn "<county>-intel-refresh"`
14. Add Telegram credentials to `.env` and confirm alerts work
15. Update operator's bookmark / client onboarding doc with live URL

After this checklist, the county is autonomous. Daily refreshes happen without operator intervention until a session expires or a source layout changes.
