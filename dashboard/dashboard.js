/**
 * Distress Intelligence — static dashboard runtime.
 *
 * The dashboard reads a flat JSON payload (data/leads.json in production
 * or data/leads_synthetic.json in synthetic mode) and renders:
 *
 *   - stat tiles for total leads and per-tier counts,
 *   - a chip-based filter rail (tier / pattern / attribute / deal_path /
 *     stack_depth) with the Two-Truths invariant (chip count =
 *     post-filter table row count),
 *   - a sortable, filterable lead table,
 *   - a CSV export of the currently-filtered set.
 *
 * The runtime sets body[data-ready="1"] once the initial render
 * completes so headless browsers (Phase 6 live-verification harness)
 * can wait on that selector.
 */

(() => {
  "use strict";

  // -------------------------------------------------------------------
  // Data loading
  // -------------------------------------------------------------------

  const DATA_PATHS_PROD = ["./data/leads.json", "../data/leads.json"];
  const DATA_PATHS_SYNTH = [
    "./data/leads_synthetic.json",
    "../data/leads_synthetic.json",
  ];

  async function fetchFirst(paths) {
    const errors = [];
    for (const path of paths) {
      try {
        const r = await fetch(path);
        if (r.ok) return [path, await r.json()];
        errors.push(`${path}: HTTP ${r.status}`);
      } catch (e) {
        errors.push(`${path}: ${e.message}`);
      }
    }
    throw new Error(
      "Could not load dashboard payload from any candidate path: " +
        errors.join(" / ")
    );
  }

  // -------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------

  const state = {
    payload: null,
    filters: {
      tier: new Set(),
      pattern: new Set(),
      attribute: new Set(),
      deal_path: new Set(),
      stack_depth: new Set(),
    },
    sort: { key: "display_score", dir: -1 },
    mode: "client", // "client" or "operator"
    precannedView: null,
  };

  const PRECANNED_VIEWS = [
    {
      id: "high_value",
      label: "High value (Hot + Strong)",
      filter: (row) => ["Hot", "Strong"].includes(row.display_tier),
    },
    {
      id: "foreclosure_estate_heir_candidate",
      label: "Foreclosure + estate owner (heir candidate)",
      filter: (row) =>
        row.display_patterns.includes("foreclosure") &&
        row.display_patterns.includes("estate"),
    },
    {
      id: "foreclosure_trust",
      label: "Foreclosure + trust owner",
      filter: (row) =>
        row.display_patterns.includes("foreclosure") &&
        (row.stack_contrib_patterns || []).filter((p) => p === "transfer").length > 0 &&
        // Only count transfer patterns that came from owner-name (not just any transfer)
        (row.display_pattern_set || []).includes("transfer"),
    },
    {
      id: "vacant_with_distress",
      label: "Vacant with distress",
      filter: (row) =>
        row.display_attributes.includes("vacant") &&
        row.display_patterns.some((p) =>
          ["foreclosure", "code", "tax", "lien"].includes(p)
        ),
    },
    {
      id: "estate_partial_interest",
      label: "Estate / partial interest",
      filter: (row) =>
        row.display_deal_paths.includes("partial_interest") ||
        row.display_patterns.includes("estate"),
    },
    {
      id: "needs_review",
      label: "Needs review",
      filter: (row) => row.display_lead_status === "REVIEW_REQUIRED",
    },
  ];

  // -------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------

  function render() {
    if (!state.payload) return;
    const countyName = state.payload.county || "";
    document.getElementById("brand-title").textContent =
      countyName
        ? `${countyName} County Distress Intelligence`
        : "Distress Intelligence";
    document.title = countyName
      ? `${countyName} County Distress Intelligence`
      : "Distress Intelligence";
    const deployment = state.payload.deployment || {};
    const repoOrg = deployment.github_org;
    const repoName = deployment.github_repo;
    const repoLink = document.getElementById("repo-link");
    if (repoLink && repoOrg && repoName) {
      repoLink.href = `https://github.com/${repoOrg}/${repoName}`;
      repoLink.hidden = false;
    }
    document.getElementById("build-label").textContent =
      state.payload.build_label || "FULL_BUILD";
    document.getElementById("generated-at").textContent =
      "Generated " + state.payload.generated_at;
    document.getElementById("view-mode-pill").textContent =
      state.mode === "operator" ? "OPERATOR_VIEW" : "CLIENT_VIEW";
    document.body.setAttribute("data-mode", state.mode);

    // Status banner — surfaces build_label_reason for source-limited
    // / partial / pending builds. Hidden for clean FULL_BUILD runs.
    const banner = document.getElementById("status-banner");
    const reason = state.payload.build_label_reason;
    const limitedLabels = new Set([
      "SOURCE_LIMITED",
      "PARTIAL_BUILD",
      "PRIMARY_SOURCE_PENDING",
    ]);
    if (reason && limitedLabels.has(state.payload.build_label)) {
      banner.hidden = false;
      banner.textContent = `${state.payload.build_label}: ${reason}`;
    } else {
      banner.hidden = true;
    }

    const filteredRows = applyFilters(state.payload.records);
    renderTiles(filteredRows);
    renderChips();
    renderPrecanned();
    renderTable(filteredRows);
    renderFooter(filteredRows);
    document.body.setAttribute("data-ready", "1");
  }

  function applyFilters(rows) {
    let out = rows;
    if (state.filters.tier.size)
      out = out.filter((r) => state.filters.tier.has(r.display_tier));
    if (state.filters.pattern.size)
      out = out.filter((r) =>
        r.display_patterns.some((p) => state.filters.pattern.has(p))
      );
    if (state.filters.attribute.size)
      out = out.filter((r) =>
        r.display_attributes.some((a) => state.filters.attribute.has(a))
      );
    if (state.filters.deal_path.size)
      out = out.filter((r) =>
        r.display_deal_paths.some((d) => state.filters.deal_path.has(d))
      );
    if (state.filters.stack_depth.size)
      out = out.filter((r) =>
        state.filters.stack_depth.has(String(r.stack_depth))
      );

    if (state.precannedView) {
      const pv = PRECANNED_VIEWS.find((v) => v.id === state.precannedView);
      if (pv) out = out.filter(pv.filter);
    }

    if (state.mode === "client") {
      out = out.filter(
        (r) => r.display_lead_status !== "REVIEW_REQUIRED"
      );
    }

    return [...out].sort((a, b) => {
      const av = a[state.sort.key];
      const bv = b[state.sort.key];
      if (av === bv) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av < bv ? -1 : 1) * state.sort.dir;
    });
  }

  function renderTiles(filteredRows) {
    const total = filteredRows.length;
    const byTier = { Hot: 0, Strong: 0, Workable: 0, Low: 0, Archive: 0 };
    for (const r of filteredRows) byTier[r.display_tier] = (byTier[r.display_tier] || 0) + 1;
    const tiles = [
      { label: "Total filtered", value: total, tier: "" },
      ...Object.entries(byTier).map(([tier, value]) => ({ label: tier, value, tier })),
    ];
    document.getElementById("stat-tiles").innerHTML = tiles
      .map(
        (t) => `
        <div class="tile" data-tier="${t.tier}">
          <span class="tile-label">${t.label}</span>
          <span class="tile-value" data-testid="tile-${t.tier || "total"}">${t.value}</span>
        </div>`
      )
      .join("");
  }

  function chipHtml(value, count, pressed) {
    return `<button class="chip" type="button" aria-pressed="${pressed}"
      data-value="${escapeAttr(value)}">${escapeHtml(value)} <span class="chip-count">${count}</span></button>`;
  }

  function renderChips() {
    const records = state.payload.records;

    const axes = [
      {
        elId: "chips-tier",
        axis: "tier",
        keys: Object.keys(state.payload.score_tier_distribution || {}),
        countFn: (k) => state.payload.score_tier_distribution[k] || 0,
      },
      {
        elId: "chips-pattern",
        axis: "pattern",
        keys: Object.keys(state.payload.pattern_counts || {}),
        countFn: (k) => state.payload.pattern_counts[k] || 0,
      },
      {
        elId: "chips-attribute",
        axis: "attribute",
        keys: Object.keys(state.payload.attribute_counts || {}),
        countFn: (k) => state.payload.attribute_counts[k] || 0,
      },
      {
        elId: "chips-deal-path",
        axis: "deal_path",
        keys: Object.keys(state.payload.deal_path_distribution || {}),
        countFn: (k) => state.payload.deal_path_distribution[k] || 0,
      },
      {
        elId: "chips-stack-depth",
        axis: "stack_depth",
        keys: Object.keys(state.payload.stack_depth_distribution || {}).sort(),
        countFn: (k) => state.payload.stack_depth_distribution[k] || 0,
      },
    ];

    for (const ax of axes) {
      const el = document.getElementById(ax.elId);
      el.innerHTML = ax.keys
        .map((k) =>
          chipHtml(k, ax.countFn(k), state.filters[ax.axis].has(k))
        )
        .join("");
    }

    document.querySelectorAll(".chip-group").forEach((g) => {
      g.querySelectorAll(".chip").forEach((chip) => {
        chip.addEventListener("click", () => {
          const axis = g.dataset.axis;
          const value = chip.dataset.value;
          const set = state.filters[axis];
          if (set.has(value)) set.delete(value);
          else set.add(value);
          render();
        });
      });
    });
  }

  function renderPrecanned() {
    const el = document.getElementById("precanned-views");
    el.innerHTML = PRECANNED_VIEWS.map(
      (v) => `<button class="pv-btn" type="button" aria-pressed="${state.precannedView === v.id}"
        data-pv="${escapeAttr(v.id)}">${escapeHtml(v.label)}</button>`
    ).join("");
    el.querySelectorAll(".pv-btn").forEach((b) => {
      b.addEventListener("click", () => {
        state.precannedView = state.precannedView === b.dataset.pv ? null : b.dataset.pv;
        render();
      });
    });
  }

  function renderTable(rows) {
    const tbody = document.getElementById("leads-tbody");
    if (!rows.length) {
      tbody.innerHTML = "";
      document.getElementById("empty-state").hidden = false;
      return;
    }
    document.getElementById("empty-state").hidden = true;

    tbody.innerHTML = rows
      .map((r) => {
        const reviewCls =
          r.display_lead_status === "REVIEW_REQUIRED" ? "review-required" : "";
        const pendingBadge =
          r.parcel_master_status === "placeholder_pending_enrichment"
            ? `<span class="cell-tag pending-badge" title="${escapeAttr(r.parcel_master_status_note || "")}">pending parcel match</span>`
            : "";
        // Heir-candidate badge: foreclosure pattern + estate pattern
        // (from owner-name-pattern or court probate) on the same lead.
        // Operator's high-value combo per REVIEW_GATE_4 follow-up.
        const heirBadge =
          r.display_patterns.includes("foreclosure") &&
          r.display_patterns.includes("estate")
            ? `<span class="cell-tag heir-badge" title="Foreclosure + estate signal — heir-hunting opportunity">★ heir candidate</span>`
            : "";
        const trustBadge =
          r.display_patterns.includes("foreclosure") &&
          (r.display_pattern_set || []).includes("transfer")
            ? `<span class="cell-tag trust-badge" title="Foreclosure + transfer signal (likely living-trust owner)">trust owner</span>`
            : "";
        const flagsCell = (r.review_flags || []).length
          ? `<div class="cell-tags">${r.review_flags
              .map((f) => `<span class="cell-tag flag-tag">${escapeHtml(f)}</span>`)
              .join("")}</div>`
          : "—";
        return `<tr class="${reviewCls}" data-lead-id="${escapeAttr(r.lead_id)}" data-testid="lead-row">
          <td>${r.display_score}</td>
          <td><span class="tier-badge" data-tier="${escapeAttr(r.display_tier)}">${escapeHtml(r.display_tier)}</span></td>
          <td>${escapeHtml(r.primary_parcel_id || "")}${pendingBadge ? " " + pendingBadge : ""}</td>
          <td>${escapeHtml(r.display_address || "")}${heirBadge ? " " + heirBadge : ""}${trustBadge ? " " + trustBadge : ""}</td>
          <td>${escapeHtml(r.display_owner || "")}</td>
          <td><div class="cell-tags">${(r.display_patterns || []).map((p) => `<span class="cell-tag">${escapeHtml(p)}</span>`).join("")}</div></td>
          <td><div class="cell-tags">${(r.display_attributes || []).map((a) => `<span class="cell-tag">${escapeHtml(a)}</span>`).join("")}</div></td>
          <td><div class="cell-tags">${(r.display_deal_paths || []).map((d) => `<span class="cell-tag">${escapeHtml(d)}</span>`).join("")}</div></td>
          <td>${r.stack_depth}</td>
          <td>${fmtMoney(r.display_assessed_value)}</td>
          <td>${fmtMoney(r.display_last_sale_price)}</td>
          <td>${escapeHtml(r.expected_sale_date || r.primary_event_date || "")}</td>
          <td>${flagsCell}</td>
          <td>${(r.primary_source_urls || []).map((u) => `<a href="${escapeAttr(u)}" target="_blank" rel="noopener">link</a>`).join(" ") || "—"}</td>
        </tr>`;
      })
      .join("");
  }

  function renderFooter(rows) {
    const total = state.payload.records.length;
    const showing = rows.length;
    document.getElementById("footer-counts").textContent =
      `${showing} of ${total} leads (${state.payload.mode} mode, ${state.payload.county}/${state.payload.state})`;
  }

  // -------------------------------------------------------------------
  // CSV export
  // -------------------------------------------------------------------

  const CSV_COLUMNS = [
    "lead_id",
    "primary_parcel_id",
    "display_address",
    "display_owner",
    "display_score",
    "display_tier",
    "display_patterns",
    "stack_contrib_patterns",
    "display_pattern_set",
    "display_attributes",
    "display_deal_paths",
    "display_deal_path_details",
    "display_title_complexity_tier",
    "display_lead_status",
    "display_assessed_value",
    "display_last_sale_price",
    "display_last_sale_date",
    "display_year_built",
    "display_match_confidence",
    "stack_depth",
    "primary_event_date",
    "score_reasons",
    "evidence_ids",
    "primary_source_urls",
    "mode",
    "county",
    "state",
    "build_label",
    "generated_at",
    "review_flag_count",
    "first_pattern",
    "first_deal_path",
  ];

  function csvEscape(v) {
    if (v == null) return "";
    if (Array.isArray(v) || typeof v === "object") v = JSON.stringify(v);
    const s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  function exportCsv() {
    const rows = applyFilters(state.payload.records);
    const header = CSV_COLUMNS.join(",");
    const lines = rows.map((r) =>
      CSV_COLUMNS.map((col) => {
        switch (col) {
          case "mode":
          case "county":
          case "state":
          case "build_label":
          case "generated_at":
            return csvEscape(state.payload[col]);
          case "review_flag_count":
            return r.display_lead_status === "REVIEW_REQUIRED" ? 1 : 0;
          case "first_pattern":
            return csvEscape((r.display_patterns || [])[0] || "");
          case "first_deal_path":
            return csvEscape((r.display_deal_paths || [])[0] || "");
          default:
            return csvEscape(r[col]);
        }
      }).join(",")
    );
    const blob = new Blob([header + "\n" + lines.join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `leads_${state.payload.county || "export"}_${(new Date()).toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 100);
    return { rows: rows.length, columns: CSV_COLUMNS.length };
  }

  // -------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
  function escapeAttr(s) { return escapeHtml(s); }

  function fmtMoney(n) {
    if (n == null || n === "" || isNaN(Number(n))) return "Unknown";
    return "$" + Math.round(Number(n)).toLocaleString("en-US");
  }

  // -------------------------------------------------------------------
  // Wiring
  // -------------------------------------------------------------------

  function wireEvents() {
    document.getElementById("reset-filters").addEventListener("click", () => {
      Object.values(state.filters).forEach((s) => s.clear());
      state.precannedView = null;
      render();
    });
    document.getElementById("toggle-view-mode").addEventListener("click", (e) => {
      state.mode = state.mode === "client" ? "operator" : "client";
      e.currentTarget.textContent =
        state.mode === "client"
          ? "Switch to Operator View"
          : "Switch to Client View";
      render();
    });
    document.getElementById("csv-export").addEventListener("click", exportCsv);
    document.querySelectorAll(".leads-table thead th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (state.sort.key === key) state.sort.dir = -state.sort.dir;
        else { state.sort.key = key; state.sort.dir = -1; }
        render();
      });
    });
  }

  async function boot() {
    wireEvents();
    const isSynthetic = new URL(window.location.href).searchParams.get("synthetic") !== "0";
    const paths = isSynthetic
      ? DATA_PATHS_SYNTH.concat(DATA_PATHS_PROD)
      : DATA_PATHS_PROD.concat(DATA_PATHS_SYNTH);
    try {
      const [path, payload] = await fetchFirst(paths);
      state.payload = payload;
      console.info(`Loaded dashboard payload from ${path}`);
      render();
    } catch (err) {
      console.error(err);
      document.getElementById("status-banner").hidden = false;
      document.getElementById("status-banner").textContent =
        "Could not load dashboard payload — start an HTTP server in the repo root and reload.";
      document.body.setAttribute("data-ready", "1");
    }
  }

  // Expose for Playwright / headless verification.
  window.__bexarDashboard = {
    getState: () => state,
    applyFilters,
    exportCsv,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
