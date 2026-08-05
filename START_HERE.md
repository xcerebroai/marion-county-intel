# START HERE

**First time using the Xcerebro County Intelligence Framework? Read this. Three minutes.**

You're holding a private repository that contains the framework for building a county lead intelligence harness. It does not produce leads itself — it tells Claude Code how to build one for any county you target.

This document is the only thing you should read before your first run.

---

## What you need

- **Claude Code** installed and authenticated (`claude --version` should print a version)
- **Python 3.12+** installed (`python --version`)
- A **private GitHub repo** for the county you're targeting, where the framework will live

That's it. No virtualenv to set up by hand. No JSON to edit. No PowerShell scripts to write.

---

## The one-sentence install

After you've cloned the framework into the county repo and you're sitting in that repo directory in your terminal:

```
claude
```

That launches Claude Code. When Claude Code's prompt appears, type one sentence:

```
Build Bexar County, Texas.
```

Substitute your actual county and state. Claude Code will:

1. Read `MASTER_PROMPT.md` (the framework contract)
2. Parse your county name and state into a slug like `bexar_tx`
3. Show you the interpreted target before doing anything:
   ```
   Target: Bexar County, Texas
   Slug: bexar_tx
   Phase: phase0
   ```
4. Ask your approval to run the bootstrap script (one approval click)
5. Run `scaffold/bootstrap_county.py` to create `runs/<slug>/` and the launch instructions
6. Read the generated launch file
7. Run Phase 0 only (County Source Recon and Onboarding Gate)
8. Stop with a change manifest

You confirm the slug. You approve the bootstrap. Then you watch.

### How "autonomous" is autonomous (v5.1.1-beta)

The first run is autonomous in the sense that:

- You only ever type ONE sentence — your county build instruction.
- You only ever approve ONE shell command — the bootstrap script.
- Everything else (recon, source verification, blocker auto-resolve, config writing, change manifest) runs hands-off.

That said, Claude Code is still operating under a permission model that asks before running shell commands and before fetching web content. During Phase 0 you may see permission prompts for:

- **Web search** — needed for source recon. Safe to approve broadly within the county repo directory.
- **Web fetch** for official county / state / vendor portal URLs — needed for source verification. Safe to approve broadly for any `.gov`, `.org`, or recognized vendor portal domain.

You may also see Claude Code stop and report an error in two specific cases (both v5.1.1-beta+ design):

- **`CONFIG_WRITE_FAILED`** — Claude Code attempted to write the populated county config but validation failed twice. The framework will not silently proceed past a config-write failure. Open the resulting `runs/<slug>/CONFIG_WRITE_FAILED.md` for diagnosis.
- **`SCHEMA_VALIDATION_SKIPPED`** in the writer output — `jsonschema` is not installed in your local Python environment. This is not an error; the config was still written and JSON syntax validation still passed. If you want strict schema validation, run `pip install jsonschema` once. The framework does not auto-install dependencies.

Phase 0 stops at a Build Mode Approval Gate. Claude Code will NOT enter Build Mode (scrapers, dashboards, deployment) without an explicit operator instruction to proceed.

---

## If Claude Code gets the slug wrong

Say so before approving the bootstrap. Example:

> The slug should be `bexar_county_tx` instead of `bexar_tx`.

Claude Code will regenerate the bootstrap with the corrected slug. The framework doesn't ship with hardcoded slug formats — `<county>_<state>` is the default, but you can override it.

---

## If the county name is ambiguous

Some county names exist in multiple states. *Washington County, [pick a state]* exists in 30 states. *Orange County* exists in 8 states. *Greene County* exists in 14 states.

If Claude Code can't determine the state from your sentence, it will ask. Always include the state in your first sentence to avoid this:

✅ `Build Washington County, Pennsylvania.`
❌ `Build Washington County.`

---

## What Phase 0 actually does

Phase 0 is the **County Source Recon and Onboarding Gate**. It does NOT build scrapers. It does NOT build a dashboard. It does NOT touch GitHub Pages or Supabase.

It does:

1. Walk the framework's exhaustive source-category checklist
2. For each category, search the official county / state / municipal / court website
3. Verify each URL is reachable
4. Classify each source: `OFFICIAL`, `UNVERIFIED`, or `NOT_FOUND`
5. Tag priority (P0 daily distress / P1 weekly distress / P2 enrichment)
6. Save the result as `config/counties/<slug>.json`
7. Validate the config against `config/counties/_schema.json`
8. Confirm the P0 gate is satisfied (at least one daily-refresh distress source unblocked)
9. Print a change manifest

When Phase 0 completes, you have a verified source map AND a build verdict. The build verdict tells you whether the county is `READY_TO_BUILD`, `READY_WITH_BLOCKERS`, `RECON_ONLY`, `WAITING_ON_ACCESS`, or `NOT_BUILDABLE_YET`. **Phase 0 is the foundation. Get it right.**

In v5.0.0, every source goes through a five-layer verification gate before being trusted: Official Origin → Source Category → Data Access → Lead Value / Source Role → Portal Proof. This is automatic — Claude Code applies it during Phase 0. You'll see the results in the source proof packet inside `config/counties/<slug>.json`.

---

## What Phase 0 will NOT do automatically

Phase 0 does NOT proceed to Phase 1 (Build Mode) without your explicit go-ahead. Phase 0 stops at the Build Eligibility Gate.

When Phase 0 completes, Claude Code prints a VIP-friendly verdict message AND the change manifest, then waits. You review the verdict. If `build_verdict == "READY_TO_BUILD"`, you tell Claude Code to proceed to Phase 1. If the verdict is anything else, you decide whether to fix the blockers, override, or kill the build.

This is by design. Phase 0 is the gate that protects everything downstream.

---

## The product rule

**This framework is an OFFICIAL EVENT SOURCE-DRIVEN lead intelligence system.**

Leads come from event-based and distress-based sources:

- Clerk records, recorder records
- Court events (foreclosure, probate, civil judgments, evictions)
- Tax distress, foreclosure events, sheriff sale events
- Probate records, liens, judgments, lis pendens
- Recorded notices and other official recorded distress events

Parcel data, GIS data, CAD data, assessor data, owner data, tax roll data, and bulk property records are **ENRICHMENT ONLY**. They are never the headline. They never get treated as leads.

If no verified primary event source exists (clerk, recorder, court portal, district clerk, sheriff, tax office, tax collector, trustee sale portal, foreclosure listing portal, tax lien foreclosure listing, auction vendor, official vendor portal, or posted notices page), Phase 0 stops. Clerk and recorder are the most common primary sources but not the only valid ones. **It will not silently fill the dashboard with parcel data to fake productivity.** A blocked primary event source means a blocked build — not a parcel viewer dressed up as a lead system.

---

## If something goes wrong

**Claude Code asks for approval to run something other than `scaffold/bootstrap_county.py`:** Deny it. The autonomous first-run grant is bounded to that one script. Anything else needs your explicit approval. If it asks to run a different script during Phase 0 (like installing dependencies), approve only if you understand what it's doing.

**Phase 0 reports "P0 GATE FAIL":** The county has no working daily-refresh distress source. Read the manifest. Decide whether to escalate (find an unblock path) or kill the build and pick a different county. Do not let Claude Code proceed past Phase 0 with a failed gate.

**Phase 0 marks every source NOT_FOUND:** Either the county genuinely doesn't publish records online (rare in the US) or Claude Code couldn't find them (more likely). Manually navigate to the county's website and check before accepting the recon result.

**Claude Code starts building a scraper / dashboard / Supabase table on first run:** Stop it. Paste this:
> Stop. You are outside scope. Phase 0 only. Do not build scrapers, dashboards, or databases yet.

---

## Next steps

After Phase 0 ships clean:

- Read `MIGRATION.md` for the full phase-by-phase build sequence
- Read `MASTER_PROMPT.md` for the framework contract
- Read `README.md` for the project overview

These three documents are the canonical guide. `START_HERE.md` is only for the first run.

---

**You are licensed under the Xcerebro LLC proprietary VIP license. See `LICENSE.md`.**

Welcome to the framework.
