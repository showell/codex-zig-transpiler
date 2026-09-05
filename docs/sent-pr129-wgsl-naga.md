# SENT as PR 129 — wgsl plug: 81 of 81 pass naga

https://github.com/damiant3/Cobblestone/pull/129

Branch `wgsl-firefox-naga` off `675a0775` (Update 55), two commits, no
stack. Backlog row `Ladder: wgsl-firefox-naga`.

---

## Measured at this base, with the plug actually run

| population | before | after |
|---|---|---|
| the 24 gpushow kernels that failed | 0 pass | **24 pass** |
| all 42 gpushow kernels | 18 pass | **42 pass** |
| the whole gate population | 57 of 81 | **81 of 81** |

The 42 regenerated shaders are included. They are generated artifacts and
leaving them stale would leave the gate red after a merge.

## Cause 1 — a tail-call loop leaves the function with no terminator

25 files, 31 functions. Every path inside the loop returns or continues, so
no `break` is emitted; Tint's reachability sees the end is unreachable, and
naga supplies an implicit `return;` that disagrees with the declared type.
`wgsl-emit-loop-helper` now closes with an unreachable return of the zero
value, and `wgsl-zero-text` mirrors `wgsl-ty-text`.

## Cause 2 — a storage pointer cannot be a function parameter

WGSL restricts pointer parameters to the function, private and workgroup
address spaces; `storage` needs `unrestricted_pointer_parameters`, which
Tint implements and naga does not. **The pointer bought nothing**: the
buffers are module-scope `var<storage>` and the entry point already reads
them by name — only helpers took the long way round.

Dropping the parameter is not enough, and the second commit is the rest of
it. A helper names a buffer by **its own** parameter name while the global is
named for the **kernel's**: `ss-gather (buf)` is called `ss-gather gdep`, and
the global is `ssao_step_gdep_buf`. So the emitter needs the caller's
argument, not the callee's parameter, and it needs to know which kernel the
helper serves.

Both are recorded at the call site, where the caller, the callee's parameter
and the argument are all in hand; resolution then walks callee to caller
until it reaches a kernel. **A self-call is not a binding** — a self-recursive
helper passes its own parameter through unchanged, and is usually defined
before the kernel that calls it, so that useless bind would otherwise be the
one found first.

This rests on a property checked over the whole tree: **no helper is called
with more than one kernel's buffers.** A helper reached from two kernels
would need one emission per kernel; there are none, and a second would be
worth a refusal rather than a silently wrong name.

## Cause 3

Not fixed here, and no longer observed: naga 30 accepts the
`bitcast<f32>(...)` constant expressions that were the fourth failure class,
so nothing in the current population fails for it.

## Also here

`apps/gpushow/tools/validate-naga.mjs`, the gate — see its own prose for why
it exists beside `validate-all.mjs`, which is careful about the population
and silent about the oracle.


🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01VpLJYCGhn1N3qkbuSU1k6s
