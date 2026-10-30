#requires -Version 5.1
$ErrorActionPreference = 'Stop'
$entry = Join-Path $PSScriptRoot 'horizon_ely.py'
if (Get-Command py -CommandType Application -ErrorAction SilentlyContinue) {
    & py -3 $entry @args
} elseif (Get-Command python3 -CommandType Application -ErrorAction SilentlyContinue) {
    & python3 $entry @args
} elseif (Get-Command python -CommandType Application -ErrorAction SilentlyContinue) {
    & python $entry @args
} else {
    throw 'Нужен Python 3.10 или новее.'
}
exit $LASTEXITCODE
