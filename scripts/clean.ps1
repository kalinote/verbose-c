$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")

Write-Host "清理项目缓存: $ProjectRoot"

Get-ChildItem -LiteralPath $ProjectRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "__pycache__" -or $_.Name -eq "__vbccache__" } |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }

$ParserPath = Join-Path $ProjectRoot "parser.py"
if (Test-Path -LiteralPath $ParserPath -PathType Leaf) {
    Remove-Item -LiteralPath $ParserPath -Force
}

$DumpsPath = Join-Path $ProjectRoot "dumps"
if (Test-Path -LiteralPath $DumpsPath -PathType Container) {
    Remove-Item -LiteralPath $DumpsPath -Recurse -Force
}

Write-Host "清理完成"
