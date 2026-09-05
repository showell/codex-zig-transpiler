# ADDED to PR 118 — the rest of the zig plug's refusal set

https://github.com/damiant3/Cobblestone/pull/118

Branch `zig-plug-memory-builtins`, based on `14ec571b` (Update 54 correction),
now 7 commits. Backlog row rides with the PR's own.

Two commits pushed on top of the existing five:

- `zig plug: poke-16, port-out-byte and __self-type-defs` — the three that
  still refused once a subject carries `Chapter: Opening`. Expressed against
  the SINGLE-FILE `ZigEmitter.codex`, because our four-page split is not
  upstream and this PR's base predates U55.
- `zig plug: run.ps1 creates its output directory and falls back to the seed`
  — was unsent; needed to run the probe at all, so it went where it was used.

## Measured, at that base

    probe (b) = act
     p <- port-out-byte 1016 65
     let w = poke-16 b 0 4660
     in let back = bit-and (peek-32 b 0) 65535
     in back + p

Transpiled and run: prints `4660`. 0x1234 stored as two little-endian bytes
and read back, with the port write contributing 0. Exercises the PR's own
`peek-32` and `alloc-bytes` as well.

`__self-type-defs` is NOT exercised — only the compiler reaches it, and the
probe's emitted zig contains no `cx_ll_empty(TypeBinding)`.

## Why run.ps1 mattered

In a fresh checkout it asked `compile.ps1` to write a log into a directory
nothing had created, so the failure read `IR compile failed; see <that log>`
— naming a file it had just been unable to create. Then it refused for want
of a self-hosted kernel a plug run does not need. Both were hit here before
anything could be measured.
