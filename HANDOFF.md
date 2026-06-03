# Handoff: Lints Audit Tool

## License

MIT — see `LICENSE` file. All source files carry an `SPDX-License-Identifier: MIT` header.

## Goal

A Python script (`audit_lints.py`) that counts specific clippy lint warnings across
a Rust workspace, broken down by crate and lint category, with separate columns for
prod-only (P), prod+tests (P+T), and tests-only (T) counts.

Alongside: a minimal demo workspace (`ws/`) with one crate (`lints_demo`) that fires
exactly one instance of each tracked lint in prod code and one in test code.

---

## Tracked lints

```python
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
```

`LINTS` is the **canonical candidate list** — every lint this tool knows about.
At runtime the tool selects which subset to actually audit (see Lint selection below).

All selected lints are passed as `-W clippy::lint` flags on the command line.
**No `clippy.toml` needed.**

---

## Lint selection: workspace-driven vs all-lints

### Default behaviour (workspace-driven)

By default the tool reads `[workspace.lints.clippy]` from the workspace
`Cargo.toml` and audits **only the lints that are set to `"warn"` or `"deny"`**.
This keeps the audit honest: if a lint is not enabled in the workspace config,
clippy would never surface it in a normal build, so auditing it creates noise.

The tool uses Python's stdlib `tomllib` (≥ 3.11) or the third-party `tomli` package
(Python ≤ 3.10) to parse the manifest.  If neither is available, or if the manifest
has no `[workspace.lints.clippy]` section, the tool falls back to the full `LINTS`
list with a printed notice.

The startup banner shows which lints are active and which were skipped:

```
Mode: workspace-enabled lints only (12 active)
      Use --all-lints to audit all 12 built-in lints.
```

Or, if some lints are disabled in the workspace:

```
Mode: workspace-enabled lints only (10 active, 2 skipped)
      Skipped (not warn/deny in workspace): arithmetic_side_effects, float_arithmetic
      Use --all-lints to audit all 12 built-in lints.
```

### `--all-lints` flag

Pass `--all-lints` to force the tool to audit every lint in `LINTS` regardless of
the workspace configuration.  Useful when you want to survey lints before enabling
them, or when the workspace has no `[workspace.lints.clippy]` section.

```bash
python3 audit_lints.py --all-lints
```

### Unknown workspace lints (forward compatibility)

If `[workspace.lints.clippy]` contains a lint that is **not** in `LINTS`
(i.e. a lint this tool doesn't know about yet), the tool:

1. Includes it in the active set so it still gets audited.
2. Auto-abbreviates its name to 10 chars for the table header.
3. Does **not** fail — the lint just lacks a curated short label.

This means you can add new lints to the workspace config without touching the script;
they will be picked up automatically on the next run.

---

## Workspace layout

```
ws/
├── Cargo.toml                   # workspace root — lints defined here
└── crates/
    └── lints_demo/
        ├── Cargo.toml           # opts in via [lints] workspace = true
        └── src/
            └── main.rs
```

### `ws/Cargo.toml`

```toml
[workspace]
resolver = "3"          # edition 2024 resolver
members = ["crates/lints_demo"]

[workspace.lints.clippy]
# Explicit panics
unwrap_used              = "warn"
expect_used              = "warn"
panic                    = "warn"
unwrap_in_result         = "warn"
get_unwrap               = "warn"
# Implicit panics
indexing_slicing         = "warn"
string_slice             = "warn"
# Unfinished code reaching prod
todo                     = "warn"
unimplemented            = "warn"
unreachable              = "warn"
# Overflow (noisy — enable if you handle numeric code)
arithmetic_side_effects  = "warn"
float_arithmetic         = "warn"
```

### `ws/crates/lints_demo/Cargo.toml`

```toml
[package]
name = "lints_demo"
version = "0.1.0"
edition = "2024"

[lints]
workspace = true
```

### `ws/crates/lints_demo/src/main.rs`

One prod function and one test per lint, **no cross-firing**.

Cross-firing traps to avoid:

| Lint to isolate    | Trap                                        | Fix                                        |
|--------------------|---------------------------------------------|-------------------------------------------|
| `unwrap_used`      | `.get().unwrap()` also fires `get_unwrap`   | Use `parse().ok().unwrap()` instead        |
| `unwrap_in_result` | needs `.unwrap()` on `Result` (not `Option`)| Use `parse::<i32>().unwrap()` in `->Result`|
| `indexing_slicing` | `v[0]` in `demo_panic` double-fires         | Return constant `42` after the panic guard |
| `test_unwrap_used` | `.get().unwrap()` also fires `get_unwrap`   | Use `parse().ok().unwrap()` in test too    |

(See `ws/crates/lints_demo/src/main.rs` for the full source.)

---

## The script: `audit_lints.py`

### Usage

```bash
python3 audit_lints.py                          # workspace-enabled lints only (default)
python3 audit_lints.py --all-lints              # audit all built-in lints regardless of workspace
python3 audit_lints.py --sort name              # alphabetical — stable for diff
python3 audit_lints.py --json                   # JSON output
python3 audit_lints.py --manifest-path path/to/Cargo.toml
python3 audit_lints.py --no-clean               # skip cargo clean (faster, less stable)
python3 audit_lints.py -v                       # show clippy stderr
```

### Key design decisions

**Workspace-driven lint selection (new in v2):**
Parse `[workspace.lints.clippy]` with `tomllib` (stdlib ≥ 3.11) or `tomli`.
Only lints set to `"warn"` or `"deny"` are audited.  This ensures the audit
reflects what clippy actually enforces, not a superset that may include lints the
project has deliberately left disabled.  `--all-lints` restores the v1 behaviour.

**TOML value handling:** the workspace config may use either a plain string
(`"warn"`) or an inline table (`{ level = "warn", priority = -1 }`).  Both are
handled; only the `level` key is consulted.

**Two clippy passes:**
1. `cargo clippy -j 1` — prod targets only → P column
2. `cargo clippy -j 1 --tests` — prod + test targets → P+T column

T = P+T − P, computed in Python.

**`cargo clean` before each pass** (`--no-clean` to skip): prevents incremental cache
from pass 1 bleeding into pass 2 — test-target artifacts reuse prod artifacts and can
cause diagnostics to be silently skipped on the second run.

**`-j 1`**: deterministic diagnostic order across runs → raw JSON and `--json` output
are diffable.

**No `-A clippy::all`**: placing `-A` after `-W` on the command line makes the allow
win, silencing everything and producing zero results with no error. Only `-W` flags.

**`stderr=subprocess.DEVNULL`** (not `PIPE`): avoids process hangs when stderr fills
its buffer before stdout is consumed.

**`crate_name()` handles both Cargo `package_id` formats:**
- Old: `"name version (path#hash)"` → first whitespace-delimited token
- New (Cargo 1.77+): `"path+file:///…/crate_name#version"` → last path segment before `#`

**Sorting:** `--sort metrics` (default) = total P+T desc, name as tiebreaker.
`--sort name` = pure alphabetical, stable across runs for diffing.

### Expected output on the demo workspace

```
Mode: workspace-enabled lints only (12 active)
      Use --all-lints to audit all 12 built-in lints.

[1/2] Auditing without test targets
  › cargo clean …
  › cargo clippy (no tests) …

[2/2] Auditing with test targets
  › cargo clean …
  › cargo clippy (with tests) …

crate          unwrap  expect   panic  unwrap_res  get_unwrap  idx_slice  str_slice  todo  unimpl  unreach  arith  float   TOTAL
                P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T
lints_demo     3   6 3  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   1 0  1   1 0  14  26 12
```

When `arithmetic_side_effects` and `float_arithmetic` are commented out or set to
`"allow"` in the workspace Cargo.toml, the run reports:

```
Mode: workspace-enabled lints only (10 active, 2 skipped)
      Skipped (not warn/deny in workspace): arithmetic_side_effects, float_arithmetic
```

…and the table has 10 lint columns instead of 12.

**`unwrap P=3` is expected:** `unwrap_used` fires on every `.unwrap()` call site,
including those inside `demo_unwrap_in_result` and `demo_get_unwrap`. One call site
can emit multiple lint codes simultaneously — fixing one `.unwrap()` decrements
multiple columns at once, which is useful signal for prioritisation.

**`arith` and `float` T=0 is expected and correct:** `arithmetic_side_effects` and
`float_arithmetic` are restriction lints that clippy explicitly does not fire inside
`#[test]` fn bodies by design. No workaround exists — T will always be 0 for these
two lints. The P count is still useful for tracking overflow risks in prod code.

---

## Lessons learned / traps

| Trap | Symptom | Fix |
|------|---------|-----|
| `-A clippy::all` after `-W clippy::lint` | Zero results, no error | Remove `-A clippy::all` entirely |
| `stderr=PIPE` unused | Process hangs on large projects | Use `stderr=DEVNULL` |
| `--all-targets` instead of `--tests` | Inconsistent counts | Use `--tests` for pass 2 only |
| No `cargo clean` between passes | Test-only warnings missing | Clean before each pass |
| Old vs new `package_id` format | Full path shown as crate name | Handle both formats in `crate_name()` |
| `v[0]` in panic demo | `indexing_slicing` double-counts | Return constant instead of indexing |
| `.get().unwrap()` in unwrap demo | `get_unwrap` double-counts | Use `parse().ok().unwrap()` instead |
| `cargo new --workspace` | Error: flag does not exist | Create workspace `Cargo.toml` by hand |
| `test_helper_arith` outside `#[cfg(test)]` | Adds extra P hits | Don't add helper fns — T=0 is correct |
| `arith`/`float` T always 0 | Looks like a bug | It's by design — restriction lints skip `#[test]` bodies |
| `Ok(n * 2)` in `demo_unwrap_in_result` | `arith` P=2 unexpectedly | Any arithmetic in prod code counts — use `Ok(n)` |
| tomllib absent on Python ≤ 3.10 | Falls back to all lints | `pip install tomli` or use Python 3.11+ |
| Workspace lint as inline table `{level="warn"}` | Level not detected | Handled: dict path reads `.get("level")` |

---

## To add a new lint

1. Append its name to `LINTS` in `audit_lints.py`
2. Add a short label to `LINT_SHORT`
3. Add the lint under `[workspace.lints.clippy]` in `ws/Cargo.toml` (set to `"warn"`)
4. Add a prod function and a test in `main.rs` that fire it in isolation

No other changes needed — table, JSON output, and clippy invocation all derive from
the active lint list automatically.  The new lint will be picked up in workspace-driven
mode immediately once step 3 is done.

---

## Changelog

### v2 — workspace-driven lint selection

- **Default mode now reads `[workspace.lints.clippy]`** and audits only lints set to
  `"warn"` or `"deny"`.  This eliminates auditing lints the workspace has not opted
  into, preventing false-negatives where a lint is "enabled" in the audit but
  `allow`-ed in the workspace (producing zero hits that look like clean code).
- **`--all-lints` flag** restores the v1 behaviour: audit every lint in `LINTS`
  regardless of the workspace configuration.
- Startup banner reports the active lint set and any skipped lints.
- `merge()`, `run_clippy()`, `print_table()`, and `print_json()` now accept an
  explicit `lints` parameter instead of relying on the module-level `LINTS` constant,
  making the active set explicit throughout.
- Forward-compatible: workspace lints not in `LINTS` are auto-included and
  auto-abbreviated rather than silently ignored.
- Graceful degradation when `tomllib`/`tomli` is unavailable: falls back to all lints
  with a printed warning.
