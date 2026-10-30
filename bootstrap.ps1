#requires -Version 5.1
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')][string]$Repo,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$Tag,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$Sha256,
    [Parameter(Mandatory=$true)][string]$Destination
)
$ErrorActionPreference = 'Stop'
$temporary = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N') + '.py')
try {
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/$Repo/$Tag/bootstrap.py" -OutFile $temporary
    if (Get-Command py -CommandType Application -ErrorAction SilentlyContinue) {
        & py -3 $temporary --repo $Repo --tag $Tag --sha256 $Sha256 --destination $Destination
    } elseif (Get-Command python -CommandType Application -ErrorAction SilentlyContinue) {
        & python $temporary --repo $Repo --tag $Tag --sha256 $Sha256 --destination $Destination
    } else {
        throw 'Нужен Python 3.10 или новее.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Загрузка пакета завершилась ошибкой.' }
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
}
