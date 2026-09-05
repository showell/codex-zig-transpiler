# SENT as PR 128 — zig plug: empty slice, and the linked list must materialise

https://github.com/damiant3/Cobblestone/pull/128

Branch `zig-plug-empty-slice-and-ll-copy` off `675a0775` (Update 55), one
commit, no stack. Backlog row `Ladder: zig-empty-slice-and-ll-copy`.

---

## 1. `cx_address_of` read the pointer of a zero-length slice

Zig leaves `.ptr` undefined when `len` is 0 — safe builds fill it with `0xaa`
— so a zero-length `Text` answered the distance from the region base to a
value that was never a pointer, and `@intCast` trapped:

```
panic: integer does not fit in destination type
  cx_address_of  <- mcopy_text  <- lcopy_text  <- lcopy_expr  <- lower_defs_keep
```

The instrumented run printed `t.ptr=0xaaaaaaaaaaaaaaaa t.len=0x0`. Nothing was
corrupt and nothing had been reclaimed — an ordinary empty text.

Bare metal has no such case: its empty text is a real block at a real
address. Returning 0 is the right answer rather than a convenience, because
`mcopy-text` reads 0 as "not in the copied region, share as-is", and an empty
text is exactly what needs no copy.

## 2. `__linked-list-to-list` returned its argument

A linked list and a list share a representation in this plug, so identity is
representationally right — and still wrong. Callers write

```
deck-record (__linked-list-to-list xs)
```

and `deck-record` means *put the result on the deck*. Identity allocates
nothing inside the bracket, so the value stays on the bivy where the caller
built it, and the next `phase-compact` reclaims it. Bare metal's
`emit-linked-list-to-list-builtin` allocates a fresh list, which is what
makes the bracket mean anything; the wasm plug calls `$ll_to_list`.

Measured: `scope-achapter`'s defs — `defs = deck-record
(__linked-list-to-list raw-defs)` — landed at bivy offset 662,977,720 with
the deck cursor at 553,438,952, 9.5 MB below. `check-all-defs` later walked
to definition 702 of 714 and read a list whose length had been overwritten
to 0.

`cx_ll_copy` is `cx_ll_concat`'s body with one operand.

## The C# plug has the same identity emitter

`CSharpEmitterExpressions.codex` emits `__linked-list-to-list` as its
argument too. If C#'s linked list and list also share a representation, the
same contract break is there. **That is a reading of the source, not a
measurement — we have not run it**, and this PR does not touch it.

## What these two are measured to fix

With these and the `mcopy-type` tag fix (PR #127), a hosted Codex compiler
built by this plug reaches its fixed point at U56: pass 1 under QEMU and
pass 2 as a native binary both 2,932,307 bytes, byte-identical, and the
sample program matches its expected output on all 9 lines. Before them it
did not transpile a 248-byte subject.

## Not included

Three further zig-plug emitters this needed — `poke-16`, `port-out-byte` and
`__self-type-defs`, the whole refusal set once a subject carries
`Chapter: Opening` — sit on top of `poke-32`/`poke-byte` work that is not
upstream yet, so they are not in this PR.


🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01VpLJYCGhn1N3qkbuSU1k6s
