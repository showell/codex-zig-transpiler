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
# PlugTypes IS carried here, unlike in the transpiler subject: this bundle has
# no compiler under it, so its copies of ApplyChain and strip-fun-args are the
# only ones present rather than duplicates of the compiler's.
Add-PlugChapter -Lines $lines -Path (Join-Path $repo 'codex/plugs/common/PlugTypes.codex') -Quire 'Zig'
Add-PlugChapter -Lines $lines -Path (Join-Path $repo 'codex/plugs/common/IRTextParser.codex') -Quire 'Zig'
Add-PlugChapter -Lines $lines -Path (Join-Path $repo 'codex/plugs/zig/ZigEmitter.codex') -Quire 'Zig'
Add-PlugChapter -Lines $lines -Path (Join-Path $here 'ZigPlugRing.codex') -Quire 'Zig'

$preLines = Resolve-PlugForewords $lines
Bundle-PlugSource -PreLines $preLines -Lines $lines -BundleSrc $OutFile -PlugName 'ringplug'
