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

**Whether the answer is right.** This is the important one. The fixed point
is a self-consistency property: it says the emitter agrees with itself. An
emitter with a bug that affects both passes identically passes cleanly. The
canonical shape is a silently wrong answer — code that compiles, runs, and
returns the wrong number — which self-agreement cannot see at all.

For that you need an oracle outside the zig backend, and there is one: the
**codex-zig-ladder** compiles the same chapters through the seed on bare
metal and requires byte agreement across fourteen rungs. That is a
comparison against something that does not share the emitter's mistakes.
This repository does not replace it and cannot.

**Which compiler you built.** Both passes read the same checkout, so the
property is indifferent to which one it was: build from last month's Update,
or from a branch someone is mid-experiment on, and it holds there too. It is
not that any wrongness survives this check — a truncated subject, a chapter
that failed to bundle, an emitter that halts, all show up. It is specifically
that the *identity* of the source is not one of the things being compared,
and identity is exactly what you rely on when quoting a result later.

`generated/PROVENANCE` is the answer to that question and the only one — it
names the checkout, its revision, whether that checkout was dirty, and the
toolchain versions. Read it before quoting a result.

**Breadth over real programs.** The subject is one program, and an unusual
one: a compiler. Constructs a compiler does not use are constructs this
property never exercises. Breadth is the ladder's corpus.

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
