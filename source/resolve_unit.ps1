# Put ahead of a bundle what the checkout's build/compile.ps1 puts ahead of its
# source before the seed reads it, and write the result back as the unit.
#
#   pwsh -File resolve_unit.ps1 -File <bundle.codex>
#
# **THE RESOLUTION IS THE CHECKOUT'S, CALLED RATHER THAN COPIED.** compile.ps1
# runs Resolve-CiteOrder over its source and writes Format-CiteChapters' output
# between the mode line and the source; this makes the same two calls from the
# checkout's own build/quire-map.ps1. For a complete bundle that is Foreword
# ListUtils and Tuple: the resolver walks both for EVERY unit, because the
# desugarer writes `map-list` for a `for` and `MkTup<N>` for a tuple, names no
# author cites. A blob of the bundle alone left both out, and the first bundled
# chapter to use `for` (Update 59's Zig emitter) stopped the ring plug with
# CDX3002 on map-list.
#
# IN PLACE, because stage 7 must read what stage 4 read. The unit is the source
# both passes are handed and the blob only adds the envelope. A unit that is
# already resolved has every chapter present, so running this again adds
# nothing.
param([Parameter(Mandatory=$true)] [string]$File)
$ErrorActionPreference = 'Stop'

$repo = & python3 (Join-Path $PSScriptRoot '..' 'cobblestone.py')
if ($LASTEXITCODE -ne 0) { exit 2 }
$repo = "$repo".Trim()
. (Join-Path $repo 'build/quire-map.ps1')

# .NET resolves a relative path against its own working directory, which is
# not the shell's.
$File = (Resolve-Path $File).Path
$srcLines = [System.IO.File]::ReadAllLines($File)
# A bundled chapter carries its quire in its header, and compile.ps1 counts it
# as already seen.
$seedSeen = @{}
foreach ($line in $srcLines) {
    if ($line -match '^Chapter:\s*(\w+)--(.+?)\s*$') { $seedSeen["$($matches[1])::$($matches[2])"] = $true }
}
try {
    $ordered = Resolve-CiteOrder -RootLines $srcLines -Repo $repo -SeedSeen $seedSeen
} catch {
    [Console]::Error.WriteLine("error 3010: $($_.Exception.Message)")
    exit 8
}
# compile.ps1's own warning, kept: anything beyond the two implicit chapters
# is a cite the bundler did not answer.
$implicit = @('ListUtils', 'Tuple')
$unbundled = @($ordered | Where-Object { -not ($_.Quire -eq 'Foreword' -and $implicit -contains $_.Name) })
if ($unbundled.Count -gt 0 -and $seedSeen.Count -gt 0) {
    [Console]::Error.WriteLine("WARNING: resolved $($unbundled.Count) chapter(s) not in the bundle:")
    foreach ($extra in $unbundled) { [Console]::Error.WriteLine("  $($extra.Quire)::$($extra.Name) ($($extra.Path))") }
}

$leaf = Split-Path $File -Leaf
if ($ordered.Count -eq 0) {
    Write-Output "${leaf}: nothing resolved ahead of it"
    exit 0
}
$prelude = Format-CiteChapters -Ordered $ordered
$w = [System.IO.StreamWriter]::new($File, $false, [System.Text.UTF8Encoding]::new($false))
foreach ($l in $prelude) { $w.Write($l); $w.Write("`n") }
foreach ($l in $srcLines) { $w.Write($l); $w.Write("`n") }
$w.Dispose()
$added = ($ordered | ForEach-Object { "$($_.Quire)::$($_.Name)" }) -join ', '
Write-Output "${leaf}: $($prelude.Count) lines resolved ahead of it ($added)"
