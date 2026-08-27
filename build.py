#!/usr/bin/env python3
"""Build codexzig, and check the fixed point.

    ./build.py                 build what is stale, then check
    ./build.py --force         rebuild every stage, guests included
    ./build.py --check-only    check the fixed point against what is on disk

codexzig is one program: Codex source in, zig out.

    codexzig < prog.codex 2> prog.zig

Getting one costs three guests, because the seed compiler emits x86 and not
zig. The emitter has to be compiled to a bootable kernel first, then fed the
transpiler's own IR, and only then is there a zig source to hand to `zig
build-exe`. Six stages, and the last is the point of the whole exercise:

    1  bundle the ring plug          the emitter, as a subject          host
    2  compile the ring plug         seed -> ringplug.cdx              GUEST
    3  bundle the transpiler         compiler + emitter + harness       host
    4  compile the transpiler        seed -> codexzig.ir               GUEST
    5  transpile it                  ringplug.cdx -> codexzig.bare.zig GUEST
    6  build the binary              zig build-exe                      host
    7  transpile the bundle again    codexzig -> codexzig.self.zig      host
    8  diff 5 against 7              THE FIXED POINT

Stage 8 is the invariant this repository exists for. The binary built the
long way -- through the seed under QEMU, then through the ring plug under
QEMU -- must reproduce, from the same source, the exact bytes that path
produced for it. It exercises every chapter of the compiler and the whole
emitter, and it costs about a minute against the forty the stages above
already spent.

Every artifact lands under generated/ and is stamped with the checkout it
came from -- see generated/PROVENANCE. A build that cannot say which
checkout it measured is not evidence, and the fixed point cannot supply the
difference: it holds just as well against the wrong source.

The checkout is $COBBLESTONE_ROOT, which is deliberately not the ladder's
$CODEX_ROOT. Nothing here takes a lock or checks for other guests; a build
assumes it has the box.
"""

import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import time

import cobblestone

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE / 'source'
GEN = HERE / 'generated'
LOCAL = GEN / 'local'

PWSH = pathlib.Path.home() / '.local' / 'pwsh' / 'pwsh'

RINGPLUG_SRC = GEN / 'ringplug-source.codex'
RINGPLUG_CDX = GEN / 'ringplug.cdx'
SUBJECT = GEN / 'codexzig-subject.codex'
SUBJECT_IR = GEN / 'codexzig.ir'
BARE_ZIG = GEN / 'codexzig.bare.zig'
SELF_ZIG = GEN / 'codexzig.self.zig'
CODEXZIG = GEN / 'codexzig'

_t0 = time.time()


def say(msg=''):
    print(f'[{time.time() - _t0:6.1f}s] {msg}', flush=True)


def head(title):
    say()
    say('=' * 4 + f' {title} ' + '=' * max(4, 62 - len(title)))


def die(msg):
    say(f'FAILED: {msg}')
    raise SystemExit(1)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _fp(out):
    # Fingerprints live in local/ rather than beside the artifact: they are
    # cache control, not provenance. PROVENANCE is provenance.
    return LOCAL / (pathlib.Path(out).name + '.fp')


def fresh(out, inputs, force):
    """Is `out` already the answer for these `inputs`?

    Content, never mtime, and the fingerprint records what it was built
    FROM. A guest costs minutes; re-running one to reach the file already on
    disk is the most expensive way to learn nothing.
    """
    if force:
        return False
    fp = _fp(out)
    if not (pathlib.Path(out).exists() and fp.is_file()):
        return False
    return fp.read_text().strip() == '\n'.join(sha(i) for i in inputs)


def stamp(out, inputs):
    _fp(out).write_text('\n'.join(sha(i) for i in inputs) + '\n')


# ----------------------------------------------------------------- preflight

def preflight():
    """Everything this build needs, checked before anything is spent."""
    head('preflight')
    root = cobblestone.root()
    rev = cobblestone.revision(root)

    seed = root / 'seed' / 'Codex.cdx'
    if not seed.is_file():
        die(f'no seed compiler at {seed}')

    missing = [t for t in ('qemu-system-x86_64', 'zig') if not shutil.which(t)]
    if missing:
        die(f'not on PATH: {", ".join(missing)}')
    if not PWSH.is_file():
        die(f'no pwsh at {PWSH}; the checkout\'s bundler is PowerShell')

    def ver(*cmd):
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.stdout.strip().splitlines()[0] if r.stdout.strip() else '?'

    import guest   # here, so preflight can report before qemu is touched
    lines = [
        f'checkout   {root}',
        f'           {rev}',
        f'seed       {seed.name}  {seed.stat().st_size} bytes',
        f'zig        {ver("zig", "version")}',
        f'qemu       {ver("qemu-system-x86_64", "--version")}',
        f'pwsh       {ver(str(PWSH), "--version")}',
        f'guest      accel={guest.ACCEL}  mem={guest.MEM_MB}MB',
    ]
    for l in lines:
        say(l)
    return root, seed, rev, lines


# -------------------------------------------------------------------- stages

def bundle(script, out, root):
    """Run one of the PowerShell bundlers into `out`.

    The chapter lists are ours; Add-PlugChapter and Resolve-PlugForewords
    are the CHECKOUT's, so foreword cites resolve by upstream's rules and
    not by a copy here that would drift.
    """
    out.unlink(missing_ok=True)
    r = subprocess.run([str(PWSH), '-NoProfile', '-File', str(script),
                        '-OutFile', str(out)],
                       capture_output=True, text=True, cwd=str(SOURCE))
    for line in (r.stdout + r.stderr).strip().splitlines()[-3:]:
        say('  | ' + line)
    if r.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        die(f'{script.name} produced no {out.name}')
    say(f'{out.name}: {out.stat().st_size} bytes')


def refuse_bad_transpile(path, what):
    """A .zig file is only a transpile if it carries the subject.

    Agreement is not enough on its own: two arms that both refused, or both
    emitted a bare prelude for input that is not Codex at all, agree
    perfectly. A file reading `this is not codex at all` once produced
    36,697 bytes of plausible zig and exit 0 from each arm.
    """
    text = pathlib.Path(path).read_text(errors='replace')
    for line in text.splitlines():
        if line.startswith('CODEGEN-HALTED:'):
            die(f'{what}: the compiler refused the subject -- {line}')
    if 'pub fn main' not in text:
        die(f'{what}: {path} carries no `pub fn main`; this is not a '
            f'transpile, whatever else it agrees with')


def refuse_markers(path):
    """@compileError in emitted zig means the plug could not translate a
    CONSTRUCT the subject uses, and the build must not proceed to a binary
    that is quietly missing it.

    The prelude's own comptime preconditions are not that. They are fixed
    prelude text, analysed only if something instantiates them and caught
    loudly by `zig build-exe` if anything ever does; counting them as
    refusals reports a defect that does not exist. The exact allowed texts
    are in source/prelude-comptime-guards.txt, and anything not listed
    there still stops the build.
    """
    allowed = {l.strip() for l in
               (SOURCE / 'prelude-comptime-guards.txt').read_text().splitlines()
               if l.strip() and not l.startswith('#')}
    import re
    found = {}
    for m in re.finditer(r'@compileError\("[^"]*"\)',
                         pathlib.Path(path).read_text(errors='replace')):
        if m.group(0) not in allowed:
            found[m.group(0)] = found.get(m.group(0), 0) + 1
    if found:
        say(f'REFUSED: untranslated constructs in {pathlib.Path(path).name}')
        for text, n in sorted(found.items(), key=lambda kv: -kv[1]):
            say(f'    {n:5d}  {text}')
        die('the emitter could not translate the subject')


def build_exe(zig_src, out_bin):
    # cwd=local/ so zig's cache lands in the untracked half.
    out_bin.unlink(missing_ok=True)
    r = subprocess.run(['zig', 'build-exe', str(zig_src),
                        f'-femit-bin={out_bin}'],
                       capture_output=True, text=True, cwd=str(LOCAL))
    if r.returncode != 0 or not out_bin.is_file():
        for line in (r.stderr or r.stdout).strip().splitlines()[:25]:
            say('  | ' + line)
        die('zig build-exe')
    say(f'{out_bin.name}: {out_bin.stat().st_size} bytes')


def self_transpile(subject, out_zig):
    """The binary reading its own bundle.

    Output lands on stderr because print-text is cx_print is
    std.debug.print -- the same wart the emitted programs all carry, which
    is why the invocation everywhere is `codexzig < in 2> out`.
    """
    out_zig.unlink(missing_ok=True)
    with open(subject, 'rb') as fin, open(out_zig, 'wb') as ferr:
        r = subprocess.run([str(CODEXZIG)], stdin=fin, stdout=subprocess.DEVNULL,
                           stderr=ferr)
    if not out_zig.is_file() or out_zig.stat().st_size == 0:
        die(f'codexzig emitted nothing (exit {r.returncode})')
    say(f'{out_zig.name}: {out_zig.stat().st_size} bytes')


def fixed_point():
    """The invariant. Two files, one comparison, no interpretation."""
    head('the fixed point')
    for p, what in ((BARE_ZIG, 'bare-metal arm'), (SELF_ZIG, 'self arm')):
        if not p.is_file():
            die(f'{what}: no {p.name}; run without --check-only first')
        refuse_bad_transpile(p, what)
    a, b = BARE_ZIG.read_bytes(), SELF_ZIG.read_bytes()
    say(f'bare metal (seed + ring plug, under QEMU): {len(a)} bytes')
    say(f'self       (codexzig on its own bundle):   {len(b)} bytes')
    if a == b:
        say('HOLDS: byte-identical')
        return True
    say('BROKEN: what codexzig emits for its own bundle differs from what')
    say('        the seed-plus-ring-plug path emitted for it.')
    r = subprocess.run(['diff', str(BARE_ZIG), str(SELF_ZIG)],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines()[:20]:
        say('  | ' + line)
    return False


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--force', action='store_true',
                    help='rebuild every stage, guests included')
    ap.add_argument('--check-only', action='store_true',
                    help='check the fixed point against what is on disk')
    args = ap.parse_args()

    if args.check_only:
        raise SystemExit(0 if fixed_point() else 1)

    GEN.mkdir(exist_ok=True)
    LOCAL.mkdir(exist_ok=True)
    root, seed, rev, provenance = preflight()
    import guest

    head('1  bundle the ring plug')
    bundle(SOURCE / 'bundle_ringplug.ps1', RINGPLUG_SRC, root)

    head('2  compile the ring plug  [GUEST]')
    if fresh(RINGPLUG_CDX, [RINGPLUG_SRC, seed], args.force):
        say(f'{RINGPLUG_CDX.name} already matches this bundle -- not recompiling')
    else:
        RINGPLUG_CDX.unlink(missing_ok=True)
        if not guest.seed_compile(RINGPLUG_SRC, RINGPLUG_CDX, seed, LOCAL, say):
            die('the seed could not compile the ring plug')
        stamp(RINGPLUG_CDX, [RINGPLUG_SRC, seed])

    head('3  bundle the transpiler')
    bundle(SOURCE / 'bundle_codexzig.ps1', SUBJECT, root)

    head('4  compile the transpiler  [GUEST]')
    if fresh(SUBJECT_IR, [SUBJECT, seed], args.force):
        say(f'{SUBJECT_IR.name} already matches this bundle -- not recompiling')
    else:
        SUBJECT_IR.unlink(missing_ok=True)
        if not guest.seed_compile_ir(SUBJECT, SUBJECT_IR, seed, LOCAL, say):
            die('the seed could not compile the transpiler subject')
        stamp(SUBJECT_IR, [SUBJECT, seed])

    head('5  transpile it  [GUEST]')
    if fresh(BARE_ZIG, [SUBJECT_IR, RINGPLUG_CDX], args.force):
        say(f'{BARE_ZIG.name} already matches this IR -- not re-transpiling')
    else:
        BARE_ZIG.unlink(missing_ok=True)
        if not guest.ring_transpile(SUBJECT_IR, BARE_ZIG, RINGPLUG_CDX, LOCAL, say):
            die('the ring plug emitted no zig')
        stamp(BARE_ZIG, [SUBJECT_IR, RINGPLUG_CDX])
    refuse_bad_transpile(BARE_ZIG, 'bare-metal arm')
    refuse_markers(BARE_ZIG)

    head('6  build the binary')
    build_exe(BARE_ZIG, CODEXZIG)

    head('7  transpile the bundle again')
    self_transpile(SUBJECT, SELF_ZIG)
    refuse_bad_transpile(SELF_ZIG, 'self arm')

    held = fixed_point()

    (GEN / 'PROVENANCE').write_text(
        'Everything beside this file is emitted by build.py. Nothing here is\n'
        'source; edit source/ and rebuild.\n\n'
        + '\n'.join(provenance)
        + f'\n\nfixed point  {"HOLDS" if held else "BROKEN"}\n'
        + f'built in     {time.time() - _t0:.0f}s\n')
    head('done' if held else 'done -- WITH A BROKEN FIXED POINT')
    say(f'{CODEXZIG}  <  prog.codex  2>  prog.zig')
    raise SystemExit(0 if held else 1)


if __name__ == '__main__':
    main()
