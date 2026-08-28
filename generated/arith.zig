const std = @import("std");

// cx_gpa and the heap it allocates from live beside the buffer
// builtins below: one region, one bump frontier, bare metal's model.

fn CxFn1(comptime A: type, comptime R: type) type {
    return struct { ctx: *anyopaque, call: *const fn (*anyopaque, A) R };
}
fn CxFn2(comptime A: type, comptime B: type, comptime R: type) type {
    return struct { ctx: *anyopaque, call: *const fn (*anyopaque, A, B) R };
}
fn CxFn3(comptime A: type, comptime B: type, comptime C: type, comptime R: type) type {
    return struct { ctx: *anyopaque, call: *const fn (*anyopaque, A, B, C) R };
}
fn CxFn4(comptime A: type, comptime B: type, comptime C: type, comptime D: type, comptime R: type) type {
    return struct { ctx: *anyopaque, call: *const fn (*anyopaque, A, B, C, D) R };
}
fn CxList(comptime T: type) type {
    return struct { items: std.ArrayListUnmanaged(T) = .empty };
}
fn cx_ll_empty(comptime T: type) *CxList(T) {
    const cx_l = cx_gpa.create(CxList(T)) catch @panic("oom");
    cx_l.* = .{};
    return cx_l;
}
fn cx_ll_push(l: anytype, v: anytype) @TypeOf(l) {
    l.items.append(cx_gpa, v) catch @panic("oom");
    return l;
}
// Exact, not rounded. These three build most of what emission
// allocates -- every instruction is a list literal (mov-rr is
// [rex-w, 137, modrm]) and write-bytes concatenates one per byte of an
// immediate -- and they all land on the DECK, which is a finite
// reservation nothing reclaims until the phase ends. Growing through
// std's geometric growCapacity asked for 17 slots to hold four, twice
// per concat, and measured 2026-08-21 that cost 6,963,432 bytes of deck
// on fibx: 9,392,656 bytes of emit-runtime-helpers where bare metal
// spends at most 2,682,824. Bare metal allocates cap*8 + 16 once, from
// __list_concat_many over all operands at their true total. Reserve the
// true total and append without re-checking; cx_ll_push keeps geometric
// growth on purpose, because it is the repeated-append path.
fn cx_ll_of(comptime T: type, vs: []const T) *CxList(T) {
    const l = cx_ll_empty(T);
    l.items.ensureTotalCapacityPrecise(cx_gpa, vs.len) catch @panic("oom");
    l.items.appendSliceAssumeCapacity(vs);
    return l;
}
fn cx_ll_concat(a: anytype, b: @TypeOf(a)) @TypeOf(a) {
    const c = cx_new(@TypeOf(a.*){ .items = .empty });
    c.items.ensureTotalCapacityPrecise(cx_gpa, a.items.items.len + b.items.items.len) catch @panic("oom");
    c.items.appendSliceAssumeCapacity(a.items.items);
    c.items.appendSliceAssumeCapacity(b.items.items);
    return c;
}
fn cx_ll_cons(v: anytype, l: anytype) @TypeOf(l) {
    const c = cx_new(@TypeOf(l.*){ .items = .empty });
    c.items.ensureTotalCapacityPrecise(cx_gpa, 1 + l.items.items.len) catch @panic("oom");
    c.items.appendAssumeCapacity(v);
    c.items.appendSliceAssumeCapacity(l.items.items);
    return c;
}
fn cx_ll_insert_at(l: anytype, i: i64, v: anytype) @TypeOf(l) {
    l.items.insert(cx_gpa, @intCast(i), v) catch @panic("oom");
    return l;
}
// The capacity is load-bearing, not a hint. The emit tables are
// pre-sized to accum-capacity precisely so a push inside emit-all-defs'
// per-definition save/restore bracket never reallocates: a reallocation
// there lands in scratch the bracket reclaims, and the table's header
// survives pointing at bytes the next definition overwrites. The
// compiler says so itself, in the guard beside that bracket -- "a push
// past it reallocates into scratch that this loop reclaims, corrupting
// the table". Discarding n was survivable only while __heap-restore was
// a no-op. Precise, not rounded: pre-allocated to accum-capacity is a
// statement about a number.
fn cx_ll_with_capacity(comptime T: type, n: i64) *CxList(T) {
    const l = cx_ll_empty(T);
    if (n > 0) l.items.ensureTotalCapacityPrecise(cx_gpa, @intCast(n)) catch @panic("oom");
    return l;
}
fn cx_text_compare(a: []const u8, b: []const u8) i64 {
    return switch (std.mem.order(u8, a, b)) { .lt => -1, .eq => 0, .gt => 1 };
}
// Mirrors bare metal's __text_to_double, not a correctly-rounded parse:
// accumulate the digits as one wrapping integer, count places after the
// dot, cvtsi2sd once, divide once by 10^frac built by repeated
// multiplication. The bits land in IrNumLit, so they must match the seed's
// exactly; a parser that rounds better is a parser that diverges.
fn cx_text_to_double_bits(s: []const u8) i64 {
    if (s.len == 0) return 0;
    var i: usize = 0;
    var neg = false;
    if (s[0] == 73) {
        neg = true;
        i = 1;
    }
    var acc: i64 = 0;
    var frac: i64 = 0;
    var dot: i64 = 0;
    while (i < s.len) : (i += 1) {
        const b = s[i];
        if (b == 65) {
            dot = 1;
            continue;
        }
        acc = acc *% 10 +% (@as(i64, b) -% 3);
        frac += dot;
    }
    if (neg) acc = -%acc;
    var v: f64 = @floatFromInt(acc);
    if (frac != 0) {
        var p: f64 = 1.0;
        var k = frac;
        while (k != 0) : (k -= 1) p *= 10.0;
        v /= p;
    }
    return @bitCast(v);
}
// real-f32 on bare metal is f32 bits in a general register (a movd
// round-trip, emit-bits-to-real-approx-builtin); Real is f64 here, and
// widening the named f32 value is exact.
fn cx_bits_to_real_approx(bits: i64) f64 {
    return @floatCast(@as(f32, @bitCast(@as(u32, @truncate(@as(u64, @bitCast(bits)))))));
}
// A char is a CCE code and text is CCE, so making text from a char is
// ONE raw byte, the way bare metal does: emit-char-to-text-builtin stores
// the code with mov-store-byte, length 1, no framing, truncating silently
// past 255. Byte-wise text rebuilds (ir-quote walks char-code-at /
// code-to-char / char-to-text over every byte) rely on that identity to
// pass CCE frame bytes through untouched; framing or converting here
// corrupts the wire.
fn cx_char_to_text(c: i64) []const u8 {
    const b = cx_gpa.alloc(u8, 1) catch @panic("oom");
    b[0] = @truncate(@as(u64, @bitCast(c)));
    return b;
}
fn cx_char_encode(c: i64) []const u8 {
    const u = @as(u64, @bitCast(c));
    if (u < 128) {
        const b = cx_gpa.alloc(u8, 1) catch @panic("oom");
        b[0] = @truncate(u);
        return b;
    }
    if (u < 2176) {
        const v = u - 128;
        const b = cx_gpa.alloc(u8, 2) catch @panic("oom");
        b[0] = @truncate(192 | (v >> 6));
        b[1] = @truncate(128 | (v & 63));
        return b;
    }
    if (u < 67712) {
        const v = u - 2176;
        const b = cx_gpa.alloc(u8, 3) catch @panic("oom");
        b[0] = @truncate(224 | (v >> 12));
        b[1] = @truncate(128 | ((v >> 6) & 63));
        b[2] = @truncate(128 | (v & 63));
        return b;
    }
    const v = u - 67712;
    const b = cx_gpa.alloc(u8, 4) catch @panic("oom");
    b[0] = @truncate(240 | (v >> 18));
    b[1] = @truncate(128 | ((v >> 12) & 63));
    b[2] = @truncate(128 | ((v >> 6) & 63));
    b[3] = @truncate(128 | (v & 63));
    return b;
}
fn cx_list_len(l: anytype) i64 {
    return @intCast(l.items.items.len);
}
fn cx_list_at(l: anytype, i: i64) @TypeOf(l.items.items[0]) {
    return l.items.items[@intCast(i)];
}
fn cx_text_len(s: []const u8) i64 {
    return @intCast(s.len);
}
fn cx_char_at(s: []const u8, i: i64) i64 {
    return @intCast(s[@intCast(i)]);
}
// Traps rather than clamps, because bare metal traps: emit-substring-bounds
// (Emit/X86_64Builtins.codex:666) emits three UD2s -- negative start,
// negative length, and len past the end -- at a deliberate ruling, since a
// clamp turns a program's bug into quietly wrong data and a safety guarantee
// is never silently degraded. The unchecked version returned the whole of
// the NEXT allocation verbatim. Note the third check subtracts rather than
// adding: start + len can wrap, and the input that wraps it is the one an
// attacker picks; s.len - cx_a cannot, because the guard above pins cx_a to
// [0, s.len]. Finding 28.
// Copies, because bare metal copies, and the difference is observable:
// emit-substring-alloc bumps r10 -- the LIVE allocation register, which
// inside a deck extent is the deck cursor -- so a substring taken between
// __deck-enter and __deck-exit lands ON THE DECK and outlives a rewind of
// the frontier. A slice of the argument cannot: it stays where the argument
// was, and a value that looks decked and is not becomes a table full of
// reclaimed bytes. Same reasoning for every piece of a split. Finding 29.
fn cx_text_dup(s: []const u8) []const u8 {
    const cx_out = cx_gpa.alloc(u8, s.len) catch @panic("oom");
    @memcpy(cx_out, s);
    return cx_out;
}
fn cx_substring(s: []const u8, start: i64, len: i64) []const u8 {
    if (start < 0 or len < 0) @panic("cx substring: negative start or length");
    const cx_a: usize = @intCast(start);
    if (cx_a > s.len or len > @as(i64, @intCast(s.len - cx_a))) @panic("cx substring: out of range");
    return cx_text_dup(s[cx_a .. cx_a + @as(usize, @intCast(len))]);
}
fn cx_ipow(a: i64, b: i64) i64 {
    if (b < 0) return 0;
    var cx_acc: i64 = 1;
    var cx_base = a;
    var cx_e = b;
    while (cx_e > 0) {
        if ((cx_e & 1) == 1) cx_acc = cx_acc *% cx_base;
        cx_base = cx_base *% cx_base;
        cx_e = cx_e >> 1;
    }
    return cx_acc;
}
fn cx_shl(a: i64, b: i64) i64 {
    return a << @as(u6, @intCast(b & 63));
}
fn cx_shr(a: i64, b: i64) i64 {
    return a >> @as(u6, @intCast(b & 63));
}
// ONE heap, bare metal's own model: records, lists, text, closures,
// buffers and the emit workspace all come from a single bump frontier
// (cx_hp), so __heap-restore reclaims everything allocated since the
// matching __heap-save. On bare metal __alloc bumps the same pointer
// the save/restore pair moves, and emit-all-defs brackets EVERY
// definition in one -- emission costs the max over definitions there
// and must not cost the sum here. The region is reserved once and
// never moved: a reallocating region would dangle every pointer
// handed out before the growth. page_allocator memory is lazily
// faulted zero pages, so resident stays proportional to what is
// touched, the zero-fill the guest does at boot comes free, and the
// byte at index i IS address i. The reservation is finite on purpose:
// the depot peeks absolute addresses (smp-* boards poll ~2.1 GB), and
// an address outside the region must refuse with the address in the
// message, not zero-fill its way up to it. The bump pointer boots at
// bare metal's own heap base (boot does mov r10, 6291456): the
// absolute value is observable -- the depot's arith-narrow-proven
// asserts __heap-save > 0 as a structural fact. Addresses below the
// base belong to the deck, which swaps cx_hp in and out below.
// 4 GiB: bare metal's guest is 3 GB and compiles its largest subjects
// inside it, and the hosted harnesses reserve 512 MB of that as deck;
// finding 24 measured the fibx subject at 381 MB deck + ~1.2 GB main,
// which the old 1.5 GiB could not hold. Reserving costs nothing resident
// (lazily faulted, below); what bounds a runaway is the venue's cgroup
// MemoryMax (the ladder's bounded_run), not this constant.
const cx_heap_reserve: usize = 4096 * 1024 * 1024;
var cx_heap_mem: []u8 = &.{};
var cx_hp: i64 = 6291456;
// rawAlloc, NOT Allocator.alloc. The wrapper memsets every allocation to
// `undefined`, which in a Debug build is 0xAA -- so the whole reserved
// region arrived filled with 170s instead of zeros, and the memset
// touched the whole region, committing a reservation that is supposed to
// stay resident in proportion to what is used. Bare metal reserves a
// span the guest zero-filled at boot, so a fresh buffer reads as zero
// there; measured 2026-08-21 with findings/probe-fresh-span.codex,
// ours read 170 in every byte. rawAlloc hands back the pages the OS
// gives, which are zero and faulted lazily.
fn cx_heap_base() [*]u8 {
    if (cx_heap_mem.len == 0) {
        const cx_pa = std.heap.page_allocator;
        const cx_p = cx_pa.rawAlloc(cx_heap_reserve, .fromByteUnits(4096), @returnAddress()) orelse @panic("cx heap: cannot reserve the region");
        cx_heap_mem = cx_p[0..cx_heap_reserve];
    }
    return cx_heap_mem.ptr;
}
fn cx_buf_want(n: i64) void {
    if (n < 0 or @as(usize, @intCast(n)) > cx_heap_reserve) std.debug.panic("cx heap: address {d} outside the {d}-byte region", .{ n, cx_heap_reserve });
    _ = cx_heap_base();
}
// The deck is a FINITE reservation and nothing else enforces it. The
// program places it with __deck-set and then lifts the main frontier
// clear of it with __heap-advance (emit-build reserves
// defs*65536 + 25165824), so the parked main frontier sits exactly at
// the deck's top: inside an extent, a deck allocation that reaches
// cx_bivy has overrun its region and is about to write over main's live
// objects. Outside an extent the deck's live bytes are
// [cx_deck_base, cx_dptr), and main may not OVERLAP that span anywhere,
// not merely cross its top: __heap-restore can park the frontier beneath
// the deck, and a frontier climbing back from below tramples live deck
// objects long before it straddles cx_dptr -- that is the path the
// 2026-08-21 crash took, build_debug_map landing on the decked
// CodegenState. In the standard emit-build shape main lives above the
// deck, so base < cx_dptr never holds and the overlap test is silent.
// Checking only the region ceiling lets the two cursors walk through
// each other in silence -- measured 2026-08-21, fibx's deck ran 8613088
// bytes past a 25362432-byte reservation and the wreckage surfaced as a
// segfault in a hash function thousands of allocations later. Upstream knows this
// failure shape: BuildSettings records that starving the floor crashes
// on a garbage pointer instead of raising CDX9002, because deck-short-of
// reads __deck-pos, which is frozen inside a phase-wide extent. resize
// declines rather than panics, funnelling the crossing into the alloc
// path so there is one refusal site.
fn cx_frontier_crosses(base: usize, len: usize) bool {
    if (cx_nest > 0) {
        if (cx_bivy <= 0) return false;
        const o: usize = @intCast(cx_bivy);
        return base < o and base + len > o;
    }
    if (cx_dptr <= 0) return false;
    const top: usize = @intCast(cx_dptr);
    const bot: usize = @intCast(cx_deck_base);
    return base < top and base + len > bot;
}
fn cx_bump_alloc(_: *anyopaque, len: usize, alignment: std.mem.Alignment, _: usize) ?[*]u8 {
    const base = alignment.forward(@intCast(cx_hp));
    if (base + len > cx_heap_reserve) std.debug.panic("cx heap: exhausted at {d} + {d} of {d}", .{ base, len, cx_heap_reserve });
    if (cx_frontier_crosses(base, len)) std.debug.panic("cx heap: the two cursors met -- alloc at {d} + {d} crosses (hp={d} dptr={d} deck_base={d} bivy={d} nest={d})", .{ base, len, cx_hp, cx_dptr, cx_deck_base, cx_bivy, cx_nest });
    cx_hp = @intCast(base + len);
    cx_deck_armed = false;
    if (cx_nest > 0 and cx_hp > cx_deck_hw) {
        cx_deck_hw = cx_hp;
        if (cx_deck_hw - cx_deck_base > cx_deck_best) cx_deck_best = cx_deck_hw - cx_deck_base;
        cx_deck_report();
    }
    return cx_heap_base() + base;
}
// In-place growth when the block is the topmost allocation is bare
// metal's __list_snoc path 2 -- extend the frontier block, reallocate
// only otherwise. The mirror, not an optimisation: a plug whose list
// growth reallocates where bare metal extends allocates a different
// amount for the same program. free rewinds only the topmost block,
// the same rule from the other side.
fn cx_bump_resize(_: *anyopaque, memory: []u8, _: std.mem.Alignment, new_len: usize, _: usize) bool {
    const off = @intFromPtr(memory.ptr) - @intFromPtr(cx_heap_base());
    if (off + memory.len == @as(usize, @intCast(cx_hp))) {
        if (off + new_len > cx_heap_reserve) return false;
        if (cx_frontier_crosses(off, new_len)) return false;
        cx_hp = @intCast(off + new_len);
        return true;
    }
    return new_len <= memory.len;
}
fn cx_bump_remap(ctx: *anyopaque, memory: []u8, alignment: std.mem.Alignment, new_len: usize, ra: usize) ?[*]u8 {
    return if (cx_bump_resize(ctx, memory, alignment, new_len, ra)) memory.ptr else null;
}
fn cx_bump_free(_: *anyopaque, memory: []u8, _: std.mem.Alignment, _: usize) void {
    const off = @intFromPtr(memory.ptr) - @intFromPtr(cx_heap_base());
    if (off + memory.len == @as(usize, @intCast(cx_hp))) cx_hp = @intCast(off);
}
const cx_heap_vtable = std.mem.Allocator.VTable{ .alloc = cx_bump_alloc, .resize = cx_bump_resize, .remap = cx_bump_remap, .free = cx_bump_free };
const cx_gpa = std.mem.Allocator{ .ptr = undefined, .vtable = &cx_heap_vtable };
fn cx_heap_save() i64 {
    return cx_hp;
}
fn cx_heap_advance(n: i64) i64 {
    if (cx_deck_armed) {
        cx_deck_armed = false;
        cx_deck_top = cx_hp + n;
        cx_hp += cx_deck_slack;
    }
    cx_hp += n;
    return 0;
}
fn cx_heap_restore(h: i64) i64 {
    cx_hp = h;
    return 0;
}
// Wrapping, because bare metal does a single 64-bit load and every
// bit pattern is a legal i64. Rebuilding the value with checked * and +
// traps on any qword whose top byte sets the high bit -- that is, on
// every NEGATIVE qword. Measured 2026-08-21 with
// findings/probe-peek-qword.codex: bytes 00 00 00 00 00 00 00 FF answer
// -72057594037927936 on bare metal and panic here.
fn cx_peek_qword(b: i64, off: i64) i64 {
    cx_buf_want(b + off + 8);
    var cx_v: i64 = 0;
    var cx_j: i64 = 7;
    while (cx_j >= 0) : (cx_j -= 1) cx_v = cx_v *% 256 +% cx_heap_mem[@as(usize, @intCast(b + off + cx_j))];
    return cx_v;
}
// Bare metal's address-of is emit-identity-builtin: it returns the VALUE,
// and since records, lists and texts are pointers there, the value IS the
// address. Answering a constant 0 made every object identical to every other
// one AND to null, and the compiler reads that as an answer: mode-ordinal and
// real-width-ordinal short-circuit on `address-of m == 0`, so they returned 0
// for every input, and copy-sx-text decides durability with `address-of t < b`,
// so it always shared and never rematerialised -- into a region about to be
// reclaimed. Finding 31.
//
// The 0 was justified by X86_64Compound's note that address-of "silently
// answers 0 on any target where it cannot be modelled: that cost the C# arm
// every tag in this table". That note describes the hazard as a cost, not a
// licence, and this is not such a target -- one flat region and pointers into
// it is exactly the shape bare metal has.
//
// HEAP-RELATIVE, not a host pointer: the answers are compared against
// __heap-save values, which are offsets from cx_heap_base. A raw @intFromPtr
// would order correctly among itself and be nonsense against those.
fn cx_address_of(v: anytype) i64 {
    switch (@typeInfo(@TypeOf(v))) {
        .int, .comptime_int => return @intCast(v),
        .bool => return @intFromBool(v),
        .pointer => |cx_pi| {
            const cx_p = if (cx_pi.size == .slice) @intFromPtr(v.ptr) else @intFromPtr(v);
            const cx_base = @intFromPtr(cx_heap_base());
            return if (cx_p >= cx_base) @intCast(cx_p - cx_base) else 0;
        },
        else => @compileError("zig plug: no address-of for this type"),
    }
}
// The deck is the C# plug's rule (_Buf.deck_enter/deck_exit): the
// outermost enter parks the bump pointer in the bivy and swaps the deck
// pointer in; the outermost exit swaps back. Deck position is observable
// (the depot's deck-*-contract subjects print it), so a no-op deck is a
// wrong answer, not a simplification.
var cx_dptr: i64 = 0;
var cx_bivy: i64 = 0;
var cx_nest: i64 = 0;
// The deck high-water mark. `emit-build` reserves defs*65536+25165824 for
// the deck and lifts the main frontier to exactly its top, so while an extent
// is open the PARKED frontier (cx_bivy) IS the reservation ceiling and cx_hp is
// the live deck cursor. Peak minus base is what the deck cost; ceiling minus
// peak is what was left. Nothing else can report this -- the deck-pos cell is
// frozen inside an extent, which is why upstream's own deck-short-of guard
// cannot fire where exhaustion actually happens.
var cx_deck_base: i64 = 0;
var cx_deck_hw: i64 = 0;
var cx_deck_top: i64 = 0;
var cx_deck_best: i64 = 0;
var cx_deck_stride: i64 = 0;
var cx_deck_armed: bool = false;
// Measurement-only headroom, added to the lift that follows __deck-set so
// the deck can run PAST its reservation without meeting the main frontier.
// Zero in every normal build, and it must stay zero in anything banked: it
// changes __deck-pos, which the depot can observe. The point of it is that the
// guard fires at the FIRST crossing, and a first crossing tells you only that
// demand exceeded the reservation -- the deficit it reports is bounded by one
// allocation and is therefore always about zero. Slack lets the program finish
// so the TRUE peak is knowable.
const cx_deck_slack: i64 = 0;
// STDOUT, never stderr. stderr carries the program's output and every
// comparison in the ladder diffs it, so a measurement written there would
// corrupt the thing being measured. Raw write syscall rather than
// std.Io.File, which in 0.16 wants an Io instance. Only on a new peak, so the
// lines are few and the last one is the answer.
fn cx_deck_report() void {
    if (@import("builtin").os.tag != .linux) return;
    if (cx_deck_base == 0 or cx_deck_top == 0) return;
    const cx_used = cx_deck_hw - cx_deck_base;
    if (cx_used - cx_deck_stride < 1048576) return;
    cx_deck_stride = cx_used;
    var cx_b: [224]u8 = undefined;
    const cx_s = std.fmt.bufPrint(&cx_b, "CX-DECK used={d} reserved={d} headroom={d} base={d} peak={d} best={d}\n", .{ cx_used, cx_deck_top - cx_deck_base, cx_deck_top - cx_deck_hw, cx_deck_base, cx_deck_hw, cx_deck_best }) catch return;
    _ = std.os.linux.write(1, cx_s.ptr, cx_s.len);
}
fn cx_deck_enter() i64 {
    if (cx_nest == 0) {
        cx_bivy = cx_hp;
        cx_hp = cx_dptr;
    }
    cx_nest += 1;
    return 0;
}
fn cx_deck_exit() i64 {
    cx_nest -= 1;
    if (cx_nest == 0) {
        cx_dptr = cx_hp;
        cx_hp = cx_bivy;
        cx_deck_report();
    }
    return 0;
}
fn cx_deck_pos() i64 {
    return cx_dptr;
}
fn cx_deck_set(p: i64) i64 {
    cx_dptr = p;
    cx_deck_base = p;
    cx_deck_hw = p;
    cx_deck_top = 0;
    cx_deck_stride = 0;
    cx_deck_best = 0;
    cx_deck_armed = true;
    return 0;
}
// The I/O boundary. Codex text is CCE everywhere inside -- on bare metal
// and here alike -- so these convert at the edge and nowhere else: bytes
// arriving become CCE, bytes leaving are already what they are. std.fs in
// 0.16 wants an Io the generated main has no reason to carry, so this uses
// the raw syscalls.
fn cx_utf8_to_cce(bytes: []const u8) []const u8 {
    var out: std.ArrayListUnmanaged(u8) = .empty;
    var i: usize = 0;
    while (i < bytes.len) {
        const n = std.unicode.utf8ByteSequenceLength(bytes[i]) catch @panic("cx_utf8_to_cce: bad utf8");
        const cp = std.unicode.utf8Decode(bytes[i..][0..n]) catch @panic("cx_utf8_to_cce: bad utf8");
        cx_cce_frame(cx_cp_to_cce(cp), &out);
        i += n;
    }
    return out.items;
}
fn cx_read_file_uni(path_cce: []const u8) []const u8 {
    const al = cx_gpa;
    const path = cx_cce_to_utf8(path_cce);
    const z = al.allocSentinel(u8, path.len, 0) catch @panic("oom");
    @memcpy(z, path);
    const rc = std.os.linux.openat(-100, z.ptr, .{ .ACCMODE = .RDONLY }, 0);
    if (@as(isize, @bitCast(rc)) < 0) @panic("cx_read_file_uni: cannot open");
    const fd: i32 = @intCast(rc);
    defer _ = std.os.linux.close(fd);
    var raw: std.ArrayListUnmanaged(u8) = .empty;
    var chunk: [65536]u8 = undefined;
    while (true) {
        const n = std.os.linux.read(fd, &chunk, chunk.len);
        if (@as(isize, @bitCast(n)) < 0) @panic("cx_read_file_uni: read failed");
        if (n == 0) break;
        raw.appendSlice(al, chunk[0..n]) catch @panic("oom");
    }
    return cx_utf8_to_cce(raw.items);
}
fn cx_write_all(bytes: []const u8) void {
    var off: usize = 0;
    while (off < bytes.len) {
        const n = std.os.linux.write(1, bytes.ptr + off, bytes.len - off);
        if (@as(isize, @bitCast(n)) <= 0) @panic("cx_write_all: write failed");
        off += n;
    }
}
fn cx_write_binary(vs: anytype) void {
    const al = cx_gpa;
    var out: std.ArrayListUnmanaged(u8) = .empty;
    for (vs.items.items) |v| out.append(al, @intCast(@mod(v, 256))) catch @panic("oom");
    cx_write_all(out.items);
}
fn cx_write_binary_buf(b: i64, off: i64, len: i64) void {
    cx_buf_want(b + off + len);
    const s: usize = @intCast(b + off);
    cx_write_all(cx_heap_mem[s .. s + @as(usize, @intCast(len))]);
}
// variant-tag is the constructor's 0-based declaration index: bare
// metal loads word 0 of the variant block (emit-variant-tag-builtin) and
// writes find-ctor-tag there, and a union(enum)'s tag is numbered the same
// way by declaration order. Self-recursive variants are pointers here, so
// the pointer case dereferences first.
fn cx_vtag(v: anytype) i64 {
    return switch (@typeInfo(@TypeOf(v))) {
        .pointer => @intCast(@intFromEnum(v.*)),
        else => @intCast(@intFromEnum(v)),
    };
}
fn cx_buf_write_byte(b: i64, off: i64, v: i64) i64 {
    cx_buf_want(b + off + 1);
    cx_heap_mem[@intCast(b + off)] = @intCast(@mod(v, 256));
    return off + 1;
}
fn cx_buf_write_bytes(b: i64, off: i64, vs: anytype) i64 {
    const n: i64 = @intCast(vs.items.items.len);
    cx_buf_want(b + off + n);
    for (vs.items.items, 0..) |v, i| cx_heap_mem[@as(usize, @intCast(b + off)) + i] = @intCast(@mod(v, 256));
    return off + n;
}
fn cx_peek_byte(b: i64, off: i64) i64 {
    cx_buf_want(b + off + 1);
    return cx_heap_mem[@intCast(b + off)];
}
fn cx_buf_read_bytes(b: i64, off: i64, n: i64) *CxList(i64) {
    cx_buf_want(b + off + n);
    const l = cx_ll_empty(i64);
    l.items.ensureTotalCapacity(cx_gpa, @intCast(n)) catch @panic("oom");
    var cx_j: i64 = 0;
    while (cx_j < n) : (cx_j += 1) l.items.appendAssumeCapacity(cx_heap_mem[@as(usize, @intCast(b + off + cx_j))]);
    return l;
}
fn cx_shru(a: i64, b: i64) i64 {
    return @bitCast(@as(u64, @bitCast(a)) >> @as(u6, @intCast(b & 63)));
}
// int-mod is Euclidean, so the result lands in [0, |b|) regardless of
// either sign, where @rem takes the dividend's sign.
fn cx_mod(a: i64, b: i64) i64 {
    const m = if (b < 0) -b else b;
    const r = @rem(a, m);
    return if (r < 0) r + m else r;
}
fn cx_text_eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}
// Classification is banded in CCE: 13..64 are the ASCII letters, 65..96
// the punctuation between, 97..127 the accented Latin and Cyrillic
// letters, 3..12 the digits -- the same two-band test bare metal's
// emit-is-letter-builtin encodes.
fn cx_is_letter(c: i64) bool {
    return (c >= 13 and c <= 64) or (c >= 97 and c <= 127);
}
fn cx_is_digit(c: i64) bool {
    return c >= 3 and c <= 12;
}
fn cx_new(v: anytype) *@TypeOf(v) {
    const p = cx_gpa.create(@TypeOf(v)) catch @panic("oom");
    p.* = v;
    return p;
}
// An accumulator loop appends to the frontier block, and the bytes
// just past it are free. Growing there leaves every existing holder of
// `a` seeing the same bytes -- text is immutable and nothing before
// a.len is written -- so the loop costs n instead of n(n+1)/2. Bare
// metal reaches the same asymptotics from the other side, statically:
// is-inplace-append (X86_64.codex:2376) recognises a tail-recursive
// accumulator parameter and calls __str_concat_inplace. That analysis
// needs TCO state this emitter does not track, and it does not need to:
// on a bump frontier the same question is one pointer comparison at run
// time. Measured 2026-08-21 with findings/probe-memory-model.codex,
// text accumulation at n = 64/128/256: 2080/8256/32896 bytes before
// (exactly n(n+1)/2), 64/128/256 after, against bare metal 72/136/264.
// No empty short-circuit. `a & ""` returning `a` is the finding-29 shape:
// bare metal has no such case -- both emit-str-concat-fast-bump and
// emit-str-concat-slow-alloc bump r10 unconditionally, so the result is
// always a fresh block at the live cursor -- and an aliased return inside a
// deck extent yields a value that looks decked and is not. Falling through
// costs an empty allocation and buys the guarantee.
fn cx_concat(a: []const u8, b: []const u8) []const u8 {
    if (a.len != 0) {
        const cx_base = @intFromPtr(cx_heap_base());
        const cx_ap = @intFromPtr(a.ptr);
        if (cx_ap >= cx_base and cx_ap - cx_base + a.len == @as(usize, @intCast(cx_hp))) {
            const cx_tail = cx_gpa.alloc(u8, b.len) catch @panic("oom");
            @memcpy(cx_tail, b);
            return a.ptr[0 .. a.len + b.len];
        }
    }
    return std.mem.concat(cx_gpa, u8, &.{ a, b }) catch @panic("oom");
}
fn cx_text_starts_with(s: []const u8, p: []const u8) bool {
    return std.mem.startsWith(u8, s, p);
}
fn cx_text_contains(h: []const u8, n: []const u8) bool {
    return std.mem.indexOf(u8, h, n) != null;
}
fn cx_text_concat_list(l: anytype) []const u8 {
    var out = std.ArrayListUnmanaged(u8).empty;
    for (l.items.items) |p| out.appendSlice(cx_gpa, p) catch @panic("oom");
    return out.items;
}
fn cx_list_set_at(l: anytype, i: i64, v: anytype) @TypeOf(l) {
    l.items.items[@intCast(i)] = v;
    return l;
}
// Text is CCE here, so a decimal digit is byte 3 + d and minus is 73;
// parsing this as ASCII would silently read zero.
fn cx_text_to_integer(s: []const u8) i64 {
    var acc: i64 = 0;
    var neg = false;
    for (s, 0..) |b, i| {
        if (i == 0 and b == 73) { neg = true; continue; }
        if (b < 3 or b > 12) break;
        acc = acc *% 10 +% @as(i64, b - 3);
    }
    return if (neg) -%acc else acc;
}
fn cx_text_replace(s: []const u8, a: []const u8, b: []const u8) []const u8 {
    if (a.len == 0) return cx_text_dup(s);
    var out = std.ArrayListUnmanaged(u8).empty;
    var i: usize = 0;
    while (i < s.len) {
        if (i + a.len <= s.len and std.mem.eql(u8, s[i .. i + a.len], a)) {
            out.appendSlice(cx_gpa, b) catch @panic("oom");
            i += a.len;
        } else {
            out.append(cx_gpa, s[i]) catch @panic("oom");
            i += 1;
        }
    }
    return out.items;
}
fn cx_text_split(s: []const u8, sep: []const u8) *CxList([]const u8) {
    const out = cx_ll_empty([]const u8);
    if (sep.len == 0) {
        _ = cx_ll_push(out, cx_text_dup(s));
        return out;
    }
    var start: usize = 0;
    while (std.mem.indexOfPos(u8, s, start, sep)) |p| {
        _ = cx_ll_push(out, cx_text_dup(s[start..p]));
        start = p + sep.len;
    }
    _ = cx_ll_push(out, cx_text_dup(s[start..]));
    return out;
}
const cce_table = [128]u32{ 0, 10, 32, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 101, 116, 97, 111, 105, 110, 115, 104, 114, 100, 108, 99, 117, 109, 119, 102, 103, 121, 112, 98, 118, 107, 106, 120, 113, 122, 69, 84, 65, 79, 73, 78, 83, 72, 82, 68, 76, 67, 85, 77, 87, 70, 71, 89, 80, 66, 86, 75, 74, 88, 81, 90, 46, 44, 33, 63, 58, 59, 39, 34, 45, 40, 41, 43, 61, 42, 60, 62, 47, 64, 35, 38, 95, 92, 124, 91, 93, 123, 125, 126, 96, 94, 36, 37, 233, 232, 234, 235, 225, 224, 226, 228, 243, 244, 246, 250, 252, 241, 231, 237, 1072, 1086, 1077, 1080, 1085, 1090, 1089, 1088, 1074, 1083, 1082, 1084, 1076, 1087, 1091 };
// The multi-byte tiers, from Foreword CCE (which the compiler inlines in
// X86_64State): codes 128..2175 frame as two bytes and name eleven
// tier-1 unicode blocks; codes 2176..67711 frame as three bytes and name
// ten tier-2 blocks, code bases running cumulatively from 2176. The
// single-byte table wins any overlap (accented Latin, Cyrillic) because
// it is scanned first, as from-unicode scans tier 0 first.
const cce_t1_uni = [11]u32{ 128, 1024, 880, 1536, 1424, 2304, 3584, 4352, 19968, 12352, 8704 };
const cce_t1_size = [11]u32{ 256, 128, 128, 128, 128, 128, 128, 128, 512, 256, 128 };
const cce_t1_code = [11]u32{ 128, 384, 512, 640, 768, 896, 1024, 1152, 1280, 1792, 2048 };
const cce_t2_uni = [10]u32{ 12288, 12352, 12448, 19968, 13312, 44032, 3584, 8192, 127744, 9728 };
const cce_t2_size = [10]u32{ 64, 96, 96, 20992, 6592, 11172, 256, 512, 1024, 256 };
fn cx_cce_to_cp(c: i64) i64 {
    if (c < 0) return 65533;
    if (c < 128) return @intCast(cce_table[@intCast(c)]);
    if (c < 67712) {
        const v: u32 = @intCast(c);
        if (v < 2176) {
            for (cce_t1_code, cce_t1_size, cce_t1_uni) |start, size, uni| {
                if (v >= start and v < start + size) return @intCast(uni + (v - start));
            }
            return 65533;
        }
        var base: u32 = 2176;
        for (cce_t2_uni, cce_t2_size) |uni, size| {
            if (v >= base and v < base + size) return @intCast(uni + (v - base));
            base += size;
        }
    }
    return 65533;
}
// A codepoint no tier covers becomes `?`, CCE 68. Bare metal does
// exactly this and does it silently -- asked for char-code-at on U+22A2
// it answers 68, text-length 1, and prints `?` on the way out. The
// substitution is lossy and is upstream's choice, not ours; refusing
// instead made the native loop abort five seconds into the 2.5 MB fibx
// subject over one turnstile in type-theory prose, while bare metal
// compiled the same file. Matching the code matters as much as matching
// the policy: the encoding is observable, so a different substitute
// diverges on every text that carries an uncovered character.
fn cx_cp_to_cce(cp: i64) i64 {
    for (cce_table, 0..) |u, i| {
        if (u == cp) return @intCast(i);
    }
    const u: u32 = @intCast(cp);
    for (cce_t1_code, cce_t1_size, cce_t1_uni) |start, size, uni| {
        if (u >= uni and u < uni + size) return @intCast(start + (u - uni));
    }
    var base: u32 = 2176;
    for (cce_t2_uni, cce_t2_size) |uni, size| {
        if (u >= uni and u < uni + size) return @intCast(base + (u - uni));
        base += size;
    }
    return 68;
}
fn cx_cce_frame(code: i64, out: *std.ArrayListUnmanaged(u8)) void {
    const al = cx_gpa;
    const c: u32 = @intCast(code);
    if (c < 128) {
        out.append(al, @intCast(c)) catch @panic("oom");
    } else if (c < 2176) {
        const v = c - 128;
        out.append(al, @intCast(192 + (v >> 6))) catch @panic("oom");
        out.append(al, @intCast(128 + (v & 63))) catch @panic("oom");
    } else if (c < 67712) {
        const v = c - 2176;
        out.append(al, @intCast(224 + (v >> 12))) catch @panic("oom");
        out.append(al, @intCast(128 + ((v >> 6) & 63))) catch @panic("oom");
        out.append(al, @intCast(128 + (v & 63))) catch @panic("oom");
    } else {
        const v = c - 67712;
        out.append(al, @intCast(240 + (v >> 18))) catch @panic("oom");
        out.append(al, @intCast(128 + ((v >> 12) & 63))) catch @panic("oom");
        out.append(al, @intCast(128 + ((v >> 6) & 63))) catch @panic("oom");
        out.append(al, @intCast(128 + (v & 63))) catch @panic("oom");
    }
}
fn cx_cce_to_utf8(s: []const u8) []const u8 {
    var out: std.ArrayListUnmanaged(u8) = .empty;
    const al = cx_gpa;
    var i: usize = 0;
    while (i < s.len) {
        const b0: i64 = s[i];
        var code: i64 = b0;
        if (b0 & 128 == 0) {
            i += 1;
        } else if (b0 & 224 == 192) {
            code = 128 + ((b0 & 31) << 6) + (s[i + 1] & 63);
            i += 2;
        } else if (b0 & 240 == 224) {
            code = 2176 + ((b0 & 15) << 12) + (@as(i64, s[i + 1] & 63) << 6) + (s[i + 2] & 63);
            i += 3;
        } else {
            code = 67712 + ((b0 & 7) << 18) + (@as(i64, s[i + 1] & 63) << 12) + (@as(i64, s[i + 2] & 63) << 6) + (s[i + 3] & 63);
            i += 4;
        }
        const cp: u32 = @intCast(cx_cce_to_cp(code));
        if (cp < 128) {
            out.append(al, @intCast(cp)) catch @panic("oom");
        } else if (cp < 2048) {
            out.append(al, @intCast(192 + (cp >> 6))) catch @panic("oom");
            out.append(al, @intCast(128 + (cp & 63))) catch @panic("oom");
        } else if (cp < 65536) {
            out.append(al, @intCast(224 + (cp >> 12))) catch @panic("oom");
            out.append(al, @intCast(128 + ((cp >> 6) & 63))) catch @panic("oom");
            out.append(al, @intCast(128 + (cp & 63))) catch @panic("oom");
        } else {
            out.append(al, @intCast(240 + (cp >> 18))) catch @panic("oom");
            out.append(al, @intCast(128 + ((cp >> 12) & 63))) catch @panic("oom");
            out.append(al, @intCast(128 + ((cp >> 6) & 63))) catch @panic("oom");
            out.append(al, @intCast(128 + (cp & 63))) catch @panic("oom");
        }
    }
    return out.items;
}
// One allocation, not two: the digits land in a stack scratch first
// (i64 needs at most 20 bytes), then the CCE translation is the only
// heap object. The double allocation left the ASCII copy stranded on
// the frontier where it blocked in-place extension of whatever grew
// next.
fn cx_show_int(n: i64) []const u8 {
    var cx_tmp: [24]u8 = undefined;
    const ascii = std.fmt.bufPrint(&cx_tmp, "{d}", .{n}) catch unreachable;
    const buf = cx_gpa.alloc(u8, ascii.len) catch @panic("oom");
    for (ascii, 0..) |cx_ch, cx_i| {
        buf[cx_i] = if (cx_ch == '-') 73 else 3 + (cx_ch - '0');
    }
    return buf;
}
fn cx_print_line(s: []const u8) void {
    std.debug.print("{s}\n", .{cx_cce_to_utf8(s)});
}
fn cx_print(s: []const u8) void {
    std.debug.print("{s}", .{cx_cce_to_utf8(s)});
}

fn Tup2(comptime a_: type, comptime b_: type) type {
    return union(enum) {
    MkTup2: struct { a_, b_ },
    };
}

fn Tup3(comptime a_: type, comptime b_: type, comptime c_: type) type {
    return union(enum) {
    MkTup3: struct { a_, b_, c_ },
    };
}

fn Tup4(comptime a_: type, comptime b_: type, comptime c_: type, comptime d_: type) type {
    return union(enum) {
    MkTup4: struct { a_, b_, c_, d_ },
    };
}

fn Tup5(comptime a_: type, comptime b_: type, comptime c_: type, comptime d_: type, comptime e_: type) type {
    return union(enum) {
    MkTup5: struct { a_, b_, c_, d_, e_ },
    };
}

const ScoreS = struct {
    v_: i64,
};
const Score = *ScoreS;

fn fib(n_: i64) i64 {
    return (if ((n_ < 2)) n_ else (fib((n_ -% 1)) +% fib((n_ -% 2))));
}

fn sum_to(n_: i64) i64 {
    return @as(i64, (if ((n_ == 0)) 0 else (n_ +% sum_to((n_ -% 1)))));
}

fn triple(x: i64) i64 {
    return (x *% 3);
}

fn size_of(n_: i64) []const u8 {
    return switch (n_) { 0 => "\x12\x10\x12\x0d", 1 => "\x10\x12\x0d", else => (if ((n_ < 10)) "\x1c\x0d\x1b" else "\x1a\x0f\x12\x1e"),  };
}

fn q_abs(x: i64) i64 {
    return (if ((x < 0)) (-%x) else x);
}

fn q_ok(row: i64, placed: *CxList(i64), i_: i64) bool {
    var _tl_i = i_;
    while (true) {
        if ((_tl_i == cx_list_len(placed))) { return true; } else { const r_: i64 = cx_list_at(placed, _tl_i); if ((r_ == row)) { return false; } else { if ((q_abs((r_ -% row)) == (_tl_i +% 1))) { return false; } else { { const _tj4_2 = (_tl_i +% 1); _tl_i = _tj4_2; continue; } } } }
    }
}

fn q_rows(row: i64, placed: *CxList(i64)) i64 {
    return @as(i64, (if ((row > 8)) 0 else b1: { const here: i64 = @as(i64, (if (q_ok(row, placed, 0)) q_solve(cx_ll_concat(cx_ll_of(i64, &[_]i64{ row }), placed)) else 0)); break :b1 (here +% q_rows((row +% 1), placed)); }));
}

fn q_solve(placed: *CxList(i64)) i64 {
    return @as(i64, (if ((cx_list_len(placed) == 8)) 1 else q_rows(1, placed)));
}

fn opening() void {
    return b0: { _ = cx_print_line("\x14\x0d\x17\x17\x10\x42\x02\x1b\x10\x15\x17\x16"); _ = cx_print_line(cx_concat("\x13\x11\x24\x49\x0e\x11\x1a\x0d\x13\x49\x13\x0d\x21\x0d\x12\x45\x02", cx_show_int((6 *% 7)))); _ = cx_print_line(cx_concat("\x0d\x11\x1d\x14\x0e\x49\x25\x19\x0d\x0d\x12\x13\x45\x02", cx_show_int(q_solve(cx_ll_empty(i64))))); _ = cx_print_line(cx_concat("\x1c\x11\x20\x49\x04\x08\x45\x02", cx_show_int(fib(15)))); _ = cx_print_line(cx_concat("\x13\x19\x1a\x49\x0e\x10\x49\x04\x03\x03\x45\x02", cx_show_int(sum_to(100)))); _ = cx_print_line(cx_concat("\x0e\x1b\x11\x18\x0d\x49\x0e\x15\x11\x1f\x17\x0d\x49\x0a\x45\x02", cx_show_int(triple(triple(7))))); _ = cx_print_line(cx_concat(cx_concat(cx_concat(cx_concat(cx_concat(cx_concat(cx_concat("\x13\x11\x26\x0d\x49\x10\x1c\x45\x02", size_of(0)), "\x51"), size_of(1)), "\x51"), size_of(5)), "\x51"), size_of(50))); _ = cx_print_line(cx_concat("\x18\x17\x0f\x1a\x1f\x0d\x16\x49\x05\x08\x03\x45\x02", cx_show_int((cx_new(ScoreS{ .v_ = std.math.clamp(250, 0, 100) })).v_))); _ = b1: { const xs = cx_ll_concat(cx_ll_of(i64, &[_]i64{ 1, 2, 3 }), cx_ll_of(i64, &[_]i64{ 4, 5 })); break :b1 cx_print_line(cx_concat("\x17\x11\x13\x0e\x49\x17\x0d\x12\x1d\x0e\x14\x45\x02", cx_show_int(cx_list_len(xs)))); }; break :b0; };
}

fn cx_entry() void {
    opening();
}

pub fn main() void {
    const stack_bytes: usize = 512 * 1024 * 1024;
    const t = std.Thread.spawn(.{ .stack_size = stack_bytes }, cx_entry, .{}) catch @panic("spawn");
    t.join();
}
