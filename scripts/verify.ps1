param(
    [string[]]$TestPaths = @('tests')
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw '缺少项目 .venv，请先创建虚拟环境并安装 requirement.txt 中的依赖。'
}

Push-Location -LiteralPath $projectRoot
try {
    & $projectPython -c 'import struct, sys; assert sys.platform == "win32" and struct.calcsize("P") == 8, "验收需要 Windows x64 Python"'
    if ($LASTEXITCODE -ne 0) { throw '验收平台检查失败。' }
    Write-Host '重新生成解析器。'
    & $projectPython -m verbose_c.cli Grammar/verbose_c.gram --compile-parser
    if ($LASTEXITCODE -ne 0) { throw '解析器生成失败。' }
    $verificationDir = Join-Path $projectRoot ('build/verify-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $verificationDir -Force | Out-Null
    Write-Host '运行 O0/O1、VM、字节码重载和独立 PE 回归测试。'
    & $projectPython -m pytest -q -p no:cacheprovider --basetemp (Join-Path $verificationDir 'temp') --junitxml (Join-Path $verificationDir 'results.xml') @TestPaths
    if ($LASTEXITCODE -ne 0) { throw "回归失败，结果位于 $verificationDir" }
    Write-Host "验收通过，结果位于 $verificationDir"
}
finally {
    Pop-Location
}
