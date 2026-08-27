# generated/

Nothing here is source. Every file is emitted by `../build.py`, and editing
one is editing something that will be overwritten without warning. The
sources are in `../source/` and in the Cobblestone checkout that
`PROVENANCE` names.

These artifacts are tracked on purpose, the binary included. The point of
this repository is that you can read the zig the compiler emits for itself
-- and run the transpiler -- without owning an 8 GB box and forty minutes.

| file | size | what it is |
| --- | --- | --- |
| `PROVENANCE` | | which checkout, which toolchain, whether the fixed point held |
| `ringplug-source.codex` | 300 KB | the zig emitter bundled as a bootable subject |
| `ringplug.cdx` | 400 KB | that subject compiled by the seed: the emitter as a kernel |
| `codexzig-subject.codex` | 2.9 MB | the compiler + the emitter + the harness, one chapter |
| `codexzig.ir` | 9.5 MB | the seed's IR for that subject, and the ring plug's input |
| `codexzig.ir.diags` | | what the compiler said while compiling itself |
| `codexzig.bare.zig` | 2.3 MB | what the seed and the ring plug emitted, under QEMU |
| `codexzig` | 28 MB | that zig, built |
| `codexzig.self.zig` | 2.3 MB | what the binary emits for the same source |

`codexzig.bare.zig` and `codexzig.self.zig` are supposed to be identical.
That is the fixed point, and it is the one property this repository exists to
hold. When they differ, the diff is the finding.

## Why codexzig.ir is here when the transpile is in-memory

Both are true, and they are different arms.

Inside `codexzig` the IR never touches a file: the harness emits IR text and
parses it straight back with a `let`, in memory. That round trip is
deliberate -- `docs/the-pipeline.md` says why a direct hand-off emits zig
that does not compile.

`codexzig.ir` belongs to the *other* arm. The bare-metal path is two separate
QEMU guests -- the seed, then the ring plug -- and a file is how the IR gets
from the first to the second. So the artifact here is the pipeline's
intermediate, not the program's.

That the two arms agree byte-for-byte, one having gone through a file and the
other through a `let`, is the fixed point.

## local/

Untracked, and the only ignored path in the repository. It holds pure
scratch: the intake blobs, the ring's staged first megabyte, the CCE payload
before decoding, zig's build cache, and the fingerprint files that let a
stage skip when its inputs have not moved.
