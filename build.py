#!/usr/bin/env python3
"""Build codexzig, and check the fixed point.

    ./build.py                 build what is stale, then check
    ./build.py --force         rebuild every stage, guests included
    ./build.py --check-only    check the fixed point against what is on disk

codexzig is one program: Codex source in, zig out.

    codexzig < prog.codex 2> prog.zig

The whole exercise is one loop:

    blob -> QEMU -> zig -> exe -> (the same source again) -> zig -> diff

Getting the first zig costs three guests, because the seed compiler emits x86
and not zig. The emitter has to be compiled to a bootable kernel first, then
fed the transpiler's own IR, and only then is there a zig source to build.

    1  bundle the ring plug        the emitter, as a subject            host
    2  compile the ring plug       seed -> ringplug.cdx                GUEST
    3  bundle the transpiler       compiler + emitter + harness         host
    4  compile the transpiler      seed -> codexzig.ir                 GUEST
    5  transpile it                ringplug.cdx -> codexzig.qemu.zig   GUEST
    6  build the binary            zig build-exe -> local/codexzig      host
    7  transpile the same source   codexzig -> codexzig.native.zig      host
    8  diff 5 against 7            THE FIXED POINT

Stage 8 is the invariant this repository exists for. The emitter emits the
same bytes for its own source whether it is running on bare metal under QEMU
or as the native binary that run produced. It exercises every chapter of the
compiler and the whole emitter, and it costs a minute against the seven the
stages above already spent.

Stage 7 is handed the same SOURCE as stage 4, not the same blob bytes. A blob
is the source wrapped in the guest's intake envelope, and the envelope is
what makes stage 4 answer with IR text instead of an x86 binary; the native
binary reads plain Codex on stdin and would choke on the mode line.

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
INTAKE = GEN / 'intake'

PWSH = pathlib.Path.home() / '.local' / 'pwsh' / 'pwsh'

RINGPLUG_SRC = GEN / 'ringplug-source.codex'
RINGPLUG_CDX = GEN / 'ringplug.cdx'
SUBJECT = GEN / 'codexzig-subject.codex'
SUBJECT_IR = GEN / 'codexzig.ir'
QEMU_ZIG = GEN / 'codexzig.qemu.zig'
NATIVE_ZIG = GEN / 'codexzig.native.zig'
CODEXZIG = LOCAL / 'codexzig'

# What each guest actually eats: the file above, plus a mode line.
RINGPLUG_BLOB = INTAKE / 'ringplug-source.codex.blob'
SUBJECT_BLOB = INTAKE / 'codexzig-subject.codex.blob'
IR_BLOB = INTAKE / 'codexzig.ir.blob'
CCE_PAYLOAD = LOCAL / 'codexzig.qemu.zig.cce'

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

def bundle(script, out):
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

    Agreement is not enough on its own: two passes that both refused, or
    both emitted a bare prelude for input that is not Codex at all, agree
    perfectly. A file reading `this is not codex at all` once produced
    36,697 bytes of plausible zig and exit 0 from each side.
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
    for p, what in ((QEMU_ZIG, 'pass 1, under QEMU'),
                    (NATIVE_ZIG, 'pass 2, native')):
        if not p.is_file():
            die(f'{what}: no {p.name}; run without --check-only first')
        refuse_bad_transpile(p, what)
    a, b = QEMU_ZIG.read_bytes(), NATIVE_ZIG.read_bytes()
    say(f'pass 1  the emitter under QEMU:  {len(a)} bytes')
    say(f'pass 2  the emitter as a binary: {len(b)} bytes')
    if a == b:
        say('HOLDS: byte-identical')
        return True
    say('BROKEN: the emitter does not emit the same bytes for its own source')
    say('        when it runs natively as when it ran under QEMU.')
    r = subprocess.run(['diff', str(QEMU_ZIG), str(NATIVE_ZIG)],
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

    for d in (GEN, LOCAL, INTAKE):
        d.mkdir(exist_ok=True)
    root, seed, rev, provenance = preflight()
    import guest

    head('1  bundle the ring plug')
    bundle(SOURCE / 'bundle_ringplug.ps1', RINGPLUG_SRC)
    guest.wrap(RINGPLUG_SRC, guest.MODE_CDX, b'\x04', RINGPLUG_BLOB)
    say(f'{RINGPLUG_BLOB.name}: {RINGPLUG_BLOB.stat().st_size} bytes')

    head('2  compile the ring plug  [GUEST]')
    if fresh(RINGPLUG_CDX, [RINGPLUG_BLOB, seed], args.force):
        say(f'{RINGPLUG_CDX.name} already answers this blob -- not recompiling')
    else:
        RINGPLUG_CDX.unlink(missing_ok=True)
        if not guest.compile_ring(RINGPLUG_BLOB, RINGPLUG_CDX, seed, LOCAL, say=say):
            die('the seed could not compile the ring plug')
        stamp(RINGPLUG_CDX, [RINGPLUG_BLOB, seed])

    head('3  bundle the transpiler')
    bundle(SOURCE / 'bundle_codexzig.ps1', SUBJECT)
    guest.wrap(SUBJECT, guest.MODE_IR, b'\x04', SUBJECT_BLOB)
    say(f'{SUBJECT_BLOB.name}: {SUBJECT_BLOB.stat().st_size} bytes')

    head('4  compile the transpiler  [GUEST]')
    if fresh(SUBJECT_IR, [SUBJECT_BLOB, seed], args.force):
        say(f'{SUBJECT_IR.name} already answers this blob -- not recompiling')
    else:
        SUBJECT_IR.unlink(missing_ok=True)
        if not guest.compile_ring(SUBJECT_BLOB, SUBJECT_IR, seed, LOCAL, say=say):
            die('the seed could not compile the transpiler subject')
        stamp(SUBJECT_IR, [SUBJECT_BLOB, seed])

    head('5  transpile it  [GUEST]')
    guest.wrap(SUBJECT_IR, guest.MODE_ZIG, b'\x00', IR_BLOB)
    say(f'{IR_BLOB.name}: {IR_BLOB.stat().st_size} bytes')
    if fresh(QEMU_ZIG, [IR_BLOB, RINGPLUG_CDX], args.force):
        say(f'{QEMU_ZIG.name} already answers this blob -- not re-transpiling')
    else:
        QEMU_ZIG.unlink(missing_ok=True)
        if not guest.compile_ring(IR_BLOB, CCE_PAYLOAD, RINGPLUG_CDX, LOCAL, say=say):
            die('the ring plug emitted no zig')
        guest.decode_zig(CCE_PAYLOAD, QEMU_ZIG, say)
        stamp(QEMU_ZIG, [IR_BLOB, RINGPLUG_CDX])
    refuse_bad_transpile(QEMU_ZIG, 'pass 1, under QEMU')
    refuse_markers(QEMU_ZIG)

    head('6  build the binary')
    # Untracked, and that is a deliberate reversal. The binary was tracked so
    # that people could get a working codexzig without an 8 GB box and seven
    # minutes -- but codexzig.qemu.zig is tracked, and `zig build-exe` on it
    # takes two seconds and needs no QEMU, no pwsh and no checkout. Keeping a
    # 28 MB blob that zig does not even build reproducibly, to save two
    # seconds, is a bad trade.
    #
    # It is still built once and kept locally, and this guard ignores --force:
    # that flag means "do not trust the fingerprints, run the guests again",
    # and re-running them yields the same zig. It does not mean "replace a
    # working executable with a different working executable".
    if fresh(CODEXZIG, [QEMU_ZIG], force=False):
        say(f'{CODEXZIG.name} was already built from this zig -- keeping it')
    else:
        build_exe(QEMU_ZIG, CODEXZIG)
        stamp(CODEXZIG, [QEMU_ZIG])

    head('7  transpile the same source')
    if fresh(NATIVE_ZIG, [CODEXZIG, SUBJECT], args.force):
        say(f'{NATIVE_ZIG.name} is already this binary\'s answer -- not re-running')
    else:
        self_transpile(SUBJECT, NATIVE_ZIG)
        stamp(NATIVE_ZIG, [CODEXZIG, SUBJECT])
    refuse_bad_transpile(NATIVE_ZIG, 'pass 2, native')

    held = fixed_point()

    intake = ['', 'what each guest was actually handed (intake/):', '']
    for blob in (RINGPLUG_BLOB, SUBJECT_BLOB, IR_BLOB):
        mode = blob.read_bytes().split(b'\n', 1)[0].decode()
        intake.append(f'  {blob.name:<32} {blob.stat().st_size:>9} bytes '
                      f'  mode {mode!r}')
    (GEN / 'PROVENANCE').write_text(
        'Everything beside this file is emitted by build.py. Nothing here is\n'
        'source; edit source/ and rebuild.\n\n'
        + '\n'.join(provenance + intake)
        + f'\n\nfixed point  {"HOLDS" if held else "BROKEN"}\n'
        + f'built in     {time.time() - _t0:.0f}s\n')
    head('done' if held else 'done -- WITH A BROKEN FIXED POINT')
    say(f'{CODEXZIG}  <  prog.codex  2>  prog.zig')
    raise SystemExit(0 if held else 1)


if __name__ == '__main__':
    main()
