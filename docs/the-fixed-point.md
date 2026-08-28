# The fixed point: what it proves, and what it does not

The property is one comparison:

> The emitter emits the same bytes for its own source whether it is running
> on bare metal under QEMU, or as the native binary that run produced.
>
>     blob -> QEMU -> zig -> exe -> (the same source again) -> zig -> diff

## What it covers

Everything. Not as a figure of speech: the subject *is* the compiler, so the
program under test transpiles the parser, the desugarer, the type checker,
the unifier, lowering, the IR passes, lambda lifting, the IR text emitter,
the IR text parser and the zig emitter. Any construct any of those chapters
uses is a construct the emitter had to handle correctly enough to reproduce.

A subtler thing it covers: **the emitter's output is a function of its input
alone.** Anything non-deterministic in the pipeline — a wall clock, a hash
iteration order, an address that moves — shows up here as two runs that
disagree. That is why `BootPaintStubs.codex` answers 0 for `bp-rtc-seconds`
rather than carrying the real 341-line chapter; the real one would put a
clock inside the subject and no fixed point could ever hold.

## What it does not cover

**Whether the emitter is doing anything at all.** The fixed point would be
satisfied perfectly by a "transpiler" that emitted a program which printed
its own input back. That is what `samples/arith.codex` is for: a small
program with a known answer, transpiled, compiled and run on every build,
whose output is checked line for line. It prints 42, 92, 610 and 5050, none
of which appear in its source, and 92 comes out of a backtracking search.

**Whether the answer is right.** The emitter is its own subject, so a defect
in translating a construct the compiler uses corrupts the binary that
performs pass 2, and the comparison fails — most mistakes cannot survive
being applied to themselves. What survives is narrower: a construct the
subject never uses, or an emission that is wrong against a specification but
neutral for the emitter's own execution.

**Which compiler you built.** Two healthy revisions each hold their own fixed
point, with different bytes, so agreement never identifies the source. Do not
read that as "it holds at any revision" — holding takes a working compiler and
a working plug. `generated/PROVENANCE` names the checkout, its revision,
whether it was dirty, and the toolchain versions. Read it before quoting a
result.

## What a break means

A break is a finding, not a flake. Both passes run the same code in the same
order — that is what the in-memory IR text round trip buys — so they have no
licence to differ.

When they do, `build.py` prints the first 20 lines of the diff. The two
things worth checking first:

1. **Did the checkout move under the build?** A stale `codexzig.ir` beside a
   fresh bundle is caught by the fingerprint files -- each guest stage is
   keyed to the exact blob it was handed, in `generated/intake/` -- but a
   checkout edited mid-build is not. `--force` settles it.
2. **Is the difference in a lifted lambda?** `lift-lambdas` is on this path
   and its ceiling here is 0 for a reason the harness explains at length. Any
   non-zero ceiling stops the lift on its first definition and emits a
   truncated program *without saying so* — a failure mode that looks exactly
   like an emitter bug.

## What it is not there to do

It is not a regression suite, and this repository should not grow one. The
whole reason a single invariant is worth building a repository around is that
it is cheap to state and cheap to check. A second property that needed a
paragraph of interpretation would already have cost more than it is worth.
