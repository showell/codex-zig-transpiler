# SENT as PR 127 — mcopy-type reads its tag with variant-tag

https://github.com/damiant3/Cobblestone/pull/127

Branch `mcopy-type-variant-tag` off `675a0775` (Update 55), one commit,
cherry-picked clean. Backlog row `Ladder: mcopy-tag-read-126`.

---

## What it changes

`mcopy-type` validates a box by reading a tag out of word 0:

```
   else if peek-qword a 0 < 0 then ErrorTy
   else if peek-qword a 0 > 28 then ErrorTy
```

28 is the `CodexType` variant count, so this is a range check on a tag. Word
0 **is** the tag on bare metal, where a variant's first word is its tag. It
is a **payload** word on any target whose unions lay themselves out
differently. The zig plug's read comes back a pointer, fails `> 28`, and
every type this touches escapes to `ErrorTy`.

The escape is silent: `check-errors` stays 0, so nothing reports it. The
compact then copies nothing and the originals are reclaimed behind it, so the
damage surfaces later and somewhere else.

The fix asks the question with the builtin that answers it:

```
   else if variant-tag ty < 0 then ErrorTy
   else if variant-tag ty > 28 then ErrorTy
```

## Why bare metal is unaffected

`emit-variant-tag-builtin` (`Emit/X86_64Builtins.codex:170`) emits
`mov-load rd, r, 0` — a 64-bit load from offset 0 of the value. `address-of`
is `emit-identity-builtin`, so `peek-qword a 0` is the same 64-bit load from
the same address. The two are the same instruction on this target.

The dereference needs `ty` to be non-null and in the copied region, and the
two guards immediately above (`a == 0`, `a < mc.mc-floor`) already establish
both before either branch is reached.

## Precedent

`Emit/X86_64Compound.codex` moved off this exact idiom already. Its comment
says it used to read the tag with `peek-qword (address-of ty) 0`, "which is
the same load on bare metal but silently answers 0 on any target where
`address-of` cannot be modelled: that cost the C# arm every tag in this
table." That fix was applied to the walker. This is the same mistake in the
copier.

## What it is measured to fix

On the zig arm at U56, with a harness that calls `compile-frontend-cdx`:

| | before | after |
|---|---|---|
| escapes on a 7-line subject | 3 × `FunTy -> ErrorTy` | 0 |
| every definition's type | `error` | correct |
| `fib` transpiled | garbage — `@compileError("no zig type")` in the signature | **byte-identical** to the known-good `fib.zig` (14,877 bytes) |
| a 388 KB subject | crash | 556,955 bytes, 690 functions |

With one further zig-plug change (not in this PR — it depends on our emitter
split), the transpiler's fixed point holds: pass 1 under QEMU and pass 2 as a
native binary both 2,932,307 bytes, byte-identical, and the sample program
matches its expected output on all 9 lines.

## Relationship to issue 126

Issue 126 reported that the plug-built compiler types every comparison
`error` where bare metal says `boolean`, and we assessed it as inert because
`fib`'s single comparison did not change the emitted zig. **This is its root,
and it is not inert.** It is not one comparison — it is every type the copier
touches, and the reason it looked inert is that the copy was being discarded
anyway on the arm we measured.

## What we have not checked

Whether the C# and wasm arms improve. We have not run them.


🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01VpLJYCGhn1N3qkbuSU1k6s
