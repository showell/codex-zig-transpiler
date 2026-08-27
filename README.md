# codex-zig-transpiler

`codexzig` is one program. Codex source in, zig out.

```
codexzig < prog.codex 2> prog.zig
```

That is the whole artifact. This repository builds it, and checks the one
property that makes it trustworthy.

## The fixed point

`codexzig` is built the long way: the seed compiler compiles the transpiler's
own source to IR on bare metal under QEMU, the zig emitter — itself compiled
to a bootable kernel — turns that IR into zig, and `zig build-exe` turns the
zig into a binary.

Then the binary is handed its own source, and **must emit those same bytes.**

```
generated/codexzig.bare.zig   what the seed and the ring plug emitted
generated/codexzig.self.zig   what the binary built from that emits for the same source
                              -> byte-identical, or it is a finding
```

That single comparison exercises every chapter of the compiler and the whole
emitter, and it costs about a minute against the forty the build already
spent. It is not a test suite and it is not a comparison against a reference
implementation; it is an invariant, and it either holds or it does not.

It is also not a guarantee of correctness. The fixed point holds just as well
against the wrong checkout, which is why every artifact is stamped with the
revision it came from — see `generated/PROVENANCE`.

## Requirements

| | | why |
| --- | --- | --- |
| `$COBBLESTONE_ROOT` | a [Cobblestone](https://github.com/damiant3/Cobblestone) checkout | every chapter is read from here; nothing is vendored |
| `qemu-system-x86_64` | any recent | the seed and the emitter run on bare metal |
| `zig` | 0.16.0 | builds the emitted zig into the binary |
| `pwsh` | at `~/.local/pwsh/pwsh` | the checkout's own bundler is PowerShell |
| a quiet box | ~4 GB free RAM | nothing here takes a lock; two 3 GB guests thrash rather than fail |
| time | ~40 min cold, seconds warm | three QEMU guests; stages skip when their inputs have not moved |

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

`build.py` prints its provenance before it spends anything, names each stage
as it runs, and marks the three that start a guest. It exits non-zero if the
fixed point breaks.

## What is here

```
build.py        the driver: eight stages, three of them guests
guest.py        the bare-metal arm -- QEMU, the serial ring, the gdbstub
cobblestone.py  where the sister checkout is, and which one it is
cce.py          host-side decode of the compressed encoding the guest answers in
source/         the parts that are ours: two chapter lists and three Codex chapters
generated/      everything the build emits, tracked -- see generated/README.md
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
"does the zig arm agree with bare metal", it belongs in the ladder. If the
question is "does this one program still reproduce itself", it belongs here.
