#Requires -Version 5.1
<# Start the public all-market collector and paper scheduler using one data root.
   Both use limited-user scheduled tasks with single-instance and restart settings.
   -WhatIf previews both actions. This never starts the protected executor.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$CoreDirectory,
    [string]$DataDirectory
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $CoreDirectory) { $CoreDirectory = Join-Path $PSScriptRoot '..\..\gym-core' }
if (-not $DataDirectory) { $DataDirectory = Join-Path $PSScriptRoot '..\..\data' }
$core = (Resolve-Path -LiteralPath $CoreDirectory).Path
$data = [IO.Path]::GetFullPath($DataDirectory)
$python = Join-Path $core '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install the gym-core environment with uv sync first.' }
$listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -and -not $WhatIfPreference) {
    throw 'Port 8765 is already in use. Inspect the current workspace before starting another collector.'
}

& (Join-Path $PSScriptRoot 'Install-Collector.ps1') -CoreDirectory $core -DataDirectory $data
if (-not $WhatIfPreference) {
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $ready = (Test-Path -LiteralPath (Join-Path $data 'live\market.db')) -and
            @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue).Count -eq 1
        if ($ready) { break }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $ready) { throw 'Collector startup did not finish; paper scheduler was not started.' }
}
$arguments = @('-I', '-B', '-m', 'gym.cli', '--data', "`"$data`"", 'research', 'start', '--poll-seconds', '60')
$action = New-ScheduledTaskAction -Execute $python -Argument ($arguments -join ' ') -WorkingDirectory $core
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($data, 'Start paper scheduler')) {
    Register-ScheduledTask -TaskName 'TradingGYM Research' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName 'TradingGYM Research'
    Write-Output 'Registered and started TradingGYM Research.'
}
