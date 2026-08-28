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
foreach ($ch in @('codex/compiler/Core/OffsetTable.codex',
                  'codex/compiler/Core/VmProfile.codex',
                  'codex/compiler/Types/Builtins.codex',
                  'codex/compiler/IR/Lir.codex',
                  'codex/compiler/Emit/EmitAllocator.codex',
                  'codex/compiler/Emit/CdxWriter.codex',
                  'codex/compiler/Emit/X86_64Boot.codex',
                  'codex/compiler/Emit/X86_64Encoder.codex',
                  'codex/compiler/Emit/X86_64State.codex',
                  'codex/compiler/Emit/X86_64.codex',
                  'codex/compiler/Emit/X86_64Builtins.codex',
                  'codex/compiler/Emit/X86_64Chapter.codex',
                  'codex/compiler/Emit/X86_64Compound.codex',
                  'codex/compiler/Emit/X86_64Helpers.codex',
                  'codex/compiler/Emit/X86_64IO.codex',
                  'codex/compiler/Emit/X86_64IPCHelpers.codex',
                  'codex/compiler/Emit/X86_64InsnCount.codex',
                  'codex/compiler/Emit/X86_64Lir.codex',
                  'codex/compiler/Emit/X86_64ListHelpers.codex',
                  'codex/compiler/Emit/X86_64ProcessHelpers.codex',
                  'codex/compiler/Emit/X86_64TextHelpers.codex',
                  'codex/compiler/Core/BuildSettings.codex',
                  'codex/compiler/Core/Phase.codex',
                  'codex/compiler/Core/PhaseAllocator.codex',
                  'codex/compiler/Core/TextFormat.codex',
                  'codex/compiler/Core/CdxCodes.codex',
                  'codex/compiler/Core/Severity.codex',
                  'codex/compiler/Core/SourceText.codex',
                  'codex/compiler/Core/Name.codex',
                  'codex/compiler/Core/Diagnostic.codex',
                  'codex/compiler/Core/DiagnosticBag.codex',
                  'codex/compiler/Core/Collections.codex',
                  'codex/compiler/Types/CodexType.codex',
                  'codex/compiler/Types/CodexTypeHelpers.codex',
                  'codex/compiler/IR/IRChapter.codex',
                  'codex/compiler/Syntax/Token.codex',
                  'codex/compiler/Syntax/Lexer.codex',
                  'codex/compiler/Syntax/SyntaxNodes.codex',
                  'codex/compiler/Syntax/ParserCore.codex',
                  'codex/compiler/Syntax/ParserExpressions.codex',
                  'codex/compiler/Syntax/Parser.codex',
                  'codex/compiler/Ast/AstNodes.codex',
                  'codex/compiler/Ast/Desugarer.codex',
                  'codex/compiler/Core/SkipListText.codex',
                  'codex/compiler/Semantics/ChapterScoper.codex',
                  'codex/compiler/Semantics/NameResolver.codex',
                  'codex/compiler/Types/CodexTypeTree.codex',
                  'codex/compiler/Types/TypeEnv.codex',
                  'codex/compiler/Types/Unifier.codex',
                  'codex/compiler/Types/TypeChecker.codex',
                  'codex/compiler/Types/TypeCheckerInference.codex',
                  'codex/compiler/IR/LoweringTypes.codex',
                  'codex/compiler/IR/Lowering.codex',
                  'codex/compiler/IR/ResolveTypes.codex',
                  'codex/compiler/Emit/IRTextEmitter.codex',
                  'codex/compiler/IR/Occurrence.codex',
                  'codex/compiler/IR/IRCheck.codex',
                  'codex/compiler/IR/LambdaLifting.codex',
                  'codex/compiler/IR/Simplify.codex',
                  'codex/compiler/IR/Passes.codex',
                  'codex/compiler/IR/LirTargets.codex',
                  'codex/compiler/Emit/CodexEmitter.codex',
                  'codex/plugs/common/IRTextParser.codex',
                  'codex/plugs/zig/ZigEmitter.codex')) {
    Add-PlugChapter -Lines $lines -Path (Join-Path $repo $ch) -Quire 'Parsmi'
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
