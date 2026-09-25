# The transpiler subject: the hosted compiler's chapter set, plus the zig
# emitter, plus the IR text parser, behind CodexZigHarness.
#
# The list is flat on purpose. Upstream reaches it through three nested
# bundlers because a dozen other subjects share prefixes of it; here there
# is one subject, so nesting would buy nothing and cost a reader two hops.
#
# Add-PlugChapter, Resolve-PlugForewords and Bundle-PlugSource come from the
# CHECKOUT's own plug-build-lib.ps1. That is deliberate: bundling resolves
# foreword cites and assembles quires by upstream's rules, and a
# reimplementation here would be a fork that drifts silently.
#
# IRTextParser IS carried, and that was the whole argument. The seam looks
# like it could skip the parser -- emit-zig-chapter takes the compiler's own
# IRChapter, so the front end holds the value already -- but the text wire
# DERIVES what the AST does not carry (IRTextEmitter.codex:404-406 infers a
# record's implicit type parameters from its field types as it serialises),
# and a direct hand-off emits zig that does not compile for any type declared
# the way foreword/core/Sort.codex declares SortPartition. Going through the
# wire in memory also makes this program the same code in the same order as
# a codexir | zigemit pipeline.
#
# NOT PlugTypes, and that one is measured rather than assumed. It has two
# sections and this bundle needs neither. Emitter Helpers: ApplyChain and
# collect-apply-chain are in Emit/CodexEmitter.codex and strip-fun-args in
# Types/CodexTypeHelpers.codex -- and ApplyChain would FORCE the issue, since
# a duplicate type is CDX3001. Plug Utilities: bytes-to-text* are called only
# by ZigPlug.codex, a body this bundle does not carry, and deck-record is a
# second identity copy of Core/PhaseAllocator.codex's.
#
# That deck-record copy is the one worth naming. X86_64Chapter.codex:1155-1157
# sets deck-record-intrinsic from `pa-slug == dr-slug` -- init-phase-allocator
# and deck-record resolving to the SAME chapter. A second deck-record in the
# subject makes which chapter dr-slug names depend on scan order. That exact
# condition, switched the wrong way, once turned the deck discipline off
# across a whole bundled compiler and stayed invisible for thirteen rungs.
# ZigEmitter never CALLS deck-record -- it intercepts the name while emitting
# -- so dropping the copy costs nothing.
#
# One source difference from the standalone plug remains, and it is INERT
# statically, for every program. The compiler's strip-fun-args
# (Types/CodexTypeHelpers.codex) carries an `is ForAllEff (id) (body)` arm
# that PlugTypes' copy lacks, and this bundle carries the compiler's. But
# strip-fun-args has NO call site in the emitter: the only emitter-side
# caller is strip-fun-args-emitter, a different function, and the one real
# caller is X86_64Chapter.codex, which the zig emitter never runs. So the arm
# cannot reach the emitted bytes and no oracle is needed to say so.
param([string]$OutFile)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$repo = (& python3 (Join-Path $here '..' 'cobblestone.py')).Trim()

. "$repo/codex/plugs/common/plug-build-lib.ps1"

$lines = [System.Collections.Generic.List[string]]::new()

# CCE is NOT listed. plug-build-lib carries a foreword chapter automatically
# once something cites it, and this bundle cites it, so listing it as well
# puts CCE in twice -- once as Foreword--CCE and once as Parsmi--CCE, two
# quires holding every definition in it. Duplicate VALUES only warn (CDX3006,
# easy to read past); CharClass is a TYPE, and a duplicate type is CDX3001, a
# hard error. ListUtils is omitted for the same reason: Core/Collections.codex
# cites Foreword chapter ListUtils.
#
# THE COMPILER'S CHAPTERS COME FROM THE CHECKOUT: build/compiler-order.txt, in
# its order. Upstream's concat-codex-self.ps1 refuses any .codex under
# codex/compiler without a row there, so it is the whole compiler by
# construction, the driver (Chapter: Opening) included -- the harness calls it.
# What is kept HERE is only what we leave out, each with its reason, so a
# chapter upstream adds arrives without an edit on this side. U62 added
# IR/ConstShare and IR/MethodSpecialization, read without a cite by chapters
# this list used to name one by one.
#
# The foreword chapters opening.codex cites (Maybe, Wrap64, Fat16, ImportGate,
# FactDisk) are NOT carried here, for the same reason CCE is not:
# plug-build-lib brings a cited foreword chapter as Foreword--<name>. Listed
# here they were Parsmi--<name>, which plug-build-lib counts as present and the
# checkout's build/compile.ps1 does not -- its resolver asks for a
# Foreword--<name> header when the file exists -- so the unit compile.ps1 would
# hand the seed carried each chapter twice.
$leftOut = @{
    # BootPaintStubs.codex stands in, below, and says why it is a stub.
    'codex/compiler/Core/BootPaint.codex' = $true
    # The harness is the entry point: it defines `opening`.
    'codex/compiler/EntryPoint.codex' = $true
}
$orderFile = Join-Path $repo 'build/compiler-order.txt'
$order = Get-Content $orderFile | ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { $_ -replace '\\', '/' }
foreach ($known in $leftOut.Keys) {
    if ($order -notcontains $known) { throw "$known has no row in $orderFile -- upstream moved it; read their change before editing this list" }
}
foreach ($ch in $order) {
    if ($leftOut.ContainsKey($ch)) { continue }
    Add-PlugChapter -Lines $lines -Path (Join-Path $repo $ch) -Quire 'Parsmi'
}
Add-PlugChapter -Lines $lines -Path (Join-Path $repo 'codex/plugs/common/IRTextParser.codex') -Quire 'Parsmi'

# EVERY PAGE OF Chapter: Zig Emitter, READ FROM THE CHECKOUT. A bundle short
# a page comes back from the seed as undefined names for every definition on
# it, so the page set must come from the checkout being bundled rather than
# from a list kept here, which is right for one checkout and wrong for the
# next. zig-plug-pages.ps1 reads the chapter's own `Page N of M` footers.
. (Join-Path $PSScriptRoot 'zig-plug-pages.ps1')
foreach ($zp in (Get-ZigEmitterPages -Repo $repo)) {
    Add-PlugChapter -Lines $lines -Path (Join-Path $repo "codex/plugs/zig/$($zp).codex") -Quire 'Parsmi'
}

# Update 42 gave PhaseAllocator a cite of Codex chapter BootPaint, and a cite
# names a chapter rather than a symbol, so a subject carrying PhaseAllocator
# must answer for one. BootPaintStubs.codex says why it is a stub.
Add-PlugChapter -Lines $lines -Path (Join-Path $here 'BootPaintStubs.codex') -Quire 'Parsmi'
Add-PlugChapter -Lines $lines -Path (Join-Path $here 'CodexZigHarness.codex') -Quire 'Parsmi'

# All 14 pages of the X86-64 Code Generator chapter are present, so the
# 'Page N of 14' trailers stand as upstream wrote them. Upstream rewrites
# them because its smaller subjects carry a SUBSET of the pages; this one
# never does, so there is nothing to renumber.

$preLines = Resolve-PlugForewords $lines
Bundle-PlugSource -PreLines $preLines -Lines $lines -BundleSrc $OutFile -PlugName 'codexzig-subject'
