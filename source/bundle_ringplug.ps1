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

# **UPSTREAM'S OWN BUNDLING, NOT A COPY OF IT.** This used to repeat
# Build-TranspilerPlug's chapter list by hand, and U63 showed what that costs:
# upstream began stripping the declaration chapters' new `cites Codex chapter
# Phase Allocator` (the plug's Plug Types supplies what they cite it for), the
# copy did not, and the ring plug failed to bundle ("quire 'Codex' is not
# registered"). So the zig plug's own build line is read from the checkout
# and Build-TranspilerPlug is called with it, the ring body standing in for
# ZigPlug -- the one thing that differs. Its compile step is Windows tooling
# this repo does not run (the seed compiles the bundle under QEMU), so it is
# replaced after the library is loaded: PowerShell resolves the name at the
# call. cobblestone-qemu's subjects/bundle_ringplug.ps1 is the same change.
function Build-PlugCdx {
    param($BundleSrc, $OutFile, $LogFile, $PlugName, $Survey, $Decks)
}

$zigBuild = Get-Content -Raw (Join-Path $repo 'codex/plugs/zig/build.ps1')
if ($zigBuild -notmatch 'Build-TranspilerPlug\s[^\n]*-Chapters\s+@\(([^)]*)\)') {
    throw "codex/plugs/zig/build.ps1 no longer calls Build-TranspilerPlug with -Chapters; read it before bundling"
}
$zigChapters = @([regex]::Matches($Matches[1], "'([^']+)'") | ForEach-Object { $_.Groups[1].Value })
if ($zigChapters[-1] -ne 'ZigPlug') { throw "the zig plug's body is no longer its last chapter ($($zigChapters -join ', '))" }
$compilerChapters = @()
if ($zigBuild -match '-CompilerChapters\s+@\(([^)]*)\)') {
    $compilerChapters = @([regex]::Matches($Matches[1], "'([^']+)'") | ForEach-Object { $_.Groups[1].Value })
}

# The plug directory Build-TranspilerPlug reads its own chapters from, staged
# outside both trees: upstream's zig chapters, and this repo's body in place
# of ZigPlug. Its build-output lands there too, never in the checkout, and
# the directory goes when the bundle has been copied out.
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("ringplug-plugdir-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
    $chapters = @()
    foreach ($c in $zigChapters[0..($zigChapters.Count - 2)]) {
        Copy-Item (Join-Path $repo "codex/plugs/zig/$c.codex") (Join-Path $stage "$c.codex")
        $chapters += $c
    }
    Copy-Item (Join-Path $here 'ZigPlugRing.codex') (Join-Path $stage 'ZigPlugRing.codex')
    $chapters += 'ZigPlugRing'

    Build-TranspilerPlug -PlugDir $stage -PlugName 'zig' -Chapters $chapters -CompilerChapters $compilerChapters | Out-Host
    Copy-Item (Join-Path $stage 'build-output/plug-source.codex') $OutFile
    Write-Host "[ringplug] bundled by upstream's Build-TranspilerPlug: $($chapters -join ', ')"
} finally {
    Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
}
