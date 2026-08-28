#!/usr/bin/env python3
"""Can the bootstrap be two guests instead of three? NO -- it does not fit.

SETTLED, and kept because the measurement is what justifies the three-guest
shape. The merged kernel BUILDS and is correct as far as it gets; what stops
it is memory, and the ceiling is not negotiable:

    guest at 3072 MB    boots, and runs every stage of the real build
    guest at 3584 MB    dies before READY
    guest at 3968 MB    dies before READY
    the workload wants  3472 MB (3,553,024 kB), measured natively

The boot stub triple-faults on a RAM size it cannot use, so the ceiling sits
between 3072 and 3584 while the merged workload wants 3472. There is no value
that is both bootable and big enough. Running this now gets as far as GUEST 2
and dies there on purpose.

Two of the three failures along the way were mistakes rather than results,
and both are recorded where they happened: `CDX map` gives a 2.9 MB unit deck
scale 100 because derive-deck-scale clamps there (MODE_CDX_DECKS below), and
read-serial-cce converts nothing, so feeding it plain source yields 37,688
bytes of bare prelude rather than an error (CodexZigRingHarness.codex).

--- the original question ---


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

# The kernel reads its unit the way the seed does -- read-file-uni then
# utf8-to-cce -- so the payload is PLAIN UTF-8 source ending in EOT, exactly
# the shape the seed is fed. The mode line is read by read-line, which ends
# on ASCII 10.
MODE_CODEX = b'RING codex\n'

# decks= is a PERCENTAGE scale on every deck reservation, parsed off the mode
# line independently of the base mode (opening.codex:60), and it is why the
# first attempt at this failed. Without the flag the scale is DERIVED from
# unit length -- and derive-deck-scale clamps at 100 (:135), so a 2.9 MB unit
# gets 100 whatever its size. The hosted build asks for 172 explicitly. Plain
# `CDX map` gave the merged kernel 100 and CHECK overflowed its floor
# (CDX9002, measured). 172 is the value already proven against this source.
#
# The three-guest build never hits this because its only `CDX map` compile is
# the 304 KB ring plug, which fits inside 100 comfortably.
MODE_CDX_DECKS = b'CDX map decks=172\n'

# Guest 2 runs the whole compiler AND the emitter in one address space, over a
# bump allocator that never frees, so its peak is the SUM of every phase's
# working set rather than the largest. Measured: the native binary doing this
# exact job peaks at 3.39 GB, so the 3072 MB default cannot hold it -- the
# first attempt climbed to 2.49 GB and parked in hlt with nothing on the wire,
# which is how this guest fails rather than saying so.
#
# That is the real cost of the two-guest shape, and it is what the three-guest
# one buys: splitting the front end from the emitter splits the peak across two
# processes. Guest 1 is only a compile and stays at the default.
#
# 3968 and not more: the guest reads its RAM size from a FOUR-BYTE cell, so
# 4096 writes zero and 5120 writes 1024. An attempt at 5120 died at 666 MB
# looking exactly like the shortage it was meant to cure. 3968 MB = 0xF8000000
# is the largest size this mechanism can actually express, and the workload
# wants 3.4 GB, so this is the whole margin there is.
GUEST2_MEM_MB = 3584

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
    guest.wrap(RING_SUBJECT, MODE_CDX_DECKS, b'\x04', RING_BLOB)
    fp = OUT / 'codexzig-ring.cdx.fp'
    want = build.sha(RING_BLOB) + '\n' + build.sha(seed)
    if RING_CDX.is_file() and fp.is_file() and fp.read_text().strip() == want:
        say(f'kernel already answers this blob -- not recompiling '
            f'({RING_CDX.stat().st_size} bytes)')
    else:
        RING_CDX.unlink(missing_ok=True)
        if not guest.compile_ring(RING_BLOB, RING_CDX, seed, OUT, say=say):
            say('')
            say('GUEST 1 FAILED. If it is CDX9002, the deck scale is the knob:')
            say(f'  mode line was {MODE_CDX_DECKS!r}')
            raise SystemExit(1)
        fp.write_text(want + '\n')
        say(f'kernel: {RING_CDX.stat().st_size} bytes')

    say('')
    say(f'==== GUEST 2: that kernel transpiles the hosted subject '
        f'({GUEST2_MEM_MB} MB)')
    guest.wrap(build.SUBJECT, MODE_CODEX, b'\x04', FEED_BLOB)
    PAYLOAD.unlink(missing_ok=True)
    if not guest.compile_ring(FEED_BLOB, PAYLOAD, RING_CDX, OUT,
                              mem_mb=GUEST2_MEM_MB, say=say):
        say('')
        say('GUEST 2 FAILED. A guest that runs out of room does not say so --')
        say('it parks in hlt with nothing on the wire. Check its peak RSS')
        say(f'against the {GUEST2_MEM_MB} MB cap before believing anything else.')
        raise SystemExit(1)
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
