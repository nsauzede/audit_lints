#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 — Nicolas Sauzede (nicolas.sauzede@gmail.com)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
audit_lints.py — Lints Audit Tool

Count clippy safety/panic warnings per crate and lint category.

By default only lints that are enabled (set to "warn" or "deny") in the
workspace Cargo.toml are audited.  Use --all-lints to audit every lint in
the built-in LINTS list regardless of workspace configuration.

Known lints (all candidates when --all-lints is used):
  Explicit panics:   unwrap_used, expect_used, panic, unwrap_in_result, get_unwrap
  Implicit panics:   indexing_slicing, string_slice
  Unfinished code:   todo, unimplemented, unreachable
  Overflow:          arithmetic_side_effects, float_arithmetic

Usage:
    python3 audit_lints.py [--manifest-path PATH] [--json] [--no-clean] [-v]
                           [--sort metrics|name] [--all-lints]
"""

import argparse
import json
import subprocess
import sys
try:
    import tomllib          # stdlib ≥ 3.11
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # pip install tomli for Python 3.10 and below
    except ModuleNotFoundError:
        tomllib = None      # graceful degradation — falls back to --all-lints behaviour
from collections import defaultdict
from pathlib import Path


# ── canonical lint list ──────────────────────────────────────────────────────
# This is the full set of lints this tool knows about.  When running without
# --all-lints the active subset is derived from [workspace.lints.clippy].

LINTS = [
    # Explicit panics
    "unwrap_used",
    "expect_used",
    "panic",
    "unwrap_in_result",
    "get_unwrap",
    # Implicit panics
    "indexing_slicing",
    "string_slice",
    # Unfinished code reaching prod
    "todo",
    "unimplemented",
    "unreachable",
    # Overflow (noisy — enable if you handle numeric code)
    "arithmetic_side_effects",
    "float_arithmetic",
]

# column header abbreviations (keep table narrow)
LINT_SHORT = {
    "unwrap_used":              "unwrap",
    "expect_used":              "expect",
    "panic":                    "panic",
    "unwrap_in_result":         "unwrap_res",
    "get_unwrap":               "get_unwrap",
    "indexing_slicing":         "idx_slice",
    "string_slice":             "str_slice",
    "todo":                     "todo",
    "unimplemented":            "unimpl",
    "unreachable":              "unreach",
    "arithmetic_side_effects":  "arith",
    "float_arithmetic":         "float",
}


# ── workspace lint detection ─────────────────────────────────────────────────

def enabled_lints_from_manifest(manifest_path: str) -> list[str] | None:
    """
    Parse [workspace.lints.clippy] from the workspace Cargo.toml and return
    the names of lints that are set to "warn" or "deny" — i.e. those that are
    actually enabled and will produce diagnostics.

    Returns None when:
      - tomllib/tomli is not available
      - the file cannot be parsed
      - the section is absent (e.g. a non-workspace manifest)

    Callers should fall back to the full LINTS list when None is returned.
    """
    if tomllib is None:
        return None
    try:
        with open(manifest_path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None

    clippy_section = (
        data
        .get("workspace", {})
        .get("lints", {})
        .get("clippy", {})
    )
    if not clippy_section:
        return None

    active = []
    for lint, level in clippy_section.items():
        # TOML values may be a plain string ("warn") or a table
        # {"level": "warn", "priority": -1} — handle both.
        if isinstance(level, dict):
            level = level.get("level", "")
        if isinstance(level, str) and level.lower() in ("warn", "deny"):
            active.append(lint)

    # Preserve the canonical ordering from LINTS so output is stable.
    lints_set = set(active)
    ordered = [l for l in LINTS if l in lints_set]
    # Append any workspace lints not in LINTS (unknown to this tool) at the end,
    # so they are at least passed to clippy even if they lack a short label.
    known = set(LINTS)
    for l in active:
        if l not in known:
            ordered.append(l)
            LINT_SHORT.setdefault(l, l[:10])  # auto-abbreviate unknown lints
    return ordered if ordered else None


# ── argument parsing ─────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Audit clippy lints across a Rust workspace."
    )
    p.add_argument("--manifest-path", default="Cargo.toml")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-clean", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument(
        "--sort", choices=["metrics", "name"], default="metrics",
        help="Sort crate rows by total warnings desc (default) or by crate name",
    )
    p.add_argument(
        "--all-lints", action="store_true",
        help=(
            "Audit all lints in the built-in LINTS list regardless of which "
            "lints are enabled in the workspace Cargo.toml. "
            "Default behaviour only audits lints set to 'warn' or 'deny' "
            "in [workspace.lints.clippy]."
        ),
    )
    return p.parse_args()


# ── cargo helpers ────────────────────────────────────────────────────────────

def cargo_clean(manifest, verbose):
    print("  › cargo clean …", flush=True)
    subprocess.run(
        ["cargo", "clean", "--manifest-path", manifest],
        stderr=None if verbose else subprocess.DEVNULL,
    )


def crate_name(package_id: str) -> str:
    """
    Extract bare crate name from Cargo's package_id, which has two formats:
      old: "name version (path#hash)"  → take first token
      new: "path+file:///...#version"  → take last path segment before '#'
    """
    if package_id.startswith("path+") or "://" in package_id:
        # new format: path+file:///home/user/proj/crates/foo#0.1.0
        return package_id.split("#")[0].rstrip("/").split("/")[-1]
    return package_id.split()[0]


def run_clippy(manifest, *, include_tests, verbose, lints):
    """Return {crate: {lint: count}} for the given lints."""
    cmd = [
        "cargo", "clippy",
        "--manifest-path", manifest,
        "--message-format=json",
        "-j", "1",
    ]
    if include_tests:
        cmd.append("--tests")
    cmd += ["--"]
    for lint in lints:
        cmd += ["-W", f"clippy::{lint}"]

    label = "with tests" if include_tests else "no tests"
    print(f"  › cargo clippy ({label}) …", flush=True)

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=None if verbose else subprocess.DEVNULL,
        text=True,
    )

    counts = defaultdict(lambda: defaultdict(int))
    lint_set = {f"clippy::{l}" for l in lints}

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("reason") != "compiler-message":
            continue
        code = ((msg.get("message") or {}).get("code") or {}).get("code", "")
        if code not in lint_set:
            continue
        crate = crate_name(msg.get("package_id", "unknown"))
        lint  = code.removeprefix("clippy::")
        counts[crate][lint] += 1

    return {c: dict(d) for c, d in counts.items()}


# ── result assembly ──────────────────────────────────────────────────────────

def merge(no_test, with_test, *, sort_by_metrics=True, lints):
    """Build sorted rows: [{crate, lints: {lint: (no, with, test_only)}, totals}]"""
    all_crates = sorted(set(no_test) | set(with_test))
    rows = []
    for crate in all_crates:
        lint_vals = {}
        crate_total_no = crate_total_with = 0
        for lint in lints:
            no    = no_test.get(crate, {}).get(lint, 0)
            with_ = with_test.get(crate, {}).get(lint, 0)
            lint_vals[lint] = (no, with_, with_ - no)
            crate_total_no   += no
            crate_total_with += with_
        rows.append({
            "crate":      crate,
            "lints":      lint_vals,
            "total_no":   crate_total_no,
            "total_with": crate_total_with,
        })
    rows.sort(key=lambda r: (-r["total_with"], r["crate"]) if sort_by_metrics else r["crate"])
    return rows


# ── output formatters ────────────────────────────────────────────────────────

def print_table(rows, lints):
    CRATE_COL = max(max(len(r["crate"]) for r in rows), 16)
    SUB = 4
    LINT_WIDTH = SUB * 3 + 2

    def lint_header(short):
        return f"{short:^{LINT_WIDTH}}"

    def sub_header():
        return f"{'P':>{SUB}} {'P+T':>{SUB}} {'T':>{SUB}}"

    def lint_cell(no, with_, only):
        return f"{no:>{SUB}} {with_:>{SUB}} {only:>{SUB}}"

    crate_pad = " " * CRATE_COL

    h1 = f"{'crate':<{CRATE_COL}}"
    for lint in lints:
        h1 += f"  {lint_header(LINT_SHORT.get(lint, lint[:10]))}"
    h1 += f"  {'TOTAL':^{LINT_WIDTH}}"
    h2 = crate_pad
    for _ in lints + ["total"]:
        h2 += f"  {sub_header()}"

    sep = "─" * len(h1)

    print(f"\n{h1}\n{h2}\n{sep}")

    grand_no = grand_with = grand_only = 0
    lint_grand = {l: [0, 0, 0] for l in lints}

    for r in rows:
        line = f"{r['crate']:<{CRATE_COL}}"
        row_only = r["total_with"] - r["total_no"]
        for lint in lints:
            no, with_, only = r["lints"][lint]
            line += f"  {lint_cell(no, with_, only)}"
            lint_grand[lint][0] += no
            lint_grand[lint][1] += with_
            lint_grand[lint][2] += only
        line += f"  {lint_cell(r['total_no'], r['total_with'], row_only)}"
        grand_no   += r["total_no"]
        grand_with += r["total_with"]
        grand_only += row_only
        print(line)

    print(sep)
    tot = f"{'TOTAL':<{CRATE_COL}}"
    for lint in lints:
        tot += f"  {lint_cell(*lint_grand[lint])}"
    tot += f"  {lint_cell(grand_no, grand_with, grand_only)}"
    print(tot + "\n")

    print("Columns: P=prod only  P+T=prod+tests  T=tests only\n")


def print_json(rows, lints):
    out_crates = []
    for r in rows:
        entry = {"crate": r["crate"], "lints": {}}
        for lint in lints:
            no, with_, only = r["lints"][lint]
            entry["lints"][lint] = {"no_tests": no, "with_tests": with_, "tests_only": only}
        entry["total"] = {"no_tests": r["total_no"], "with_tests": r["total_with"],
                          "tests_only": r["total_with"] - r["total_no"]}
        out_crates.append(entry)

    grand_no   = sum(r["total_no"]   for r in rows)
    grand_with = sum(r["total_with"] for r in rows)
    print(json.dumps({
        "crates": out_crates,
        "total": {
            "no_tests":   grand_no,
            "with_tests": grand_with,
            "tests_only": grand_with - grand_no,
        }
    }, indent=2))


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    manifest = str(Path(args.manifest_path).resolve())

    # Determine which lints to audit.
    if args.all_lints:
        active_lints = LINTS
        print("\nMode: all built-in lints (--all-lints)")
    else:
        active_lints = enabled_lints_from_manifest(manifest)
        if active_lints is None:
            # Fallback: tomllib absent, parse error, or no [workspace.lints.clippy]
            active_lints = LINTS
            if tomllib is None:
                print(
                    "\nWarning: tomllib not available (Python < 3.11 and tomli not installed).\n"
                    "         Falling back to all built-in lints.\n"
                    "         Install tomli (`pip install tomli`) or use Python 3.11+ to enable\n"
                    "         automatic detection of enabled lints.\n"
                )
            else:
                print(
                    "\nNote: No [workspace.lints.clippy] section found in manifest.\n"
                    "      Falling back to all built-in lints.\n"
                    "      Use --all-lints to silence this note.\n"
                )
        else:
            omitted = [l for l in LINTS if l not in active_lints]
            print(f"\nMode: workspace-enabled lints only ({len(active_lints)} active"
                  + (f", {len(omitted)} skipped" if omitted else "") + ")")
            if omitted:
                print(f"      Skipped (not warn/deny in workspace): {', '.join(omitted)}")
            print(f"      Use --all-lints to audit all {len(LINTS)} built-in lints.\n")

    print("\n[1/2] Auditing without test targets")
    if not args.no_clean:
        cargo_clean(manifest, args.verbose)
    no_test = run_clippy(manifest, include_tests=False, verbose=args.verbose,
                         lints=active_lints)

    print("\n[2/2] Auditing with test targets")
    if not args.no_clean:
        cargo_clean(manifest, args.verbose)
    with_test = run_clippy(manifest, include_tests=True, verbose=args.verbose,
                           lints=active_lints)

    all_crates = set(no_test) | set(with_test)
    if not all_crates:
        print("\n✓ No warnings found.\n")
        sys.exit(0)

    rows = merge(no_test, with_test, sort_by_metrics=(args.sort == "metrics"),
                 lints=active_lints)

    if args.json:
        print_json(rows, active_lints)
    else:
        print_table(rows, active_lints)


if __name__ == "__main__":
    main()
