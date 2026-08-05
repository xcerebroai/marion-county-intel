# marion-county-intel

Lead intelligence build for **Marion County, Indiana (Indianapolis)**, running on
the [Xcerebro Universal County Intelligence Framework](https://github.com/xcerebroai/xcerebro-county-intel)
**v5.6.0**.

    County:      Marion County, Indiana
    Slug:        marion_in
    Framework:   v5.6.0 (vendored into this repo)
    Phase:       Phase 0 complete — doc-type recon done, no scraper code yet
    Verdict:     READY_TO_BUILD

This repository is a **county build**, not the framework. The framework is
vendored in (`knowledge_base/`, `scaffold/`, `config/counties/_schema.json`,
`MASTER_PROMPT.md`) so the pipeline and its gate tests run here directly.

---

## Current state

Phase 0 doc-type recon is complete. **Read
[`recon/marion-in-recon.md`](recon/marion-in-recon.md) first** — it is the
authoritative source map for this build and every source verdict below comes
from it.

No scrapers, translators, dashboards, or databases have been built yet.

### The canonical join key

Every doc source in this build normalizes to the **Indiana state parcel
number**, with the local Marion parcel number stored alongside it as a
mandatory secondary:

    parcel_id_state    STATEPARCELNUMBER    49-06-25-178-053.000-101
    parcel_id_state_n  digits only          490625178053000101
    parcel_id_local    PARCEL_C             1042893

Both keys are required because different source families speak different keys,
and the MapIndy Parcel layer is the only place they appear together — it is the
crosswalk. Full contract, 1:1 proof, and the multi-polygon dedupe trap are in
§1 of the recon report. **Read that section before writing any adapter.**

### Source verdicts

    RANK  SOURCE                        ROLE          P    VERDICT
    1     MyCase — Indiana Courts       PRIMARY       P0   GREEN
    2     MapIndy Parcel layer          ENRICHMENT    P2   GREEN
    3     MapIndy Abandoned & Vacant    PRIMARY       P1   GREEN
    4     Accela code enforcement       PRIMARY       P0   YELLOW
    5     Indiana Gateway tax bills     ENRICHMENT    P2   YELLOW
    6     Sheriff sale list             SUPPORTING    P1   YELLOW
    7     Tax sale (GovEase/SRI)        PRIMARY       P1   YELLOW
    8     MapIndy Registered Landlord   ENRICHMENT    P2   GREEN
    9     Marion County Recorder        PRIMARY       P1   RED-ish
    10    Open-data code enforcement    BACKFILL ONLY      RED as live feed
    11    PACER bankruptcy              PRIMARY       —    RED (paid)

15 of 29 framework lead types are live and buildable now. 9 more are blocked
behind a single unresolved question on the recorder portal.

### Things that will bite you

- **Court records carry no address and no parcel id.** MyCase returns parties
  and case metadata only. The parcel join must be derived via an address
  bridge. This is the hardest problem in the build (recon §1.5).
- **Code enforcement carries no parcel id either** — address + owner only.
- **The parcel layer is not row-unique.** Multi-polygon parcels repeat up to
  30x. Dedupe on the canonical key or counts inflate.
- **The open-data code enforcement extract is frozen at 2024-02-27** despite a
  2025 "modified" stamp. Historical backfill only; use Accela for current data.
- **The prior `marion-in-intel` build never established a real parcel join** —
  it used SHA1 placeholder ids and fuzzy owner-name matching. Do not inherit
  that approach.

---

## Layout

    recon/marion-in-recon.md      Phase 0 doc-type recon — START HERE
    config/counties/marion_in.json  county config (recon stub, not yet
                                    schema-validated — see below)
    config/counties/_schema.json    framework county config schema
    runs/marion_in/                 run folder (LAUNCH file, operator notes)
    knowledge_base/                 framework contracts, protocols, domain docs
    scaffold/                       framework pipeline, translators, gate tests
    scrapers/                       (empty — Phase 1+)
    data/                           (empty — Phase 1+)
    dashboard/                      framework dashboard shell

---

## Verify the harness

    python scaffold/tests/run_all.py

37/37 gate tests pass as of 2026-08-04, including the four v5.6.0 recon
invariants.

---

## Next actions

1. **One headless-browser recon pass.** It unblocks nearly everything left:
   the Fidlar recorder search XHR and doc-type dropdown (governs 9 lead types),
   the indy.gov sheriff/tax sale list URLs, and the Indiana Gateway export.
   This also discharges the outstanding §01.22 sample-document requirement.
2. **Build the address → parcel crosswalk** from MapIndy layer 0 / the open
   data address datasets. Load-bearing for everything downstream.
3. **Ship an MVP** on MyCase + parcel layer + crosswalk — foreclosure (MF),
   eviction (EV), probate (EU/ES/EM), civil judgment (CC), tax deed (TP).
4. **Generate the full Phase 0 county config** via
   `scaffold/ops/write_county_config.py`, replacing the current stub.

Open operator decisions are listed in recon report §10.5.

---

## Config stub caveat

`config/counties/marion_in.json` is a **recon stub**, flagged
`RECON_STUB_NOT_SCHEMA_VALIDATED`. It records verified county identity, the
canonical key contract, and the source inventory. It does **not** yet carry the
full 18-field v5.0.0 proof packet per source, so it will not pass
`config/counties/_schema.json` validation. Producing the validated config is a
Phase 0 Step 4 task and must go through `write_county_config.py`, never a
hand-written file.

---

Copyright © 2026 Xcerebro LLC. Proprietary VIP license — see `LICENSE.md`.
