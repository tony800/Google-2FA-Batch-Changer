$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Create .venv and install requirements-build.txt first.'
}
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; build cancelled.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependencies are inconsistent.' }
& $python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name Google2FADesktop --collect-all playwright `
    --add-data "使用说明.txt;." --add-data "账号格式示例.txt;." desktop_app.pyw
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
Copy-Item '使用说明.txt','账号格式示例.txt' 'dist\Google2FADesktop\'
Write-Output 'Build ready: dist\Google2FADesktop\Google2FADesktop.exe'
