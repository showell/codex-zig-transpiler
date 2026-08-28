# generated/

Nothing here is source. Every file is emitted by `../build.py`, and editing
one is editing something that will be overwritten without warning. The
sources are in `../source/` and in the Cobblestone checkout that
`PROVENANCE` names.

**These files are the point of the repository, not a side effect of it.** They
are what a Codex compiler emits when it is asked to produce zig, and they are
checked in so you can read them without an 8 GB box and seven minutes. Start
with `arith.zig`.

These artifacts are tracked on purpose. The point of this repository is that
you can read the zig the compiler emits for itself -- and build a working
transpiler out of it, `zig build-exe generated/codexzig.qemu.zig`, two
seconds -- without owning an 8 GB box and seven minutes.

The 28 MB executable is NOT tracked, and that is the same argument pointed
the other way: the zig is here, so the binary is two seconds away, and a
blob that large which zig does not even build reproducibly is not worth
carrying to save them.

| file | size | what it is |
| --- | --- | --- |
| `PROVENANCE` | | which checkout, which toolchain, whether the fixed point held |
| `ringplug-source.codex` | 300 KB | the zig emitter bundled as a bootable subject |
| `ringplug.cdx` | 400 KB | that subject compiled by the seed: the emitter as a kernel |
| `codexzig-subject.codex` | 2.9 MB | the compiler + the emitter + the harness, one chapter |
| `codexzig.ir` | 9.9 MB | the seed's IR for that subject, and the ring plug's input |
| `codexzig.qemu.zig` | 2.3 MB | pass 1 — the emitter running under QEMU |
| `codexzig.native.zig` | 2.3 MB | pass 2 — the emitter running as the binary built from pass 1 |
| `*.diags` | | what the compiler said while producing each of the above |
| `intake/*.blob` | | see below |

`arith.zig` is the one to read first if you want to see what this emitter
produces. It is 40 KB rather than 2.3 MB, it is a program you can hold in your
head, and the build compiles and runs it every time and checks all nine lines
of its output.

`codexzig.qemu.zig` and `codexzig.native.zig` are supposed to be identical:
the emitter emits the same bytes for its own source whether it runs on bare
metal or as a native binary. That is the fixed point, and it is the one
property this repository exists to hold. When they differ, the diff is the
finding.

## intake/

The exact bytes each guest consumed. A blob is the file above it plus a
**mode line** plus a terminator, and the mode line is the instruction:

```
CDX map             the seed answers with a bootable x86 binary
IR-CCE decks=172    the same seed, the same source, answers with IR text
RING zig            the ring plug answers with zig
```

Most of a blob duplicates a file already tracked here, which is the argument
against keeping it. The argument for keeping it won: this is what was
*actually* transpiled, and the mode line -- the part that decides what the
compile even means, `decks=172` included -- appears nowhere else in the
repository. `PROVENANCE` lists all three so the instruction can be read
without opening a 9 MB file.

Blobs are written only when their content changes, so a warm build does not
churn them.

## What reproduces and what does not

**Bare metal reproduces.** The seed, handed the same blob, emits the same
bytes: `ringplug.cdx` rebuilt from scratch is byte-identical to the one
already here, and `codexzig.qemu.zig` has come out the same across every
build. So the QEMU half of this pipeline is a function of its input.

**`zig build-exe` does not**, and that is zig's.

`zig build-exe` does not emit the same bytes twice. Measured here, three
builds from one unchanged `codexzig.qemu.zig`, seconds apart:

```
28307746 bytes  sha 460632e0...
28311842 bytes  sha b92c7b88...
28307746 bytes  sha 9b421505...
```

The size alternates between two values and the hash differs every time, and
`--build-id=none` does not change that -- it looks like non-deterministic
ordering in zig's own codegen, not anything this repository controls. Note
which half of the toolchain this is: the compiler running on bare metal
under emulation is the reproducible one.

Two consequences worth knowing:

- **The binary is not tracked, and is built once locally.** It lands in
  `local/codexzig`. Rebuilding only produces a different 28 MB blob that is
  not better in any way anyone can name, so stage 6 skips even under
  `--force`; delete it to force one. The reproducible artifacts are
  `PROVENANCE` and the two `.zig` files.
- **It does not threaten the fixed point.** That comparison is over zig text,
  not binaries, and it has held across builds whose binaries differed. The
  emitter's behaviour is deterministic even where its executable is not --
  which is worth saying out loud, because it is the stronger claim.

## Why codexzig.ir is here when the round trip is in-memory

Both are true, and they are different arms.

Inside `codexzig` the IR never touches a file: the harness emits IR text and
parses it straight back with a `let`, in memory. That round trip is
deliberate -- `docs/the-pipeline.md` says why a direct hand-off emits zig
that does not compile.

`codexzig.ir` belongs to pass 1. Getting zig out under QEMU takes two
separate guests -- the seed, then the ring plug -- and a file is how the IR
gets from the first to the second. So the artifact here is the pipeline's
intermediate, not the program's.

That both passes emit the same bytes, one having put its IR through a file
and the other through a `let`, is the fixed point.

## local/

Untracked, and the only ignored path in the repository. It holds pure
scratch and one product: the `codexzig` executable, the ring's staged first
megabyte (a duplicate of the blob's own first megabyte, because QEMU's loader
takes a file and not a slice), the CCE payload before decoding, the guest's
symbol maps, zig's build cache, and the fingerprint files that let a stage
skip when its inputs have not moved.
