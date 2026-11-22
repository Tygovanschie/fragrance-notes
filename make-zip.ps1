# Builds the Chrome Web Store zip from an explicit list of files, so notes, the website (site/)
# and the server (server/) never end up in it. Run from anywhere: .\make-zip.ps1
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$version = (Get-Content (Join-Path $root 'manifest.json') -Raw | ConvertFrom-Json).version
$out = Join-Path (Split-Path $root -Parent) "fragrance-notes-$version.zip"
$stage = Join-Path ([IO.Path]::GetTempPath()) 'fragrance-notes-zip'

# Everything the extension needs, and nothing else.
$include = @('manifest.json', 'LICENSE', 'fonts.css', '*.js', '*.html', 'icons', 'fonts')

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory $stage | Out-Null
foreach ($pattern in $include) {
  Get-Item (Join-Path $root $pattern) | ForEach-Object { Copy-Item $_.FullName -Destination $stage -Recurse }
}
if (Test-Path $out) { Remove-Item $out }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $out
Remove-Item $stage -Recurse -Force
Write-Host "Made $out"
Get-ChildItem $out | Select-Object Name, @{ n = 'KB'; e = { [math]::Round($_.Length / 1KB) } } | Format-Table -AutoSize
