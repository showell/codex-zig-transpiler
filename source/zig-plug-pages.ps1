# The pages of Chapter: Zig Emitter, in order, read from the checkout.
#
# A chapter spanning k files foots every page with `Page N of M` (CDX3004), and
# a single-page chapter foots `Page 1`. That footer is the order, written by the
# author of the chapter, so no list is kept beside it to disagree with -- and the
# page count differs between checkouts, so a list is wrong for all but one.
#
# Nothing is guessed. A gap in the numbering, a disagreement about M, or two
# files claiming one page is a REFUSAL: a bundle missing a page comes back from
# the seed as a pile of undefined names rather than as an error out here.

function Get-ZigEmitterPages {
    param([Parameter(Mandatory = $true)][string]$Repo)

    $dir = Join-Path $Repo 'codex/plugs/zig'
    $found = @{}
    $total = $null
    foreach ($f in (Get-ChildItem -Path $dir -Filter *.codex | Sort-Object Name)) {
        $text = Get-Content -Raw -Path $f.FullName
        if ($text -notmatch '(?m)^Chapter:[ \t]*Zig Emitter[ \t]*$') { continue }
        $lines = $text.TrimEnd() -split "`r?`n"
        if ($lines[-1].Trim() -notmatch '^Page[ \t]+(\d+)(?:[ \t]+of[ \t]+(\d+))?$') {
            throw "$($f.Name) declares Chapter: Zig Emitter but its last line is not a page footer: '$($lines[-1].Trim())'"
        }
        $n = [int]$Matches[1]
        $of = if ($Matches[2]) { [int]$Matches[2] } else { 1 }
        if ($found.ContainsKey($n)) { throw "$($f.Name) and $($found[$n]) both claim page $n of Chapter: Zig Emitter" }
        if ($null -eq $total) { $total = $of }
        elseif ($total -ne $of) { throw "pages of Chapter: Zig Emitter disagree about the length of the chapter" }
        $found[$n] = $f.BaseName
    }
    if ($found.Count -eq 0) { throw "no page under $dir declares Chapter: Zig Emitter" }
    if ($found.Count -ne $total) { throw "found $($found.Count) pages of Chapter: Zig Emitter; the footers say $total" }
    1..$total | ForEach-Object { $found[$_] }
}
