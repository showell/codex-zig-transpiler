"""One guest at a time on this box, taken at the door that starts one.

Two 3 GB guests on an 8 GB box do not fail; they thrash at 2% CPU each
and finish in the morning. So a second guest is refused, loudly, and
never queued.

The lock is taken inside guest.launch and nowhere else, because that is
the only line in this repository that runs qemu. An entry point cannot
forget it, because it cannot start a guest without going through the
door.
"""

import fcntl
import pathlib
import subprocess

LOCKFILE = pathlib.Path.home() / '.codex-guest.lock'

_fd = None  # held for the life of the process; the flock dies with it


def guests():
    """Every QEMU guest on this host, as (pid, args).

    A guest is a process whose argv[0] is qemu-system-*, which is the
    whole identification rule -- no interpreter to resolve and no
    command string to guess at. Ours hold the flock, so the only thing
    worth seeing here is a FOREIGN guest: one started by something that
    never asks, such as the checkout's own build/compile.ps1.
    """
    out = subprocess.run(['ps', '-eo', 'pid=,args='],
                         capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines():
        pid, _, args = line.strip().partition(' ')
        if args.split(' ')[0].rsplit('/', 1)[-1].startswith('qemu-system-'):
            found.append((int(pid), args[:120]))
    return found


def take():
    """Claim the box, or raise. Idempotent within one process."""
    global _fd
    if _fd is not None:
        return
    foreign = guests()
    if foreign:
        raise SystemExit('BOX BUSY: a QEMU guest is already running here\n'
                         + '\n'.join(f'    pid {p}  {a}' for p, a in foreign))
    fd = LOCKFILE.open('w')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f'BOX BUSY: another build holds {LOCKFILE}')
    _fd = fd


if __name__ == '__main__':
    # For a script about to detach: would take() refuse right now, while
    # the refusal can still reach a terminal instead of a log?
    take()
    print('box free')
