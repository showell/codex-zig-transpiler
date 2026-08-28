# How a build gets from Codex source to a binary

Eight stages. Three start a QEMU guest and cost minutes; the rest cost
seconds. `build.py` names each one as it runs and marks the guests.

Everything below lands in `generated/`.

```
   source/bundle_ringplug.ps1  +  $COBBLESTONE_ROOT
1  ------------------------------------------------>  ringplug-source.codex
2  seed/Codex.cdx  ==QEMU==>                           ringplug.cdx

   source/bundle_codexzig.ps1  +  $COBBLESTONE_ROOT
3  ------------------------------------------------>  codexzig-subject.codex
4  seed/Codex.cdx  ==QEMU==>                           codexzig.ir
5  ringplug.cdx    ==QEMU==>                           codexzig.qemu.zig
6  zig build-exe                                       codexzig

7  codexzig < codexzig-subject.codex               ->  codexzig.native.zig
8  diff 5 7                                        ->  THE FIXED POINT
9  codexzig < samples/arith.codex, build, run     ->  arith.zig + its output
```

Stage 9 is not part of the invariant. It is there because the invariant alone
cannot tell you the emitter does anything: a transpiler that emitted a program
printing its own input would satisfy it. So a small program with a known
answer goes through the real artifact, and its output is checked line for
line.

Each guest is handed a blob from `generated/intake/`: the file named above it,
wrapped in a mode line and a terminator. The mode line is what makes stage 2
and stage 4 different runs of the same compiler over different sources --
`CDX map` asks for a bootable binary, `IR-CCE decks=172` asks for IR text.

Stages 4 and 5 are two separate guests, so the IR between them is a **file**.
Inside `codexzig` at stage 7 the same IR is a `let` and never touches disk --
same code, same order, one pass just has a filesystem in the middle. The
fixed point is both passes emitting the same bytes anyway.

Stage 7 gets the same *source* as stage 4, not the same blob. The envelope is
the guest's, and it is exactly what makes stage 4 answer with IR text instead
of an x86 binary.

## Why the emitter has to become a kernel first

The seed compiler emits x86, not zig. So there is no way to ask bare metal
for zig directly — the emitter has to be running somewhere, and at the
bottom of the bootstrap the only thing that runs is a Codex kernel. Stages 1
and 2 build that kernel: the zig emitter, the IR text parser, and the
declarations they need, bundled behind `ZigPlugRing.codex` and compiled by
the seed.

`ZigPlugRing` is the only part that differs from the checkout's own zig plug.
The shipped plug takes its input over TCP; this one reads the compiler's
serial ring. The reason is heap. The TCP receive path costs about **130 bytes
of guest heap per byte of IR** before the parser sees anything — four payload
materialisations per frame plus a per-character text conversion, none of it
restored, against a bump allocator that never frees. `read-serial-cce` is a
machine-code loop that builds the Text one byte per byte. The transpiler's IR
is 9 MB, which the TCP path cannot admit and the ring can.

## Why the guest is fed through a ring and a gdbstub

Nothing is streamed into the guest over serial. The input's first megabyte is
placed at guest physical `0x500000` by QEMU's generic loader *before boot*,
and the ring's write cursor is injected after `READY` through the gdbstub —
the same re-injection `codex-vm` performs on the guest's first LSR read. With
no streamed input there is nothing for QEMU 6.2's chardev stall to race
against.

The ring is 1 MB and the inputs are 3–9 MB, so the ring is a **window, not a
ceiling**. Both cursors are unbounded counters masked at access, so the host
refills from behind the guest's read cursor. Two details in `_feed_ring` are
load-bearing:

- The VM is **stopped for every cell access**. The gdbstub writes memory
  byte-wise, and a `wpos` update racing the guest's own load could tear and
  send the reader past real data.
- The loop runs until the guest has **consumed** everything, not until
  everything is delivered. A reader that finds the ring dry mid-stream parks
  in `hlt`, and nothing on this path wakes it — streamed serial wakes it
  through UART interrupts, and the preload path has no serial input by
  design. Each round's stop/resume *is* that missing wake, so detaching
  before `rpos` catches `wpos` leaves the guest asleep beside a full ring.

`TCP_NODELAY` on the gdb socket is also load-bearing, and not obviously so.
`cmd()` acks a reply with a bare `+` and then sends the next packet as a
separate small write — exactly the pattern Nagle holds until the `+` is
acknowledged, and the peer sits on that ack for 40 ms. Measured on a 2.9 MB
source: 41 ms per 1 KB packet, 25 KB/s, 99% of the fill spent writing,
against a guest that drains the whole 1 MB ring in under 191 ms. The stall
was the transport, not the ring, the poll interval, or the guest.

## Why the merged program goes through the IR text wire

`codexzig` is `codexir | zigemit` with the pipe replaced by a `let`: emit the
IR text, parse it straight back in memory, emit zig. The round trip looks
gratuitous — the two halves meet at a type, and `emit-zig-chapter` takes the
compiler's own `IRChapter`, so the front end is holding the value already.

The first version did exactly that, worked on 85 ordinary programs, and then
failed on the one that matters. Given its own bundle it emitted a monomorphic
`SortPartitionS` whose fields still said `a` — zig that does not compile.

The text wire is not an identity. It **derives what the AST does not carry**:
`IRTextEmitter.codex:404-406` computes a record's implicit type parameters
from its field types as it serialises. `foreword/core/Sort.codex` declares
`SortPartition = record { list : List a, pivot : Integer }` — no parameter
list at all, `a` free in the fields — so only the wire ever knew. Copying that
one derivation into the harness fixed the declaration and left the use sites;
copying the next would be a second rule duplicated out of the compiler, and
then a third.

So the harness stops copying rules and uses the wire, in memory. What that
buys is larger than one type: this program now runs the same code in the same
order as the two-process pipeline, so agreeing with it is structural rather
than measured.

## Stage 6 is a real gate

Before `zig build-exe` runs, the emitted zig is scanned for `@compileError`.
One of those means the plug could not translate a construct the subject
actually uses, and the build must not proceed to a binary that is quietly
missing it.

The prelude's own comptime preconditions are exempt, and the exemption list
is `source/prelude-comptime-guards.txt` — exact texts, nothing pattern-based.
They are fixed prelude text, analysed only if something instantiates them and
caught loudly by `zig build-exe` if anything ever does. Counting them as
refusals reports a defect that does not exist: `cx_address_of` once blocked
every build at this scan from a line in the prelude no subject reaches.
Anything **not** on that list still stops the build, whatever its spelling.


## Why not two guests

Putting the compiler and the emitter in one kernel would make the whole
bootstrap *compile codexzig to a kernel, then use it to transpile codexzig* —
one bundle, two guests. That kernel was built, from this same chapter list
behind a serial-ring harness, and it compiles clean at 1,971,047 bytes.

It cannot run. One guest merged holds the source, the AST, the IR and the
emitted text at once over an allocator that never frees, so its peak is the
sum of every phase rather than the largest; measured natively that is 3472 MB.
The boot stub triple-faults on a RAM size it cannot use, and the ceiling is
between 3072 MB (boots) and 3584 MB (dies before READY). No size is both
bootable and big enough.

Two things learned on the way there are worth keeping, because both failed
*quietly* rather than loudly:

- **`CDX map` gives a 2.9 MB unit deck scale 100.** `derive-deck-scale` clamps
  at 100 regardless of length (`opening.codex:135`), and the hosted build asks
  for 172 explicitly. Without the flag, CHECK overflows with CDX9002.
- **`read-serial-cce` converts nothing.** It copies raw bytes until a NUL,
  because its caller is a wire that already speaks CCE — true of an IR file
  the seed emitted, false of Codex source. Fed plain source it produced 37,688
  bytes of bare prelude, a parse of garbage, and exit 0. The seed's own driver
  reads a unit with `read-file-uni` then `utf8-to-cce`
  (`opening.codex:2188-2189`), which is the conversion.

The kernel and its harness are not kept here. They were about 200 lines to
maintain for a shape that cannot run, and what is worth keeping is the
measurement above.
