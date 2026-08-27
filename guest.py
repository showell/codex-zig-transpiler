"""The bare-metal arm: one QEMU guest, driven over serial and the gdbstub.

Two things run on bare metal in this repository and they are the SAME
function with a different kernel. `compile_ring` boots a kernel, hands it
one blob, and reads back a sized payload:

    seed/Codex.cdx  + a Codex source blob  ->  a CDX binary, or IR text
    ringplug.cdx    + an IR-CCE blob       ->  zig, as CCE bytes

The intake is the compiler's own serial ring, not streamed serial. The
input's first megabyte is placed at guest phys 0x500000 by QEMU's generic
loader before boot, and the ring's write cursor is injected after READY
through the gdbstub -- the same re-injection codex-vm does on the guest's
first LSR read. Nothing is streamed in, so there is nothing to race.

Blobs larger than the 1 MB ring stream THROUGH it: both ring positions are
unbounded counters masked at access, so the host refills from behind the
guest's read cursor and the ring becomes a window rather than a ceiling.
The transpiler subject is 2.9 MB and its IR is 9.5 MB, so this path is the
normal one here, not the exception.
"""

import os
import pathlib
import re
import socket
import subprocess
import sys
import time

import cce
import lock

ACCEL = os.environ.get('CODEX_ACCEL', 'tcg')
# One variable caps every guest on a host. The 8 GB box runs the 3072
# default; the seed dies silently above it.
MEM_MB = int(os.environ.get('CODEX_MEM_MB', '3072'))

RING_ADDR = 0x500000
RING_SIZE = 0x100000   # 1 MB, must match the seed's serial-ring-buf-size
WPOS_ADDR = 28704      # 0x7020, X86_64Boot.codex
RPOS_ADDR = 28712      # 0x7028


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def launch(kernel, mem_mb, extra_args=()):
    """Boot a Codex kernel and return (proc, data, ctrl).

    The ONE place this repository runs qemu, which is why the compute lock
    is taken here and nowhere else.
    """
    lock.take()
    # Fixed ports collide with leftover guests and with TIME_WAIT across
    # rapid relaunches, so both are dynamic.
    data_port, ctrl_port = free_port(), free_port()
    # kernel-irqchip=off is what the author's WHPX fallback needs; under KVM
    # the userspace APIC path is deprecated and the guest dies pre-READY.
    machine = ['-machine', 'kernel-irqchip=off'] if ACCEL != 'kvm' else []
    proc = subprocess.Popen([
        'qemu-system-x86_64', '-accel', ACCEL, *machine, '-kernel', str(kernel),
        '-chardev', f'socket,id=ch0,host=127.0.0.1,port={data_port},server=on,wait=on,nodelay=on',
        '-chardev', f'socket,id=ch1,host=127.0.0.1,port={ctrl_port},server=on,wait=on,nodelay=on',
        '-serial', 'chardev:ch0', '-serial', 'chardev:ch1',
        '-device', 'isa-debug-exit,iobase=0xf4,iosize=0x04',
        # codex-vm writes the guest RAM size at phys 0xFE8 pre-boot ("dynamic
        # RSP"); QEMU does not, and the boot stub then sets RSP from 0 and
        # triple-faults. Seed the cell the same way. QEMU 6.2's generic loader
        # asserts data_len < 8, so write the low 4 bytes.
        '-device', f'loader,addr=0xfe8,data={hex(mem_mb * 1024 * 1024)},data-len=4',
        '-cpu', 'max', '-display', 'none', '-no-reboot', '-m', str(mem_mb),
        *extra_args,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def connect(port):
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError('qemu exited: '
                                   + proc.stderr.read().decode()[-800:])
            try:
                return socket.create_connection(('127.0.0.1', port), timeout=1)
            except OSError:
                time.sleep(0.25)
        raise RuntimeError(f'no connection on {port}')

    # A failed connect must take QEMU with it: with wait=on chardevs a
    # half-connected guest (data attached, ctrl refused) blocks forever
    # holding its full RAM, and the caller's finally has no proc to kill yet.
    try:
        data, ctrl = connect(data_port), connect(ctrl_port)
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    return proc, data, ctrl


def wait_ready(ctrl, timeout=300):
    """Block until the kernel says READY.

    The EOF check is not decoration. Once QEMU dies the socket returns b''
    instantly and forever, and a loop without it spins at 100% against a
    frozen log until someone kills it by hand.
    """
    ctrl.settimeout(timeout)
    buf = b''
    while b'READY\n' not in buf:
        chunk = ctrl.recv(4096)
        if not chunk:
            raise RuntimeError(f'ctrl closed pre-READY: {buf!r}')
        buf += chunk
    return buf


class Gdb:
    """Just enough of the remote protocol to move two cursors and a ring."""

    def __init__(self, port):
        self.s = socket.create_connection(('127.0.0.1', port), timeout=10)
        # TCP_NODELAY, or every round trip costs a delayed ACK. cmd() acks a
        # reply with a bare "+" and then sends the next packet as a separate
        # small write -- exactly the pattern Nagle holds until the "+" is
        # acknowledged, and the peer sits on that ack for 40 ms. Measured on
        # a 2.9 MB source: 41 ms per 1 KB M packet, 25 KB/s, 99% of a ring
        # fill spent writing, against a guest draining the whole 1 MB ring in
        # under 191 ms. The stall was the transport, not the ring.
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # QEMU halts the VM on connect and may emit a spontaneous stop
        # packet; drain and ack anything queued before the first command.
        self.s.settimeout(0.8)
        try:
            while True:
                junk = self.s.recv(4096)
                if not junk:
                    break
                if b'$' in junk:
                    self.s.sendall(b'+')
        except (TimeoutError, OSError):
            pass
        self.s.settimeout(5)

    def cmd(self, payload):
        pkt = b'$' + payload + b'#' + b'%02x' % (sum(payload) % 256)
        self.s.sendall(pkt)
        buf = b''
        while True:
            c = self.s.recv(4096)
            if not c:
                raise RuntimeError('gdb closed')
            buf += c
            if b'#' in buf[1:]:
                start = buf.index(b'$')
                end = buf.index(b'#', start)
                self.s.sendall(b'+')
                return buf[start + 1:end]

    def write_mem(self, addr, data):
        r = self.cmd(b'M%x,%x:' % (addr, len(data)) + data.hex().encode())
        if r != b'OK':
            raise RuntimeError(f'gdb write @{addr:#x} failed: {r!r}')

    def read_mem(self, addr, n):
        r = self.cmd(b'm%x,%x' % (addr, n))
        if r.startswith(b'E') or len(r) != n * 2:
            raise RuntimeError(f'gdb read @{addr:#x} unexpected: {r!r}')
        return bytes.fromhex(r.decode())

    def cont_nowait(self):
        # 'c' replies only at the next stop, so consume just the '+' ack.
        payload = b'c'
        self.s.sendall(b'$' + payload + b'#' + b'%02x' % (sum(payload) % 256))
        self.s.recv(1)

    def interrupt(self):
        self.s.sendall(b'\x03')          # raw 0x03 stops a running target
        buf = b''
        while True:
            c = self.s.recv(4096)
            if not c:
                raise RuntimeError('gdb closed during interrupt')
            buf += c
            if b'#' in buf[1:]:
                self.s.sendall(b'+')
                return

    def detach(self):
        try:
            self.cmd(b'D')
        except Exception:
            pass
        self.s.close()


def _feed_ring(gdb, blob, staged, say):
    """Refill the ring from behind the guest's read cursor until CONSUMED.

    Not merely until delivered. A reader that finds the ring dry mid-stream
    parks in hlt, and nothing on this path wakes it -- streamed serial wakes
    it through UART interrupts, and the preload path has no serial input by
    design. Each round's stop/resume doubles as that missing wake, so
    detaching before rpos catches wpos leaves the guest asleep beside a
    full ring.

    The VM is stopped for every cell access: the gdbstub writes memory
    byte-wise, and a wpos update racing the guest's own load could tear and
    send the reader past real data.
    """
    wpos, last_rpos, stalled, dry = staged, -1, 0, 0
    t0 = time.time()
    gdb.cont_nowait()
    while True:
        time.sleep(0.15)
        gdb.interrupt()
        rpos = int.from_bytes(gdb.read_mem(RPOS_ADDR, 8), 'little')
        if rpos >= len(blob):
            break
        room = RING_SIZE - (wpos - rpos)
        if room > 0 and wpos < len(blob):
            chunk = blob[wpos:wpos + room]
            off = 0
            # 1 KB per M packet: hex doubles the payload and QEMU's gdbstub
            # buffer is 4096 bytes, packet framing included.
            while off < len(chunk):
                piece = chunk[off:off + 1024]
                pos = (wpos + off) & (RING_SIZE - 1)
                head = min(len(piece), RING_SIZE - pos)
                gdb.write_mem(RING_ADDR + pos, piece[:head])
                if head < len(piece):
                    gdb.write_mem(RING_ADDR, piece[head:])
                off += len(piece)
            wpos += len(chunk)
            gdb.write_mem(WPOS_ADDR, wpos.to_bytes(8, 'little'))
        elif wpos < len(blob):
            # Woke with data still to send to a ring the guest had not
            # drained a byte of.
            dry += 1
        stalled = 0 if rpos != last_rpos else stalled + 1
        last_rpos = rpos
        if stalled > 400:
            raise RuntimeError(f'guest stopped consuming at rpos {rpos} '
                               f'of {len(blob)}')
        gdb.cont_nowait()
    say(f'ring: {len(blob)} bytes consumed in {time.time() - t0:.1f}s '
        f'({dry} rounds with no room freed)')


def _read_sized(data, timeout, say):
    """Read the guest's wire: log lines, SIZE:<n>, n bytes, trailer.

    Length-driven rather than idle-driven -- the guest stays running after
    it answers, so an idle-based read always pays its full timeout.
    """
    data.settimeout(5)
    out, needed = b'', None
    deadline = time.time() + timeout
    t0 = time.time()
    while time.time() < deadline:
        try:
            chunk = data.recv(65536)
        except socket.timeout:
            if needed is not None and len(out) >= needed:
                break
            continue
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if needed is None:
            i = out.find(b'SIZE:')
            if i >= 0 and b'\n' in out[i:]:
                nl = out.index(b'\n', i)
                needed = nl + 1 + int(out[i + 5:nl].split()[0])
            elif b'CODEGEN-HALTED' in out or b'CODEGEN-ERRORS' in out:
                needed = len(out)
        if needed is not None and len(out) >= needed:
            data.settimeout(2)   # brief trailer drain (HEAP:/STACK: lines)
    say(f'stream: {len(out)} bytes in {time.time() - t0:.0f}s')
    return out


def compile_ring(blob_path, out_path, kernel, timeout=1800, say=print):
    """Boot `kernel`, feed it `blob_path`, write its payload to `out_path`.

    Returns True on a sized payload. Diagnostics land beside the output as
    `<out_path>.diags` -- all of them. A harness whose premise is that a
    disagreement is evidence does not get to discard evidence because there
    is a lot of it: capping the log at twelve lines once let 108 duplicate-
    definition warnings from one bundling bug hide CDX6020 and CDX2053 for
    months.
    """
    blob = pathlib.Path(blob_path).read_bytes()
    staged = min(len(blob), RING_SIZE)
    stage_path = blob_path
    if len(blob) > RING_SIZE:
        stage_path = str(blob_path) + '.stage1'
        pathlib.Path(stage_path).write_bytes(blob[:RING_SIZE])

    gp = free_port()
    proc, data, ctrl = launch(kernel, MEM_MB, extra_args=[
        '-device', f'loader,file={stage_path},addr={hex(RING_ADDR)},force-raw=on',
        '-gdb', f'tcp:127.0.0.1:{gp}',
    ])
    try:
        t0 = time.time()
        wait_ready(ctrl)
        say(f'READY at {time.time() - t0:.1f}s; injecting wpos={staged}')

        gdb = Gdb(gp)
        gdb.cmd(b'?')                                  # attach/halt handshake
        head = gdb.read_mem(RING_ADDR, 8)
        if head != blob[:8]:
            raise RuntimeError(f'ring preload mismatch: {head!r} vs {blob[:8]!r}')
        gdb.write_mem(WPOS_ADDR, staged.to_bytes(8, 'little'))
        gdb.write_mem(RPOS_ADDR, (0).to_bytes(8, 'little'))

        if staged < len(blob):
            _feed_ring(gdb, blob, staged, say)
        gdb.detach()

        out = _read_sized(data, timeout, say)
        i = out.find(b'SIZE:')
        header = out[:i if i >= 0 else len(out)].decode(errors='replace')
        diags = [l for l in header.splitlines()
                 if l.strip() and not l.startswith('WD:')]
        # A clean compile REMOVES the sidecar rather than leaving last run's:
        # a stale .diags keeps a vanished class "present" for anything that
        # reads it.
        dpath = pathlib.Path(str(out_path) + '.diags')
        dpath.unlink(missing_ok=True)
        if diags:
            dpath.write_text('\n'.join(diags) + '\n')
            census = {}
            for l in diags:
                m = re.search(r'CDX\d{4}', l)
                k = m.group(0) if m else 'other'
                census[k] = census.get(k, 0) + 1
            say(f'{len(diags)} diagnostics -> {dpath.name}   '
                + '  '.join(f'{k}x{v}' for k, v in sorted(census.items())))
            for line in diags[:12]:
                say('  | ' + line)
            if len(diags) > 12:
                say(f'  | ... {len(diags) - 12} more in {dpath.name}')

        if i < 0:
            say('NO SIZE MARKER -- the guest emitted nothing')
            return False
        nl = out.index(b'\n', i)
        size = int(out[i + 5:nl].split()[0])
        payload = out[nl + 1:nl + 1 + size]
        if len(payload) != size:
            say(f'SHORT READ: SIZE:{size}, got {len(payload)}')
            return False
        pathlib.Path(out_path).write_bytes(payload)
        say(f'wrote {out_path} ({size} bytes)')
        return True
    finally:
        proc.kill()
        proc.wait()


def _blob(source_path, mode, terminator, scratch):
    """Wrap a source in the guest's intake envelope: mode line, bytes, EOT."""
    src = pathlib.Path(source_path).read_bytes()
    path = pathlib.Path(scratch) / (pathlib.Path(source_path).name + '.blob')
    path.write_bytes(mode + src + terminator)
    return str(path)


def seed_compile(source_path, out_cdx, seed, scratch, say=print):
    """Compile a bundled Codex source to a CDX binary, on bare metal."""
    blob = _blob(source_path, b'CDX map\n', b'\x04', scratch)
    return compile_ring(blob, out_cdx, seed, say=say)


def seed_compile_ir(source_path, out_ir, seed, scratch, say=print):
    """Compile a bundled Codex source and capture its IR text.

    The mode line is what differs from seed_compile: `IR-CCE decks=172`
    asks the guest for IR rather than a binary.
    """
    blob = _blob(source_path, b'IR-CCE decks=172\n', b'\x04', scratch)
    return compile_ring(blob, out_ir, seed, say=say)


def ring_transpile(ir_path, out_zig, plug_cdx, scratch, say=print):
    """Feed IR text to the ring plug and decode the zig it answers.

    Any byte >= 97 is multibyte CCE, which the host table does not carry;
    that fails the run rather than leaving <NN> placeholders in a .zig file
    for zig to choke on later.
    """
    if b'\x00' in pathlib.Path(ir_path).read_bytes():
        raise SystemExit(f'{ir_path}: contains NUL; read-serial-cce would '
                         f'stop early')
    blob = _blob(ir_path, b'RING zig\n', b'\x00', scratch)
    payload_path = str(pathlib.Path(scratch) / (pathlib.Path(out_zig).name + '.cce'))
    if not compile_ring(blob, payload_path, plug_cdx, say=say):
        return False
    text = cce.decode(pathlib.Path(payload_path).read_bytes())
    bad = re.search(r'<\d+>', text)
    if bad:
        o = bad.start()
        raise SystemExit(f'{payload_path}: undecodable CCE byte near char {o}: '
                         f'...{text[max(0, o - 40):o + 40]}...')
    pathlib.Path(out_zig).write_text(text)
    say(f'wrote {out_zig} ({len(text)} chars)')
    return True


if __name__ == '__main__':
    # For poking at one stage by hand without running the whole build.
    print(f'accel={ACCEL} mem={MEM_MB}MB  guests now: {lock.guests() or "none"}',
          file=sys.stderr)
