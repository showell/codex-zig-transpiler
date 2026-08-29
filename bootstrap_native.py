#!/usr/bin/env python3
"""Rebuild codexzig from the checkout WITHOUT QEMU, by self-hosting.

build.py is the release path and costs three guests, because the seed compiler
emits x86 and there has to be a first zig somehow. Once a working codexzig
exists that is no longer true: it is itself a Codex-to-zig transpiler, so it can
compile the NEXT emitter's source. This is the iteration path for plug work --
edit ZigEmitter.codex, run this, and have a binary carrying the change in about
three minutes with no guest and no lock on the box.

WHAT THIS DOES NOT DO is check the fixed point. That is build.py's stage 8 and
it needs the QEMU leg, because the whole point of it is that pass 1 came from an
INDEPENDENT implementation -- the emitter compiled to a bootable kernel -- and
not from the binary under test. Nothing self-hosted can supply that.

What it checks instead is CONVERGENCE, which is the part reachable from here:

    codexzig(n)    transpiles the subject  ->  candidate.zig
    build          candidate.zig           ->  codexzig(n+1)
    codexzig(n+1)  transpiles the subject  ->  again.zig
    require        candidate.zig == again.zig

The iteration matters and is not ceremony. When a change alters how the emitter
emits, candidate.zig was produced by the OLD emitter and again.zig by the NEW
one, so they differ LEGITIMATELY on the first round -- as the x-to-v parameter
rename did, in exactly the ten lines it touched. Demanding agreement on step one
would have called that a failure. So this iterates to a fixed point instead:
immediate for a change that does not affect the emitter's own output, one extra
round for a change that does. A change that never converges is a real finding.

EVERY FLAG COMES FROM build.py. This imports its bundle(), build_exe() and
self_transpile() rather than restating them, because restating them is how
`-O ReleaseFast` crept into a hand-run bootstrap once and produced a 15.9 MB
binary where build.py's Debug default produces 27.8 MB -- two builds that are
not comparable, discovered only because their timings differed.

Run ./build.py --force before anything ships: this path never proves the QEMU
arm agrees, and PROVENANCE is written by that one.
"""

import pathlib
import shutil
import sys

import build as B

MAX_ROUNDS = 4


def main():
    if not B.CODEXZIG.is_file():
        raise SystemExit(f'no codexzig at {B.CODEXZIG}; run ./build.py first -- '
                         'self-hosting needs a predecessor')

    root = B.cobblestone.root()
    rev = B.cobblestone.revision(root)
    B.head('bootstrap (no guest)')
    B.say(f'checkout   {root}')
    B.say(f'           {rev}')
    B.say(f'from       {B.CODEXZIG.name}  {B.CODEXZIG.stat().st_size} bytes')

    B.head('bundle the transpiler')
    B.bundle(B.SOURCE / 'bundle_codexzig.ps1', B.SUBJECT)

    work = B.LOCAL / 'bootstrap'
    work.mkdir(exist_ok=True)
    current = B.CODEXZIG

    for rnd in range(1, MAX_ROUNDS + 1):
        B.head(f'round {rnd}: transpile, build, re-transpile')
        cand = work / f'cand{rnd}.zig'
        B.self_transpile(B.SUBJECT, cand, current)
        B.refuse_bad_transpile(cand, f'round {rnd} candidate')
        nxt = work / f'codexzig{rnd}'
        B.build_exe(cand, nxt)
        again = work / f'again{rnd}.zig'
        B.self_transpile(B.SUBJECT, again, nxt)
        B.refuse_bad_transpile(again, f'round {rnd} confirmation')

        if cand.read_bytes() == again.read_bytes():
            B.say(f'CONVERGED after {rnd} round(s): {cand.stat().st_size} bytes, '
                  'the binary reproduces the source it was built from')
            shutil.copy2(nxt, B.CODEXZIG)
            B.stamp(B.CODEXZIG, [cand])
            shutil.copy2(cand, B.NATIVE_ZIG)
            B.say(f'installed {B.CODEXZIG}')
            B.say('NOTE: the fixed point is NOT checked here. Run ./build.py '
                  '--force before this goes anywhere.')
            return 0

        B.say(f'not yet converged ({cand.name} != {again.name}); '
              'the emitter changed its own output, iterating')
        current = nxt

    B.die(f'no fixed point after {MAX_ROUNDS} rounds -- the emitter does not '
          'converge on its own source, which is a finding, not a flake')


if __name__ == '__main__':
    sys.exit(main())
