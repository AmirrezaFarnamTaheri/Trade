#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DataDirectory,
    [Parameter(Mandatory)][string]$UvPath,
    [Parameter(Mandatory)][ValidatePattern('^[A-Z0-9]{3,32}$')][string[]]$Symbols
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $UvPath -PathType Leaf)) { throw "uv executable is unavailable" }
$logDirectory = Join-Path $DataDirectory 'live\allocation'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logPath = Join-Path $logDirectory 'scheduled-allocation-latest.log'
$from = (Get-Date).ToUniversalTime().AddDays(-5).ToString('yyyy-MM-ddT00:00:00Z')
$baseArguments = @('run', '--no-sync', 'gymctl', '--data', $DataDirectory)
$mix = @('XAUTUSDT', 'SLVONUSDT', 'USOONUSDT', 'COPXONUSDT', 'AAPLXUSDT')
$steps = @(
    @{ Name = 'trend history'; Refresh = $true; Arguments = @('history') + $Symbols + @('--resolution', '1d', '--from', $from, '--best-effort') }
    @{ Name = 'trend journal'; Refresh = $false; Arguments = @('allocate') + $Symbols + @('--vol-target', '5', '--band', '0', '--require-completed-day') }
    @{ Name = 'mix history'; Refresh = $true; Arguments = @('history') + $mix + @('--resolution', '1d', '--from', $from, '--best-effort') }
    @{ Name = 'mix journal'; Refresh = $false; Arguments = @('mix-journal', '--require-completed-day') }
)

Set-Content -LiteralPath $logPath -Encoding UTF8 -Value "Started $([DateTime]::UtcNow.ToString('o'))"
$result = 0
foreach ($step in $steps) {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ("Started " + $step.Name)
    $arguments = $baseArguments + $step.Arguments
    try {
        # Windows PowerShell can turn redirected native stderr into ErrorRecords.
        $ErrorActionPreference = 'Continue'
        & $UvPath @arguments 2>&1 | ForEach-Object {
            Add-Content -LiteralPath $logPath -Encoding UTF8 -Value $_.ToString()
        }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = 'Stop'
    }
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ("Finished " + $step.Name + " with exit " + $code)
    # Code 3 means the refresh tried all symbols. The corresponding journal enforces the required day.
    if ($code -ne 0 -and -not ($step.Refresh -and $code -eq 3)) { $result = $code }
}
Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "Completed $([DateTime]::UtcNow.ToString('o')) with exit $result"
exit $result
