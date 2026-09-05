# SENT as PR 130 — real-to-int/real-from-int, replacing the closed PR 100

https://github.com/damiant3/Cobblestone/pull/130   (PR 100 closed)

Branch `zig-plug-real-int-conversions` off `675a0775` (Update 55), one
commit, +62/-1. Backlog row `Ladder: zig-real-int-conversions`.

---

## What the review said, and what changed

#100's review found the emitter correct: NaN caught by `v != v`, both
infinities by the range tests, the top bound exact, `-2^63` admitted by `<`
rather than `<=`, `-0.0` truncating to 0 the way `cvttsd2si` does, and no
input where the zig arm disagrees with the x86 one.

**The blocker was the expectation, not the emitter.** #100 put NaN, infinity
and overflow rows in `codex/test/ops`, which `build/test-cross-batch.ps1`
grades on arm64 and riscv64 as well — and those three cases are exactly where
the ISAs disagree: x86 answers the integer indefinite, arm64 and riscv
saturate.

That is settled now, by you: `real-to-int-wide.codex` carries the unambiguous
range for all three backends, and says why in its own prose. **So this PR adds
no cross-graded expectation at all** — the emitter alone, and the two script
fixes the review asked for.

## Measured, transpiled and run

The plug emits `real-to-bits` and `bits-to-real` and neither of the two
conversions beside them, so a program that turns a Real into an Integer or
back refuses at the emitter. `show` on a Real routes through the same
conversion, so it is not an exotic path.

| probe | answer |
|---|---|
| `real-from-int` then `real-to-int` of `3000000000` | `3000000000` |
| the same of `-3000000000` | `-3000000000` |
| `real-to-int 2.75` | `2` |
| `real-to-int -2.75` | `-2` |

3000000000 is above 2^31 on purpose — the range a 32-bit conversion saturates
in, which is where the riscv encoder defect #100 exposed lived. Truncation is
toward zero rather than toward the floor. Only unambiguous values, the
standard `real-to-int-wide` sets.

## The two script notes from the review

`run.ps1` creates the `build-output` directory it writes its log into. Without
it a fresh checkout failed as `IR compile failed; see <that log>`, naming a
file it had just been unable to create.

And it passes `-Kernel` in **both** branches, which is the half the earlier
version got wrong: testing an absolute path and then passing nothing left
`compile.ps1` on its own relative default, so from any working directory but
the repo root the test passed and the compile failed anyway. Passing it
explicitly also puts the choice in the `kernel:` digest line. This is related
to backlog 2.26 — the same scripts sharing a fixed scratch path — and is not
that defect.

## Backlog

Row **2.29**, since 2.06 is taken on your side.


🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01VpLJYCGhn1N3qkbuSU1k6s
