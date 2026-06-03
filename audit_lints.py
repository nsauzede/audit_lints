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

Tracked lints:
  Explicit panics:   unwrap_used, expect_used, panic, unwrap_in_result, get_unwrap
  Implicit panics:   indexing_slicing, string_slice
  Unfinished code:   todo, unimplemented, unreachable
  Overflow:          arithmetic_side_effects, float_arithmetic

Usage:
    python3 audit_lints.py [--manifest-path PATH] [--json] [--no-clean] [-v]
                           [--sort metrics|name]
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


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



def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest-path", default="Cargo.toml")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-clean", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--sort", choices=["metrics", "name"], default="metrics",
                   help="Sort crate rows by total warnings desc (default) or by crate name")
    return p.parse_args()


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


def run_clippy(manifest, *, include_tests, verbose):
    """Return {crate: {lint: count}} for all tracked lints."""
    cmd = [
        "cargo", "clippy",
        "--manifest-path", manifest,
        "--message-format=json",
        "-j", "1",
    ]
    if include_tests:
        cmd.append("--tests")
    cmd += ["--"]
    for lint in LINTS:
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
    lint_set = {f"clippy::{l}" for l in LINTS}

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


def merge(no_test, with_test, *, sort_by_metrics=True):
    """Build sorted rows: [{crate, lints: {lint: (no, with, test_only)}, totals}]"""
    all_crates = sorted(set(no_test) | set(with_test))
    rows = []
    for crate in all_crates:
        lints = {}
        crate_total_no = crate_total_with = 0
        for lint in LINTS:
            no   = no_test.get(crate, {}).get(lint, 0)
            with_ = with_test.get(crate, {}).get(lint, 0)
            lints[lint] = (no, with_, with_ - no)
            crate_total_no   += no
            crate_total_with += with_
        rows.append({
            "crate":      crate,
            "lints":      lints,
            "total_no":   crate_total_no,
            "total_with": crate_total_with,
        })
    rows.sort(key=lambda r: (-r["total_with"], r["crate"]) if sort_by_metrics else r["crate"])
    return rows


def print_table(rows):
    # Two header lines:
    #   col1            | unwrap          | expect   | …  | TOTAL
    #                   | no  with  only  | no  …    |    | no  with  only
    CRATE_COL = max(max(len(r["crate"]) for r in rows), 16)
    # each lint gets 3 sub-columns of width 4, separated by spaces → 14 chars + 2 padding
    SUB = 4  # digits per sub-column
    LINT_WIDTH = SUB * 3 + 2  # "no  with only" ~ 14

    def lint_header(short):
        return f"{short:^{LINT_WIDTH}}"

    def sub_header():
        return f"{'P':>{SUB}} {'P+T':>{SUB}} {'T':>{SUB}}"

    def lint_cell(no, with_, only):
        return f"{no:>{SUB}} {with_:>{SUB}} {only:>{SUB}}"

    sep_unit = "─" * LINT_WIDTH
    crate_pad = " " * CRATE_COL

    # header row 1
    h1 = f"{'crate':<{CRATE_COL}}"
    for lint in LINTS:
        h1 += f"  {lint_header(LINT_SHORT[lint])}"
    h1 += f"  {'TOTAL':^{LINT_WIDTH}}"
    # header row 2
    h2 = crate_pad
    for _ in LINTS + ["total"]:
        h2 += f"  {sub_header()}"

    sep = "─" * len(h1)

    print(f"\n{h1}\n{h2}\n{sep}")

    grand_no = grand_with = grand_only = 0
    lint_grand = {l: [0, 0, 0] for l in LINTS}

    for r in rows:
        line = f"{r['crate']:<{CRATE_COL}}"
        row_only = r["total_with"] - r["total_no"]
        for lint in LINTS:
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
    for lint in LINTS:
        tot += f"  {lint_cell(*lint_grand[lint])}"
    tot += f"  {lint_cell(grand_no, grand_with, grand_only)}"
    print(tot + "\n")

    print("Columns: P=prod only  P+T=prod+tests  T=tests only\n")


def print_json(rows):
    out_crates = []
    for r in rows:
        entry = {"crate": r["crate"], "lints": {}}
        for lint in LINTS:
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


def main():
    args = parse_args()
    manifest = str(Path(args.manifest_path).resolve())

    print("\n[1/2] Auditing without test targets")
    if not args.no_clean:
        cargo_clean(manifest, args.verbose)
    no_test = run_clippy(manifest, include_tests=False, verbose=args.verbose)

    print("\n[2/2] Auditing with test targets")
    if not args.no_clean:
        cargo_clean(manifest, args.verbose)
    with_test = run_clippy(manifest, include_tests=True, verbose=args.verbose)

    all_crates = set(no_test) | set(with_test)
    if not all_crates:
        print("\n✓ No warnings found.\n")
        sys.exit(0)

    rows = merge(no_test, with_test, sort_by_metrics=(args.sort == "metrics"))

    if args.json:
        print_json(rows)
    else:
        print_table(rows)


if __name__ == "__main__":
    main()
