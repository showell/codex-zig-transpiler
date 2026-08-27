# generated/

Nothing here is source. Every file is emitted by `../build.py`, and editing
one is editing something that will be overwritten without warning. The
sources are in `../source/` and in the Cobblestone checkout that
`PROVENANCE` names.

These artifacts are tracked on purpose. The point of this repository is that
you can read the zig the compiler emits for itself without owning an 8 GB box
and forty minutes, and a `.gitignore` entry would take that away.

| file | what it is |
| --- | --- |
| `PROVENANCE` | which checkout, which toolchain, whether the fixed point held |
| `ringplug-source.codex` | the zig emitter bundled as a bootable subject |
| `codexzig-subject.codex` | the compiler + the emitter + the harness, one chapter |
| `codexzig.bare.zig` | what the seed and the ring plug emitted, under QEMU |
| `codexzig.self.zig` | what the binary built from that emitted for the same source |

`codexzig.bare.zig` and `codexzig.self.zig` are supposed to be identical.
That is the fixed point, and it is the one property this repository exists to
hold. When they differ, the diff is the finding.

## local/

Untracked, and the only ignored path in the repository. It holds the things
that are large, binary, or both: the IR text (9 MB), the compiled ring plug,
the CCE payloads, the intake blobs, and the `codexzig` binary itself (28 MB).
All of it is reproducible from what is tracked here plus the named checkout.
