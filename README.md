# codex-zig-transpiler

`codexzig` is one program. Codex source in, zig out.

```
codexzig < prog.codex 2> prog.zig
```

That is the whole artifact. This repository builds it, and checks the one
property that makes it trustworthy.

## The fixed point

One loop:

```
blob -> QEMU -> zig -> exe -> (the same source again) -> zig -> diff
```

`codexzig` is built the long way, because the seed compiler emits x86 and not
zig: the seed compiles the transpiler's own source to IR under QEMU, the zig
emitter — itself compiled to a bootable kernel — turns that IR into zig, and
`zig build-exe` turns the zig into a binary.

Then that binary is handed the same source, and **must emit the same bytes.**

```
generated/codexzig.qemu.zig     pass 1 — the emitter running under QEMU
generated/codexzig.native.zig   pass 2 — the emitter running as the binary pass 1 built
                                -> byte-identical, or it is a finding
```

Said as a property: *the emitter emits the same bytes for its own source
whether it runs on bare metal or as a native binary.* That single comparison
exercises every chapter of the compiler and the whole emitter, and it costs a
minute against the seven the build already spent. It is not a test suite and
not a comparison against a reference implementation; it is an invariant, and
it either holds or it does not.

It is not a proof of correctness — but it is a demanding property, not a
weak one, and it is worth being precise about which.

**Holding at all takes a working compiler and a working zig plug.** The two
passes run the same `ZigEmitter` source through *different backends*: pass 1's
emitter is compiled by the seed to x86 and runs bare metal, while pass 2's
emitter is compiled by the zig plug to zig and then built by zig. So a plug
defect that changes how the emitter itself behaves lands here as a difference.
Editing the plug breaks this easily, which is the point. This repository has
only ever seen it hold at the one revision `generated/PROVENANCE` names, and
there is no reason to assume it held at an arbitrary earlier Update.

**What slips through is being wrong consistently.** Both passes use the same
plug, so an edit that changes the emitted zig the *same way* in both holds the
fixed point while changing every byte of the output. The property says the
emitter agrees with itself across two backends; it does not say the answer is
right. For that you need an oracle outside the zig arm — see the ladder,
below.

**And it cannot tell you which compiler you built.** Two different healthy
revisions each hold their own fixed point, with different bytes, so agreement
never identifies the source. That is a blind spot you can walk into by
exporting one variable, which is why every artifact is stamped:
`generated/PROVENANCE`.

Pass 2 is handed the same *source* as pass 1, not the same blob bytes. A blob
is that source wrapped in the guest's intake envelope, and the envelope is
what makes QEMU answer with IR text rather than an x86 binary; the native
binary reads plain Codex on stdin and would choke on the mode line.

## Requirements

| | | why |
| --- | --- | --- |
| `$COBBLESTONE_ROOT` | a [Cobblestone](https://github.com/damiant3/Cobblestone) checkout | every chapter is read from here; nothing is vendored |
| `qemu-system-x86_64` | any recent | the seed and the emitter run on bare metal |
| `zig` | 0.16.0 | builds the emitted zig into the binary |
| `pwsh` | at `~/.local/pwsh/pwsh` | the checkout's own bundler is PowerShell |
| a quiet box | ~4 GB free RAM | see Memory below; nothing here takes a lock, and two guests thrash rather than fail |
| time | ~7 min cold, 3 s warm | measured: 3 guests in 366s, zig 2s, pass 2 58s; a warm run skips all of it |

`$COBBLESTONE_ROOT` is deliberately **not** `$CODEX_ROOT`. That one belongs
to the codex-zig-ladder, which moves its checkout's HEAD between branches and
pinned Updates all day as part of how it works. Point this at a checkout that
stays where it is put:

```
git -C <cobblestone> worktree add --detach ~/showell_repos/cobblestone-pin <rev>
```

`CODEX_MEM_MB` caps the guest (default 3072; the seed dies silently above
it on an 8 GB box). `CODEX_ACCEL` selects the accelerator (default `tcg`).

## Building

```
export COBBLESTONE_ROOT=~/showell_repos/cobblestone-pin
./build.py                 # build what is stale, then check the fixed point
./build.py --force         # rebuild every stage, guests included
./build.py --check-only    # check the fixed point against what is on disk
```

## Memory

This is the requirement most likely to bite, because **a guest that runs out
of room does not say so.** It parks in `hlt` with nothing on the wire, having
already done minutes of real work, and looks identical to a slow compile. The
only evidence is its peak resident size beside its cap, which `build.py`
prints per stage and records in `generated/PROVENANCE`.

What each stage actually touches of the 3072 MB cap, measured (`build.py`
prints it per stage and records it in `generated/PROVENANCE`):

| stage | | peak |
| --- | --- | --- |
| 2 | compile the ring plug — 304 KB in | 568 MB |
| 4 | compile the transpiler — 2.9 MB in, 9.9 MB of IR out | **2454 MB** |
| 5 | transpile it — 9.9 MB of IR in, 2.3 MB of zig out | 916 MB |

| | |
| --- | --- |
| guest cap | 3072 MB (`CODEX_MEM_MB`); stage 4 uses 80% of it |
| host, to build | ~4 GB free — one guest at a time, plus zig |
| host, to *run* `codexzig` | **3472 MB** on its own 2.9 MB source |

Stage 4 is the binding one and its margin is thinner than it looks: 618 MB.

That last row is a real requirement and not a footnote. Transpiling a large
program is expensive because the allocator underneath is a bump allocator
that never frees, so peak demand is the **sum** of every phase's working set
rather than the largest. `codexzig` on its own source peaks at 3,553,024 kB —
and note that 2454 + 916 = 3370 lands right beside it, which is the same fact
seen from the other side.

**The guest cannot simply be made bigger.** The boot stub sets its stack from
a RAM-size cell and triple-faults on a value it cannot use: 3072 MB boots,
3584 MB and 3968 MB both die before READY, with QEMU exiting before a byte of
the banner. `guest.py` refuses a size at or above 4096 MB outright, because
the cell is four bytes wide and 5120 MB silently becomes 1024.

### Why three guests and not two

The obvious simplification is to put the compiler and the emitter in one
kernel, so the bootstrap becomes *compile codexzig to a kernel, then use it to
transpile codexzig*. That kernel was built and it is real — 1,971,047 bytes,
compiled clean.

It does not fit, and the numbers leave no room to argue:

```
guest at 3072 MB    boots, and runs every stage of the real build
guest at 3584 MB    dies before READY
guest at 3968 MB    dies before READY
the workload wants  3472 MB, measured natively
```

Merged, one guest holds the source, the AST, the IR *and* the emitted text at
once, over an allocator that never frees — so its peak is the SUM of every
phase's working set. The boot stub triple-faults on a RAM size it cannot use,
putting the ceiling between 3072 and 3584, and the merged workload wants
3472. **There is no guest size that is both bootable and big enough.**

Splitting the front end from the emitter splits that peak across two
processes, and that is what the third guest buys. It is not a historical
accident, even though that is how it got here.

## Just want a working transpiler?

You do not need any of the above. `generated/codexzig.qemu.zig` is in this
repository, and it is the whole program:

```
zig build-exe generated/codexzig.qemu.zig -femit-bin=codexzig
./codexzig < prog.codex 2> prog.zig
```

Two seconds, no QEMU, no PowerShell, no checkout. That is why the repository
tracks the zig and not the 28 MB executable — which zig does not build
reproducibly anyway.

`build.py` prints its provenance before it spends anything, names each stage
as it runs, and marks the three that start a guest. It exits non-zero if the
fixed point breaks.

## What is here

```
build.py        the driver: eight stages, three of them guests
guest.py        bare metal -- QEMU, the serial ring, the gdbstub
cobblestone.py  where the sister checkout is, and which one it is
cce.py          host-side decode of the compressed encoding the guest answers in
source/         the parts that are ours: two chapter lists and three Codex chapters
generated/      everything the build emits, tracked, including the binary
                and the exact blobs bare metal ate -- see generated/README.md
docs/           how the pipeline works, and what the fixed point does not cover
```

Deliberately absent: any Codex source from Cobblestone (read from
`$COBBLESTONE_ROOT`), and the two-process `codexir | zigemit` pipeline that
`codexzig` merges (it lives in the ladder, which is where the questions it
answers are asked).

## Sister repos

- **[Cobblestone](https://github.com/damiant3/Cobblestone)** — Damian's
  self-hosted language, compiler and OS. The compiler, the zig plug, and the
  seed all come from here. This repository is downstream of it and vendors
  none of it.
- **codex-zig-ladder** — the verification ladder. It compiles the compiler
  two ways and requires the answers to agree, across fourteen rungs, against
  bare metal. That is a *comparison* machine, and it is where defects in the
  zig plug get found and reported. This repository holds one *invariant*, and
  is deliberately much smaller.

The distinction matters when deciding where work goes. If the question is
"does the zig backend agree with bare metal", it belongs in the ladder. If
the question is "does this one program still reproduce itself", it belongs
here.
