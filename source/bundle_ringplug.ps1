# The ring-fed zig plug: the emitter as a bootable kernel.
#
# This is the bootstrap half. The seed compiler emits x86, not zig, so the
# only way to get zig out of a bare-metal compile is to compile the EMITTER
# to a kernel first and then feed IR to it. That kernel is this bundle.
#
# Same declarations, parser and emitter as the checkout's own
# plugs/zig/build.ps1, with ZigPlugRing as the body instead of ZigPlug -- no
# Net or Kernel chapters, because the intake is the serial ring the compiler
# itself reads from rather than a TCP stack.
param([string]$OutFile)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$repo = (& python3 (Join-Path $here '..' 'cobblestone.py')).Trim()

. "$repo/codex/plugs/common/plug-build-lib.ps1"

$lines = [System.Collections.Generic.List[string]]::new()
foreach ($decl in @('codex/compiler/Core/Name.codex',
                    'codex/compiler/Core/SourceText.codex',
                    'codex/compiler/Types/CodexType.codex',
                    'codex/compiler/Ast/AstNodes.codex',
                    'codex/compiler/IR/IRChapter.codex')) {
    # AstNodes' 'Deck Copies' section duplicates PhaseAllocator helpers that
    # a plug bundle reaches another way; a duplicate type is CDX3001.
    $drop = if ($decl -like '*AstNodes.codex') { @('Deck Copies') } else { @() }
    Add-PlugChapter -Lines $lines -Path (Join-Path $repo $decl) -Quire 'Zig' -DropSections $drop
}
# THE COMPILER CHAPTERS THE PLUG RUNS, READ FROM THE CHECKOUT, for the same
# reason as the pages below. U62's zig plug began calling IR\ConstShare
# (COMPILER-86) and plugs/zig/build.ps1 grew `-CompilerChapters` for it; a list
# kept here compiles the U62 ring plug to "Undefined name: shared-const-names".
# Same place in the order as Build-TranspilerPlug: after the IR declarations.
$zigBuild = Get-Content -Raw (Join-Path $repo 'codex/plugs/zig/build.ps1')
if ($zigBuild -match '-CompilerChapters\s+@\(([^)]*)\)') {
    foreach ($cc in [regex]::Matches($Matches[1], "'([^']+)'")) {
        $rel = $cc.Groups[1].Value -replace '\\', '/'
        Add-PlugChapter -Lines $lines -Path (Join-Path $repo "codex/compiler/$rel.codex") -Quire 'Zig'
    }
}
# PlugTypes IS carried here, unlike in the transpiler subject: this bundle has
# no compiler under it, so its copies of ApplyChain and strip-fun-args are the
# only ones present rather than duplicates of the compiler's.
Add-PlugChapter -Lines $lines -Path (Join-Path $repo 'codex/plugs/common/PlugTypes.codex') -Quire 'Zig'
Add-PlugChapter -Lines $lines -Path (Join-Path $repo 'codex/plugs/common/IRTextParser.codex') -Quire 'Zig'
# EVERY PAGE OF Chapter: Zig Emitter, READ FROM THE CHECKOUT. A bundle short
# a page comes back from the seed as undefined names for every definition on
# it, so the page set must come from the checkout being bundled rather than
# from a list kept here, which is right for one checkout and wrong for the
# next. zig-plug-pages.ps1 reads the chapter's own `Page N of M` footers.
. (Join-Path $PSScriptRoot 'zig-plug-pages.ps1')
foreach ($zp in (Get-ZigEmitterPages -Repo $repo)) {
    Add-PlugChapter -Lines $lines -Path (Join-Path $repo "codex/plugs/zig/$($zp).codex") -Quire 'Zig'
}
Add-PlugChapter -Lines $lines -Path (Join-Path $here 'ZigPlugRing.codex') -Quire 'Zig'

$preLines = Resolve-PlugForewords $lines
Bundle-PlugSource -PreLines $preLines -Lines $lines -BundleSrc $OutFile -PlugName 'ringplug'
