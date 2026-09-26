# Vendors the local shadowbox package into python_modules/ so the
# Cloudflare Worker bundle includes repo code, not just PyPI deps.
# Run from the repo root after `pywrangler sync` and before `pywrangler deploy`.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "python_modules\shadowbox"
if (Test-Path -LiteralPath $dest) {
    Remove-Item -Recurse -Force -LiteralPath $dest
}
Copy-Item -Recurse -LiteralPath (Join-Path $root "src\shadowbox") -Destination $dest
$files = (Get-ChildItem -Recurse -LiteralPath $dest | Measure-Object).Count
Write-Output "vendored $files files into python_modules/shadowbox"
