// SPDX-License-Identifier: MIT
// Copyright (c) 2026 — Nicolas Sauzede (nicolas.sauzede@gmail.com)
use std::num::ParseIntError;

// ── prod: one lint each ───────────────────────────────────────────────────────

/// unwrap_used only
fn demo_unwrap(s: &str) -> i32 {
    s.parse::<i32>().ok().unwrap()                              // unwrap_used
}

/// expect_used only
fn demo_expect(s: &str) -> i32 {
    s.parse::<i32>().ok().expect("must be a number")            // expect_used
}

/// panic only — no indexing, return constant after guard
fn demo_panic(v: &[i32]) -> i32 {
    if v.is_empty() { panic!("empty slice"); }                  // panic
    42
}

/// unwrap_in_result only — .unwrap() on Result inside -> Result fn
fn demo_unwrap_in_result(s: &str) -> Result<i32, ParseIntError> {
    let n = s.parse::<i32>().unwrap();                          // unwrap_in_result
    Ok(n)
}

/// get_unwrap only — .get().unwrap() in a non-Result fn
fn demo_get_unwrap(v: &[i32]) -> i32 {
    *v.get(0).unwrap()                                          // get_unwrap
}

/// indexing_slicing only
fn demo_indexing(v: &[i32]) -> i32 {
    v[0]                                                        // indexing_slicing
}

/// string_slice only — byte-index slicing of a &str
fn demo_string_slice(s: &str) -> &str {
    &s[0..1]                                                    // string_slice
}

/// todo only
fn demo_todo() -> i32 {
    todo!("implement me")                                       // todo
}

/// unimplemented only
fn demo_unimplemented() -> i32 {
    unimplemented!("not yet")                                   // unimplemented
}

/// unreachable only
fn demo_unreachable(x: u8) -> i32 {
    match x {
        0 => 0,
        1 => 1,
        _ => unreachable!("only 0 or 1 expected"),              // unreachable
    }
}

/// arithmetic_side_effects only
fn demo_arith(a: u8, b: u8) -> u8 {
    a + b                                                       // arithmetic_side_effects
}

/// float_arithmetic only
fn demo_float(a: f32, b: f32) -> f32 {
    a + b                                                       // float_arithmetic
}

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
    let _ = (demo_todo, demo_unimplemented, demo_arith, demo_float); // ref without calling
}

// ── tests: one lint each ──────────────────────────────────────────────────────

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
        let v = vec![1i32, 2, 3];
        let _ = v[0];                                           // indexing_slicing
    }

    #[test]
    fn test_string_slice() {
        let _ = &"hello"[0..1];                                 // string_slice
    }

    #[test]
    fn test_todo() {
        let f: fn() -> i32 = || todo!("test");                  // todo
        let _ = f;
    }

    #[test]
    fn test_unimplemented() {
        let f: fn() -> i32 = || unimplemented!();               // unimplemented
        let _ = f;
    }

    #[test]
    fn test_unreachable() {
        let x: u8 = 0;
        let _ = match x {
            0 => 0,
            1 => 1,
            _ => unreachable!("only 0 or 1"),                   // unreachable
        };
    }

    #[test]
    fn test_arith() {
        // arithmetic_side_effects does not fire inside #[test] bodies (by design).
        // Calling the prod fn exercises the code; T column will always be 0 for this lint.
        let _ = demo_arith(1, 2);
    }

    #[test]
    fn test_float() {
        // Same: float_arithmetic does not fire in #[test] bodies.
        let _ = demo_float(1.0, 2.0);
    }
}
