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

All passed as `-W clippy::lint` flags on the command line. **No `clippy.toml` needed.**

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
|--------------------|---------------------------------------------|--------------------------------------------|
| `unwrap_used`      | `.get().unwrap()` also fires `get_unwrap`   | Use `parse().ok().unwrap()` instead        |
| `unwrap_in_result` | needs `.unwrap()` on `Result` (not `Option`)| Use `parse::<i32>().unwrap()` in `->Result`|
| `indexing_slicing` | `v[0]` in `demo_panic` double-fires         | Return constant `42` after the panic guard |
| `test_unwrap_used` | `.get().unwrap()` also fires `get_unwrap`   | Use `parse().ok().unwrap()` in test too    |

```rust
use std::num::ParseIntError;

// ── prod: one lint each ───────────────────────────────────────────────────────

fn demo_unwrap(s: &str) -> i32 {
    s.parse::<i32>().ok().unwrap()                              // unwrap_used
}
fn demo_expect(s: &str) -> i32 {
    s.parse::<i32>().ok().expect("must be a number")            // expect_used
}
fn demo_panic(v: &[i32]) -> i32 {
    if v.is_empty() { panic!("empty slice"); }                  // panic
    42
}
fn demo_unwrap_in_result(s: &str) -> Result<i32, ParseIntError> {
    let n = s.parse::<i32>().unwrap();                          // unwrap_in_result
    Ok(n * 2)
}
fn demo_get_unwrap(v: &[i32]) -> i32 {
    *v.get(0).unwrap()                                          // get_unwrap
}
fn demo_indexing(v: &[i32]) -> i32 {
    v[0]                                                        // indexing_slicing
}
fn demo_string_slice(s: &str) -> &str {
    &s[0..1]                                                    // string_slice
}
fn demo_todo() -> i32 {
    todo!("implement me")                                       // todo
}
fn demo_unimplemented() -> i32 {
    unimplemented!("not yet")                                   // unimplemented
}
fn demo_unreachable(x: u8) -> i32 {
    match x { 0 => 0, 1 => 1, _ => unreachable!("only 0|1"),  // unreachable
    }
}
fn demo_arith(a: u8, b: u8) -> u8   { a + b }                  // arithmetic_side_effects
fn demo_float(a: f32, b: f32) -> f32 { a + b }                 // float_arithmetic

fn main() {
    let v = vec![1i32, 2, 3];
    println!("{}", demo_unwrap("21"));
    println!("{}", demo_expect("21"));
    println!("{}", demo_panic(&v));
    println!("{}", demo_unwrap_in_result("21").unwrap_or(0));
    println!("{}", demo_get_unwrap(&v));
    println!("{}", demo_indexing(&v));
    println!("{}", demo_string_slice("hello"));
    let _ = demo_unreachable(0);
    println!("{}", demo_arith(1, 2));
    println!("{}", demo_float(1.0, 2.0));
    let _ = (demo_todo, demo_unimplemented);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_unwrap_used() {
        let _ = "1".parse::<i32>().ok().unwrap();               // unwrap_used
    }
    #[test]
    fn test_expect_used() {
        let _ = "1".parse::<i32>().ok().expect("digit");        // expect_used
    }
    #[test]
    fn test_panic() {
        let v = vec![1i32, 2, 3];
        if v.is_empty() { panic!("empty"); }                    // panic
    }
    #[test]
    fn test_unwrap_in_result() -> Result<(), ParseIntError> {
        let _ = "1".parse::<i32>().unwrap();                    // unwrap_in_result
        Ok(())
    }
    #[test]
    fn test_get_unwrap() {
        let v = vec![1i32, 2, 3];
        let _ = v.get(0).unwrap();                              // get_unwrap
    }
    #[test]
    fn test_indexing_slicing() {
        let v = vec![1i32, 2, 3]; let _ = v[0];                // indexing_slicing
    }
    #[test]
    fn test_string_slice() {
        let _ = &"hello"[0..1];                                 // string_slice
    }
    #[test]
    fn test_todo() {
        let f: fn() -> i32 = || todo!("test"); let _ = f;      // todo
    }
    #[test]
    fn test_unimplemented() {
        let f: fn() -> i32 = || unimplemented!(); let _ = f;   // unimplemented
    }
    #[test]
    fn test_unreachable() {
        let x: u8 = 0;
        let _ = match x { 0=>0, 1=>1, _=>unreachable!() };     // unreachable
    }
    #[test]
    fn test_arith() {
        // arithmetic_side_effects does NOT fire inside #[test] bodies — by design.
        // Just call the prod fn to exercise the code path; T will always be 0.
        let _ = demo_arith(1, 2);
    }
    #[test]
    fn test_float() {
        // Same: float_arithmetic does not fire in #[test] bodies.
        let _ = demo_float(1.0, 2.0);
    }
}
```

---

## The script: `audit_lints.py`

### Usage

```bash
python3 audit_lints.py                          # pretty table, sort by metrics (default)
python3 audit_lints.py --sort name              # alphabetical — stable for diff
python3 audit_lints.py --json                   # JSON output
python3 audit_lints.py --manifest-path path/to/Cargo.toml
python3 audit_lints.py --no-clean               # skip cargo clean (faster, less stable)
python3 audit_lints.py -v                       # show clippy stderr
```

### Key design decisions

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
crate          unwrap  expect   panic  unwrap_res  get_unwrap  idx_slice  str_slice  todo  unimpl  unreach  arith  float   TOTAL
                P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T  P P+T T
lints_demo     3   6 3  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   2 1  1   1 0  1   1 0  14  26 12
```

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

---

## To add a new lint

1. Append its name to `LINTS` in `audit_lints.py`
2. Add a short label to `LINT_SHORT`
3. Add the lint under `[workspace.lints.clippy]` in `ws/Cargo.toml`
4. Add a prod function and a test in `main.rs` that fire it in isolation

No other changes needed — table, JSON output, and clippy invocation all derive from
`LINTS` automatically.
