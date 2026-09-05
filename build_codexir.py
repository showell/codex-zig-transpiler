#!/usr/bin/env python3
"""Build codexir: the same compiler, stopping at the IR wire.

    ./build_codexir.py            build if stale, then smoke-test
    ./build_codexir.py --force    rebuild even if it looks current

    codexir < prog.codex 2> prog.ir

codexzig is Codex source in, zig out. codexir is Codex source in, IR out --
`generated/codexzig.ir` as a program you can run, instead of an artifact one
guest produced once.

WHY IT EXISTS. The IR bank at $CODEX_GOLDS was cut by bare metal at an older
Update, so a disagreement with it cannot be attributed: 23 commits and ~3,000
changed compiler lines separate that pin from this checkout, Update 55 among
them. This is a second arm at THIS pin, and a diff against it is about the
host rather than about the calendar.

WHY IT IS CHEAP. build.py needs three guests to reach a first zig, because the
seed emits x86. This needs none: codexzig already exists and is a fixed point,
so the whole chain is on the host --

    codexzig-subject.codex, harness swapped -> codexzig -> zig build-exe

-- about two minutes, against build.py's seven-guest run. That is the only
reason this belongs beside build.py rather than in codex-qemu.

THE SUBJECT IS build.py'S OWN, WITH ONE CHAPTER REPLACED. Not a second chapter
list: `source/bundle_codexzig.ps1` names about ninety chapters with reasons
attached to a dozen of them, and a copy of that list is a fork that drifts in
silence. This takes `generated/codexzig-subject.codex` -- the same bytes the
fixed point was measured on -- drops its trailing harness chapter and appends
`source/CodexIrHarness.codex`. The zig emitter chapters ride along unused,
which costs binary size and nothing else.

**THE EFFECT LABELS IN THIS TOOL'S IR ARE WRONG, and that is not this tool.**
`cx_address_of` answers 0 for any Text below the heap base -- every string
literal in the emitted program -- and `mcopy-name-fresh` keys a Name by
`cons-mix 701 (address-of tv)` and nothing else, so every literal-named Name
collides on one key and the first one copied is adopted by all of them. One
program whose six labels are Device.Mmio x3, Device.Port x2 and Console.Write
x1 on bare metal and on the Rust interpreter comes out Device.Mmio x6 here. It
is in the shipped -cdx path too, so it is the plug and not the harness. Until
that is fixed, an effect row out of this tool is not evidence.
"""

import argparse
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE / 'source'
GEN = HERE / 'generated'
LOCAL = GEN / 'local'

SUBJECT = GEN / 'codexzig-subject.codex'
CODEXZIG = LOCAL / 'codexzig'
HARNESS = SOURCE / 'CodexIrHarness.codex'
IR_SUBJECT = GEN / 'codexir-subject.codex'
IR_ZIG = GEN / 'codexir.native.zig'
CODEXIR = LOCAL / 'codexir'

# The chapter build.py's harness contributes, and the one this replaces it with.
ZIG_HARNESS_HEADER = 'Chapter: Parsmi--CodexZigHarness'

_t0 = time.time()


def say(msg=''):
    print(f'[{time.time() - _t0:6.1f}s] {msg}', flush=True)


def die(msg):
    say(f'FAILED: {msg}')
    raise SystemExit(1)


def swap_harness():
    """The transpiler subject with its last chapter replaced.

    The split is on the harness chapter's own header line, and it must appear
    exactly once: a subject carrying two of them, or none, is not the subject
    this expects and guessing which to cut would produce a plausible file that
    is not the fixed point's.
    """
    text = SUBJECT.read_text()
    if text.count(ZIG_HARNESS_HEADER) != 1:
        die(f'{SUBJECT.name} carries {text.count(ZIG_HARNESS_HEADER)} of '
            f'{ZIG_HARNESS_HEADER!r}; expected exactly one')
    body = text[:text.index(ZIG_HARNESS_HEADER)]
    IR_SUBJECT.write_text(body + HARNESS.read_text())
    say(f'{IR_SUBJECT.name}: {IR_SUBJECT.stat().st_size} bytes '
        f'({len(body)} carried, {IR_SUBJECT.stat().st_size - len(body)} new)')


def transpile():
    """codexzig reading the swapped subject. Output is on stderr; see the
    harness's own note on why."""
    r = subprocess.run([str(CODEXZIG)], stdin=IR_SUBJECT.open('rb'),
                       capture_output=True)
    IR_ZIG.write_bytes(r.stderr)
    diag = r.stdout.decode('utf-8', 'replace')
    for line in diag.strip().splitlines():
        if 'CDX3005' not in line:          # the builtin-shadow warnings, all 8
            say('  | ' + line[:110])
    zig = IR_ZIG.read_text(errors='replace')
    for line in zig.splitlines():
        if line.startswith('CODEGEN-HALTED:'):
            die(f'codexzig refused the subject -- {line}')
    if 'pub fn main' not in zig:
        die('the emitted zig carries no `pub fn main`; this is not a transpile')
    allowed = {l.strip() for l in
               (SOURCE / 'prelude-comptime-guards.txt').read_text().splitlines()
               if l.strip() and not l.startswith('#')}
    import re
    bad = {m for m in re.findall(r'@compileError\("[^"]*"\)', zig) if m not in allowed}
    if bad:
        die(f'the plug could not translate a construct: {sorted(bad)[:3]}')
    say(f'{IR_ZIG.name}: {IR_ZIG.stat().st_size} bytes')


def build_exe():
    CODEXIR.unlink(missing_ok=True)
    r = subprocess.run(['zig', 'build-exe', str(IR_ZIG), f'-femit-bin={CODEXIR}'],
                       capture_output=True, text=True, cwd=str(LOCAL))
    if r.returncode != 0 or not CODEXIR.is_file():
        for line in (r.stderr or r.stdout).strip().splitlines()[:25]:
            say('  | ' + line)
        die('zig build-exe')
    say(f'{CODEXIR.name}: {CODEXIR.stat().st_size} bytes')


def smoke():
    """A program small enough to read, checked for the two things a broken
    build gets wrong: it must emit a chapter, and it must REFUSE bad input.

    The refusal half is not decoration. A tool that emits for anything looks
    exactly like one that works until somebody feeds it a program with a
    mistake in it, which is the first thing anybody does.
    """
    good = 'Chapter: T\n\nSection: E\n\n  opening : [Console] Nothing = act\n    print-line-uni "hi"\n  end\n'
    r = subprocess.run([str(CODEXIR)], input=good, capture_output=True, text=True)
    if not r.stderr.startswith('(chapter "Program"'):
        die(f'smoke: no chapter emitted; got {r.stderr[:120]!r}')
    if '(def "opening"' not in r.stderr:
        die('smoke: the chapter carries no opening')
    say(f'smoke: {len(r.stderr)} bytes of IR for a six-line program')

    bad = 'Chapter: T\n\nSection: E\n\n  opening : [Console] Nothing = act\n    print-line-uni (no-such-function 1)\n  end\n'
    r = subprocess.run([str(CODEXIR)], input=bad, capture_output=True, text=True)
    if 'CODEGEN-HALTED' not in r.stderr:
        die('smoke: a program naming an undefined function was NOT refused')
    say('smoke: an undefined name is refused, as the driver refuses it')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    for p in (SUBJECT, CODEXZIG, HARNESS):
        if not p.exists():
            die(f'{p} is missing; run ./build.py first')
    fresh = (CODEXIR.is_file()
             and CODEXIR.stat().st_mtime > max(SUBJECT.stat().st_mtime,
                                               HARNESS.stat().st_mtime,
                                               CODEXZIG.stat().st_mtime))
    if fresh and not args.force:
        say(f'{CODEXIR.name} is newer than its inputs; --force to rebuild')
    else:
        swap_harness()
        transpile()
        build_exe()
    smoke()
    say('codexir OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
