# Builds the Chrome Web Store zip from an explicit list of files, so notes, the website (site/)
# and the server (server/) never end up in it. Run from anywhere: .\make-zip.ps1
# The zip entries are written here with '/' separators, as the ZIP format requires. (Compress-Archive in
# Windows PowerShell 5.1 writes 'icons\16.png' instead, which Chrome may not read.)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$root = $PSScriptRoot
$version = (Get-Content (Join-Path $root 'manifest.json') -Raw | ConvertFrom-Json).version
$out = Join-Path (Split-Path $root -Parent) "fragrance-notes-$version.zip"

# Everything the extension needs, and nothing else.
$include = @('manifest.json', 'LICENSE', 'fonts.css', 'base.css', '*.js', '*.html', 'icons', 'fonts')

$files = foreach ($pattern in $include) {
  foreach ($item in Get-Item (Join-Path $root $pattern)) {
    if ($item.PSIsContainer) { Get-ChildItem $item.FullName -Recurse -File } else { $item }
  }
}
if (Test-Path $out) { Remove-Item $out }
$zip = [IO.Compression.ZipFile]::Open($out, [IO.Compression.ZipArchiveMode]::Create)
try {
  foreach ($f in $files | Sort-Object FullName -Unique) {
    $name = $f.FullName.Substring($root.Length).TrimStart('\', '/') -replace '\\', '/'
    [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $f.FullName, $name, [IO.Compression.CompressionLevel]::Optimal)
  }
} finally {
  $zip.Dispose()
}
Write-Host "Made $out"
Get-ChildItem $out | Select-Object Name, @{ n = 'KB'; e = { [math]::Round($_.Length / 1KB) } } | Format-Table -AutoSize
