#!/usr/bin/env python3
"""Can the bootstrap be two guests instead of three?

Today it is three: compile the emitter to a kernel, compile the transpiler's
source to IR text, run the kernel over that IR. The middle one is the only
step that is obviously necessary, and the outer two exist as a pair -- build
an emitter, then use it.

This tries the shape that collapses them. Put the compiler AND the emitter in
one kernel, reading the serial ring, and the whole bootstrap becomes:

    compile codexzig to a kernel, then use it to transpile codexzig.

    1  codexzig-ring-subject.codex  --seed-->  codexzig-ring.cdx     GUEST
    2  codexzig-ring.cdx  <  codexzig-subject.codex  -->  zig        GUEST

The test is decisive because the answer is already on disk. Guest 2 is handed
the SAME hosted subject the three-guest build transpiles, through the same
emitter in the same order, so its zig must equal generated/codexzig.qemu.zig
byte for byte. Anything else is a finding, not a variation.

The open question is heap, not correctness. One guest now holds the source,
the AST, the IR and the emitted text at once, in a bump allocator that never
frees, and the seed dies silently above CODEX_MEM_MB. If this fails, the
failure mode to expect is a guest that stops consuming or never answers --
not wrong zig.
"""

import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import build
import cobblestone
import guest

HERE = pathlib.Path(__file__).resolve().parent
OUT = build.LOCAL / 'two-guests'

RING_SUBJECT = OUT / 'codexzig-ring-subject.codex'
RING_CDX = OUT / 'codexzig-ring.cdx'
RING_BLOB = OUT / 'codexzig-ring-subject.codex.blob'
FEED_BLOB = OUT / 'codexzig-subject.codex.blob'
PAYLOAD = OUT / 'two-guest.zig.cce'
RESULT_ZIG = OUT / 'codexzig.two-guest.zig'

# read-serial-cce ignores its mode argument (see the checkout's own
# read-serial-rt.codex, which passes "ignored"), so this only has to be a
# line the kernel can consume before the payload starts.
MODE_CODEX = b'RING codex\n'

t0 = time.time()


def say(msg=''):
    print(f'[{time.time() - t0:6.1f}s] {msg}', flush=True)


def main():
    root = cobblestone.root()
    seed = root / 'seed' / 'Codex.cdx'
    OUT.mkdir(parents=True, exist_ok=True)
    say(f'checkout {cobblestone.revision(root)}')
    say(f'guest    accel={guest.ACCEL}  mem={guest.MEM_MB}MB')

    say('')
    say('==== bundle the ring-intake transpiler')
    r = subprocess.run([str(build.PWSH), '-NoProfile', '-File',
                        str(build.SOURCE / 'bundle_codexzig.ps1'),
                        '-OutFile', str(RING_SUBJECT),
                        '-Harness', 'CodexZigRingHarness.codex',
                        '-PlugName', 'codexzig-ring'],
                       capture_output=True, text=True, cwd=str(build.SOURCE))
    if r.returncode != 0 or not RING_SUBJECT.is_file():
        say((r.stdout + r.stderr)[-800:])
        raise SystemExit('bundle failed')
    say(f'{RING_SUBJECT.name}: {RING_SUBJECT.stat().st_size} bytes')

    say('')
    say('==== GUEST 1: seed compiles it to a kernel')
    guest.wrap(RING_SUBJECT, guest.MODE_CDX, b'\x04', RING_BLOB)
    RING_CDX.unlink(missing_ok=True)
    if not guest.compile_ring(RING_BLOB, RING_CDX, seed, OUT, say=say):
        raise SystemExit('GUEST 1 FAILED: the seed could not compile it')
    say(f'kernel: {RING_CDX.stat().st_size} bytes')

    say('')
    say('==== GUEST 2: that kernel transpiles the hosted subject')
    guest.wrap(build.SUBJECT, MODE_CODEX, b'\x00', FEED_BLOB)
    PAYLOAD.unlink(missing_ok=True)
    if not guest.compile_ring(FEED_BLOB, PAYLOAD, RING_CDX, OUT, say=say):
        raise SystemExit('GUEST 2 FAILED: the kernel answered nothing')
    guest.decode_zig(PAYLOAD, RESULT_ZIG, say)

    say('')
    say('==== the verdict')
    want = build.QEMU_ZIG.read_bytes()
    got = RESULT_ZIG.read_bytes()
    say(f'three guests: {len(want)} bytes')
    say(f'two   guests: {len(got)} bytes')
    if got == want:
        say('IDENTICAL -- two guests is enough, and the third was inherited')
        return 0
    say('DIFFER -- this is a finding')
    d = subprocess.run(['diff', str(build.QEMU_ZIG), str(RESULT_ZIG)],
                       capture_output=True, text=True)
    for line in d.stdout.splitlines()[:20]:
        say('  | ' + line)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
