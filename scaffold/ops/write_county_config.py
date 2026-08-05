"""
Atomic county config writer for the Xcerebro County Intelligence Harness.

Introduced in: v5.1.1-beta (Execution Reliability Patch).
Reason for existence:
    Phase 0 Step 4 in v5.1.0-beta sometimes failed when Claude Code (or any
    other LLM-driven file writer) text-streamed a large nested JSON object
    directly to disk. Long files produced duplicated keys, truncated objects,
    or otherwise structurally invalid JSON that schema validation could not
    repair.

    This module exists so Claude Code (and any operator script) has ONE
    canonical, side-effect-safe way to write a populated county config:

        write_county_config(config_dict, target_path, schema_path=...)

    The function:

      1. Accepts a Python dict (which by construction cannot contain
         duplicate keys at any nesting level).
      2. Writes via json.dump to a temp file next to the final path.
      3. Validates JSON syntax by re-reading the temp file.
      4. Optionally validates against a JSON Schema if jsonschema is
         installed locally. If jsonschema is not installed, validation
         is SKIPPED, not failed. The framework will never auto-install
         packages on the operator's machine.
      5. Atomically moves the temp file into the final config path.
      6. Returns a structured WriteResult describing what happened.

    If validation fails at any step, the temp file is left in place for
    operator inspection, the final config path is NOT touched, and the
    caller may attempt EXACTLY ONE structured repair (re-build the dict
    and call write_county_config again). A second failure must produce
    `CONFIG_WRITE_FAILED` and stop the run.

Locked rules (v5.1.1-beta):
    - Never use a streaming/text-rendering write path for a county config.
    - Never use Claude Code's `Write` tool to emit a populated county
      config larger than 100 lines. Always go through this module.
    - Never auto-install jsonschema or any other dependency. If it isn't
      available locally, log `SCHEMA_VALIDATION_SKIPPED` and continue.
    - Never silently overwrite an existing config. The caller passes
      `overwrite=True` explicitly when intent is to replace.

Usage:

    from scaffold.ops.write_county_config import write_county_config

    result = write_county_config(
        config_dict=my_built_dict,
        target_path="config/counties/bexar_tx.json",
        schema_path="config/counties/_schema.json",
        overwrite=False,
    )
    print(result.summary())
    if result.status != "OK":
        # Caller may attempt ONE structured repair, then must stop.
        raise SystemExit(1)

Returns a `WriteResult` object with:
    status:                "OK" | "JSON_INVALID" | "SCHEMA_INVALID"
                           | "PATH_EXISTS_NO_OVERWRITE" | "IO_ERROR"
    schema_validation:     "VALIDATED" | "SCHEMA_VALIDATION_SKIPPED"
                           | "SCHEMA_INVALID" | "SCHEMA_FILE_MISSING"
    final_path:            absolute path of the written config (or "")
    temp_path:             absolute path of the temp file (kept on failure)
    bytes_written:         file size of the written config (or 0)
    top_level_key_count:   number of top-level keys in the dict
    source_names:          list of source IDs declared in `sources`
    build_verdict:         value of `build_verdict` if present
    operator_override_count: length of `operator_override_audit` if present
    errors:                list of error strings
    notes:                 list of informational notes (e.g. why a step
                           was skipped)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


__all__ = ["WriteResult", "write_county_config"]


# ---------- Result object ----------

@dataclass
class WriteResult:
    """Structured outcome of a county config write attempt."""

    status: str = "OK"
    schema_validation: str = "SCHEMA_VALIDATION_SKIPPED"
    final_path: str = ""
    temp_path: str = ""
    bytes_written: int = 0
    top_level_key_count: int = 0
    source_names: list = field(default_factory=list)
    build_verdict: str = ""
    operator_override_count: int = 0
    errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def is_ok(self) -> bool:
        return self.status == "OK"

    def summary(self) -> str:
        """Human-readable single-block summary for terminal printing."""
        lines = [
            "==== write_county_config result ====",
            f"status:                  {self.status}",
            f"schema_validation:       {self.schema_validation}",
            f"final_path:              {self.final_path}",
            f"temp_path:               {self.temp_path}",
            f"bytes_written:           {self.bytes_written}",
            f"top_level_key_count:     {self.top_level_key_count}",
            f"source_names:            {self.source_names}",
            f"build_verdict:           {self.build_verdict}",
            f"operator_override_count: {self.operator_override_count}",
        ]
        if self.errors:
            lines.append("errors:")
            for e in self.errors:
                lines.append(f"  - {e}")
        if self.notes:
            lines.append("notes:")
            for n in self.notes:
                lines.append(f"  - {n}")
        lines.append("====================================")
        return "\n".join(lines)


# ---------- Public API ----------

def write_county_config(
    config_dict: dict,
    target_path: str,
    schema_path: str | None = None,
    overwrite: bool = False,
) -> WriteResult:
    """
    Atomically write a county config dict to disk with optional schema
    validation. Returns a structured WriteResult; never raises on
    validation errors (only on programmer errors like a non-dict input).

    The required flow is:

        build dict in memory  (caller responsibility — duplicate keys
                                are structurally impossible here)
        -> write to temp file via json.dump
        -> re-read temp file and json.loads to confirm syntax
        -> optionally schema-validate if jsonschema is installed
        -> shutil.move temp file to final path

    Args:
        config_dict: the populated county config as a Python dict
        target_path: final destination path
                     (typically `config/counties/<slug>.json`)
        schema_path: optional path to `config/counties/_schema.json`
                     for schema validation. If None or missing, schema
                     validation is skipped (NOT failed).
        overwrite:   if False and `target_path` already exists, refuse
                     and return PATH_EXISTS_NO_OVERWRITE. If True,
                     replace atomically.

    Returns:
        WriteResult
    """
    result = WriteResult()

    # ---- Input guard ----
    if not isinstance(config_dict, dict):
        result.status = "IO_ERROR"
        result.errors.append(
            "config_dict must be a dict; got "
            f"{type(config_dict).__name__}"
        )
        return result

    target = Path(target_path).resolve()
    result.final_path = str(target)

    # ---- Overwrite guard ----
    if target.exists() and not overwrite:
        result.status = "PATH_EXISTS_NO_OVERWRITE"
        result.errors.append(
            f"Target path already exists and overwrite=False: {target}"
        )
        return result

    # ---- Pre-fill descriptive fields from the dict ----
    result.top_level_key_count = len(config_dict)
    sources = config_dict.get("sources")
    if isinstance(sources, dict):
        result.source_names = list(sources.keys())
    result.build_verdict = str(config_dict.get("build_verdict", "") or "")
    override_audit = config_dict.get("operator_override_audit", [])
    if isinstance(override_audit, list):
        result.operator_override_count = len(override_audit)

    # ---- Ensure parent directory exists ----
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.status = "IO_ERROR"
        result.errors.append(
            f"Could not create parent directory {target.parent}: {exc}"
        )
        return result

    # ---- Write to temp file ----
    try:
        # Use NamedTemporaryFile in the SAME directory so the final
        # move is atomic on the same filesystem.
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=f"{target.stem}.",
            suffix=".tmp.json",
            delete=False,
        )
        with tmp:
            json.dump(
                config_dict,
                tmp,
                indent=2,
                ensure_ascii=False,
                sort_keys=False,
            )
            tmp.flush()
            os.fsync(tmp.fileno())
        result.temp_path = tmp.name
    except (OSError, TypeError, ValueError) as exc:
        result.status = "IO_ERROR"
        result.errors.append(
            f"Failed to write temp file: {exc}"
        )
        return result

    # ---- Validate JSON syntax by re-reading the temp file ----
    try:
        with open(result.temp_path, "r", encoding="utf-8") as fh:
            reloaded = json.load(fh)
        # Sanity: dict round-trip preserves structure
        if not isinstance(reloaded, dict):
            result.status = "JSON_INVALID"
            result.errors.append(
                "Temp file did not round-trip as a JSON object"
            )
            return result
    except json.JSONDecodeError as exc:
        result.status = "JSON_INVALID"
        result.errors.append(f"Temp file is not valid JSON: {exc}")
        return result
    except OSError as exc:
        result.status = "IO_ERROR"
        result.errors.append(f"Could not re-read temp file: {exc}")
        return result

    result.bytes_written = os.path.getsize(result.temp_path)

    # ---- Optional schema validation (graceful skip) ----
    if schema_path:
        schema = Path(schema_path)
        if not schema.exists():
            result.schema_validation = "SCHEMA_FILE_MISSING"
            result.notes.append(
                f"Schema file not found at {schema}; skipping schema "
                "validation. JSON syntax is still valid."
            )
        else:
            try:
                import jsonschema  # type: ignore
            except ImportError:
                result.schema_validation = "SCHEMA_VALIDATION_SKIPPED"
                result.notes.append(
                    "jsonschema not installed in local environment; "
                    "skipping schema validation. JSON syntax is still "
                    "valid. The framework never auto-installs packages."
                )
            else:
                try:
                    with open(schema, "r", encoding="utf-8") as fh:
                        schema_doc = json.load(fh)
                    jsonschema.validate(reloaded, schema_doc)
                    result.schema_validation = "VALIDATED"
                except jsonschema.ValidationError as exc:
                    result.status = "SCHEMA_INVALID"
                    result.schema_validation = "SCHEMA_INVALID"
                    # Keep the message concise so it lands in terminal
                    # output without overwhelming the operator.
                    message = (
                        f"Schema validation failed at "
                        f"{list(exc.absolute_path)}: {exc.message}"
                    )
                    result.errors.append(message)
                    return result
                except json.JSONDecodeError as exc:
                    result.status = "IO_ERROR"
                    result.errors.append(
                        f"Could not parse schema file: {exc}"
                    )
                    return result
                except OSError as exc:
                    result.status = "IO_ERROR"
                    result.errors.append(
                        f"Could not read schema file: {exc}"
                    )
                    return result
    else:
        result.schema_validation = "SCHEMA_VALIDATION_SKIPPED"
        result.notes.append(
            "No schema_path provided; skipping schema validation."
        )

    # ---- Atomic move into final path ----
    try:
        # shutil.move handles same-filesystem rename atomically;
        # cross-filesystem it falls back to copy+delete which is fine.
        shutil.move(result.temp_path, str(target))
    except OSError as exc:
        result.status = "IO_ERROR"
        result.errors.append(
            f"Could not move temp file into final path: {exc}"
        )
        return result

    # Update temp_path to reflect that it has been consumed.
    result.temp_path = ""
    result.bytes_written = os.path.getsize(target)
    return result


# ---------- CLI entry point ----------

def _cli() -> int:
    """
    Tiny CLI wrapper to dry-run the writer against a JSON file of a dict
    payload. Mostly useful for sanity-checking the module from a shell.
    Not intended as the normal call path — Claude Code should import
    write_county_config and call it with a built dict directly.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Atomic county config writer (v5.1.1-beta)."
    )
    parser.add_argument(
        "--input-json",
        required=True,
        help="Path to a JSON file containing the populated county config dict.",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Final destination path "
             "(typically config/counties/<slug>.json).",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="Optional path to config/counties/_schema.json.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting an existing target file.",
    )
    args = parser.parse_args()

    try:
        with open(args.input_json, "r", encoding="utf-8") as fh:
            config_dict = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not read input JSON: {exc}", file=sys.stderr)
        return 2

    result = write_county_config(
        config_dict=config_dict,
        target_path=args.target,
        schema_path=args.schema,
        overwrite=args.overwrite,
    )
    print(result.summary())
    return 0 if result.is_ok() else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
