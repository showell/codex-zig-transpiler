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
reason this belongs beside build.py rather than in cobblestone-qemu.

THE SUBJECT IS build.py'S OWN, WITH ONE CHAPTER REPLACED. Not a second chapter
list: `source/bundle_codexzig.ps1` names about ninety chapters with reasons
attached to a dozen of them, and a copy of that list is a fork that drifts in
silence. This takes `generated/codexzig-subject.codex` -- the same bytes the
fixed point was measured on -- drops its trailing harness chapter and appends
`source/CodexIrHarness.codex`. The zig emitter chapters ride along unused,
which costs binary size and nothing else.
"""

import argparse
import hashlib
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

# **THE SECOND ORACLE, BUILT BY THE SAME CHAIN AND NOT BY A COPY OF IT.**
# `codexcheck` stops one phase earlier than codexir, where the types are
# decided. Only the harness chapter and the output names differ, so it rides
# this script rather than forking it -- the argument `bundle.rs` makes about
# second bundlers applies exactly: a second build chain nobody compares is
# worse than one, because it is a second thing to keep in step with no signal
# that it has drifted.
CHECK_HARNESS = SOURCE / 'CheckHarness.codex'
CHECK_SUBJECT = GEN / 'codexcheck-subject.codex'
CHECK_ZIG = GEN / 'codexcheck.native.zig'
CODEXCHECK = LOCAL / 'codexcheck'

# The chapter build.py's harness contributes, and the one this replaces it with.
ZIG_HARNESS_HEADER = 'Chapter: Parsmi--CodexZigHarness'

_t0 = time.time()


def say(msg=''):
    print(f'[{time.time() - _t0:6.1f}s] {msg}', flush=True)


def die(msg):
    say(f'FAILED: {msg}')
    raise SystemExit(1)


def swap_harness(harness, subject_out):
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
    subject_out.write_text(body + harness.read_text())
    say(f'{subject_out.name}: {subject_out.stat().st_size} bytes '
        f'({len(body)} carried, {subject_out.stat().st_size - len(body)} new)')


def transpile(subject_in, zig_out):
    """codexzig reading the swapped subject. Output is on stderr; see the
    harness's own note on why."""
    r = subprocess.run([str(CODEXZIG)], stdin=subject_in.open('rb'),
                       capture_output=True)
    zig_out.write_bytes(r.stderr)
    diag = r.stdout.decode('utf-8', 'replace')
    # **CDX3005 IS NOT NOISE, AND FILTERING IT COST AN AFTERNOON.** It says a
    # definition shadows a builtin, and its own text says why that matters:
    # "a shadow that computes the same result more slowly is the failure mode
    # that has actually cost time here". Suppressed, it hid that this bundle
    # defines its own `text-contains` -- so a guard added to the hottest
    # comparison in cite resolution, believing it called a native builtin,
    # called a Codex substring search instead and made a self-compile
    # dramatically slower. Counted rather than dropped: eight lines of the same
    # shape are noise, and the NUMBER changing is not.
    shadows = [l for l in diag.strip().splitlines() if 'CDX3005' in l]
    for line in diag.strip().splitlines():
        if 'CDX3005' not in line:
            say('  | ' + line[:110])
    if shadows:
        names = sorted({l.split("'")[1] for l in shadows if "'" in l})
        say(f'  | {len(shadows)} builtin shadows (CDX3005): ' + ' '.join(names))
    zig = zig_out.read_text(errors='replace')
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
    say(f'{zig_out.name}: {zig_out.stat().st_size} bytes')


def build_exe(zig_in, bin_out):
    bin_out.unlink(missing_ok=True)
    r = subprocess.run(['zig', 'build-exe', str(zig_in), f'-femit-bin={bin_out}'],
                       capture_output=True, text=True, cwd=str(LOCAL))
    if r.returncode != 0 or not bin_out.is_file():
        for line in (r.stderr or r.stdout).strip().splitlines()[:25]:
            say('  | ' + line)
        die('zig build-exe')
    say(f'{bin_out.name}: {bin_out.stat().st_size} bytes')


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


def smoke_check():
    """The check oracle answers for a unit, and refuses a bad one.

    The number that matters is `next-row-id`, which is why it is asserted here
    rather than merely printed: it is the counter behind an effectful builtin's
    row variable, and a build that answered 0 for it would look fine in every
    other line of the dump.
    """
    good = ('Chapter: T\n\nSection: E\n\n  opening : [Console] Nothing = act\n'
            '    print-line-uni "hi"\n  end\n')
    r = subprocess.run([str(CODEXCHECK)], input=good, capture_output=True, text=True)
    if not r.stderr.startswith('--- check ---'):
        die(f'smoke: no check dump; got {r.stderr[:120]!r}')
    rows = dict(l.split(None, 1) for l in r.stderr.splitlines() if ' ' in l and not l.startswith('tb '))
    if 'next-row-id' not in rows or int(rows['next-row-id']) <= 0:
        die(f'smoke: next-row-id absent or zero -- {rows.get("next-row-id")!r}')
    say(f'smoke: check-errors {rows.get("check-errors")}, '
        f'type-bindings {rows.get("type-bindings")}, next-row-id {rows["next-row-id"]}')

    bad = ('Chapter: T\n\nSection: E\n\n  opening : [Console] Nothing = act\n'
           '    print-line-uni (no-such-function 1)\n  end\n')
    r = subprocess.run([str(CODEXCHECK)], input=bad, capture_output=True, text=True)
    if 'CODEGEN-HALTED' not in r.stderr:
        die('smoke: a program naming an undefined function was NOT refused')
    say('smoke: an undefined name is refused, as the driver refuses it')


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def fingerprint_of(inputs):
    return '\n'.join(sha(i) for i in inputs)


def fingerprint(binary):
    fp = LOCAL / (binary.name + '.fp')
    return fp.read_text().strip() if fp.is_file() else None


def stamp(binary, inputs):
    (LOCAL / (binary.name + '.fp')).write_text(fingerprint_of(inputs) + '\n')


def receipt():
    """What these oracles were built from, since nothing else records it.

    The Rust arm is graded against codexir and codexcheck and ports from
    codexcheck-subject.codex, so the pin behind them decides what a Rust gate
    means. They are gitignored and carry no stamp of their own, which leaves
    mtime as the only evidence -- and mtime says when, never what.

    The pin is not read from the environment: these are built from build.py's
    subject, so the checkout that answers for them is the one build.py already
    recorded. Taking it from generated/PROVENANCE keeps the two receipts from
    being able to disagree.
    """
    pin = ['(no generated/PROVENANCE: run ./build.py first)']
    prov = GEN / 'PROVENANCE'
    if prov.is_file():
        lines = prov.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith('checkout'):
                pin = [line] + lines[i + 1:i + 2]
                break
    (GEN / 'PROVENANCE.oracles').write_text(
        'codexir and codexcheck -- the oracles rust-codex-compiler is graded\n'
        'against, and codexcheck-subject.codex, the source it ports from.\n'
        'Emitted by build_codexir.py, not by build.py.\n\n'
        'built      ' + time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) + '\n'
        + '\n'.join(pin) + '\n'
        f'subject    {sha(SUBJECT)[:16]}  {SUBJECT.name}\n'
        f'codexzig   {sha(CODEXZIG)[:16]}  the transpiler that emitted them\n')
    say(f'wrote {(GEN / "PROVENANCE.oracles").name}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    for p in (SUBJECT, CODEXZIG, HARNESS, CHECK_HARNESS):
        if not p.exists():
            die(f'{p} is missing; run ./build.py first')

    for harness, subject, zig, binary, name in (
            (HARNESS, IR_SUBJECT, IR_ZIG, CODEXIR, 'codexir'),
            (CHECK_HARNESS, CHECK_SUBJECT, CHECK_ZIG, CODEXCHECK, 'codexcheck')):
        head(name) if 'head' in globals() else say(f'==== {name} ====')
        inputs = (SUBJECT, harness, CODEXZIG)
        if binary.is_file() and fingerprint(binary) == fingerprint_of(inputs) \
                and not args.force:
            say(f'{binary.name} is the answer for these inputs; --force to rebuild')
        else:
            swap_harness(harness, subject)
            transpile(subject, zig)
            build_exe(zig, binary)
            stamp(binary, inputs)
        smoke() if name == 'codexir' else smoke_check()
        say(f'{name} OK')
    receipt()
    return 0


if __name__ == '__main__':
    sys.exit(main())
