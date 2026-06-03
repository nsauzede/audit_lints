# Lints Audit Tool
Audit various lints reported by `cargo clippy`, sorted by crates within a workspace.
Refer to [HANDOFF.md](HANDOFF.md) for more information.

# Quick Usage

```shell
$ cd ws
$ ../audit_lints.py

[1/2] Auditing without test targets
  › cargo clean …
  › cargo clippy (no tests) …

[2/2] Auditing with test targets
  › cargo clean …
  › cargo clippy (with tests) …

crate                 unwrap          expect          panic         unwrap_res      get_unwrap      idx_slice       str_slice          todo           unimpl         unreach          arith           float           TOTAL
                     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T     P  P+T    T
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
lints_demo           3    6    3     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    1    0     1    1    0    14   26   12
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
TOTAL                3    6    3     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    2    1     1    1    0     1    1    0    14   26   12

Columns: P=prod only  P+T=prod+tests  T=tests only

$
```
