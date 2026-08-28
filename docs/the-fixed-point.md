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

First, what it is NOT easy to slip past, because the tempting summary --
"it only checks the emitter against itself, so a consistent bug passes" -- is
wrong in practice.

The emitter is its own subject. A defect in translating some construct does
not just corrupt output somewhere off to the side; if the compiler uses that
construct anywhere in 2.9 MB of source, the defect corrupts **the binary that
performs pass 2**. A corrupted emitter then emits different bytes than the
uncorrupted one that built it, and the comparison fails. Add that pass 1's
emitter comes from the seed's x86 backend and pass 2's from the zig plug's,
and a defect has to survive being applied to itself, across two backends, and
still produce zig that compiles at all. Most do not come close.

So the things that DO get through are specific:

**Constructs the subject never uses.** A compiler is a broad program but not
an exhaustive one. This is a coverage gap rather than a consistency gap, and
the ladder's corpus is what closes it.

**Emissions that are wrong but neutral here.** A different-but-equivalent
form for something the compiler does use compiles, leaves the emitter's
behaviour unchanged, and agrees. Wrong against a specification, invisible to
this property.

**A wrong answer both backends share.** The canonical shape: code that
compiles, runs, and returns the wrong number, identically on x86 and in zig.
Self-application cannot see it. That needs an oracle outside the zig arm, and
there is one -- the **codex-zig-ladder** compiles the same chapters through
the seed on bare metal and requires byte agreement across fourteen rungs.
This repository does not replace it and cannot.

**Which compiler you built.** Two healthy revisions each hold their own fixed
point, with different bytes, so agreement never identifies the source. Do not
read this as "it holds at any revision" -- holding requires a working compiler
and a working plug, and this repository has only seen it hold at the revision
`generated/PROVENANCE` names. The point is narrower: *given* that it holds,
that fact alone tells you nothing about which checkout you had.

`generated/PROVENANCE` is the answer to that question and the only one -- it
names the checkout, its revision, whether that checkout was dirty, and the
toolchain versions. Read it before quoting a result.

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
