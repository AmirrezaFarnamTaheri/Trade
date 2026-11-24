#Requires -Version 5.1
<# Runs the observation-only multi-venue (Nobitex + AbanTether) quote recorder at logon for the current user.
   No administrator rights, no service account, no secrets: only reads public market quotes.
   Persists normalized snapshots to <data>\live\multi_venue_quotes.sqlite3.
   Remove with -Uninstall.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$CoreDirectory,
    [string]$DataDirectory,
    [string]$TaskName = 'TradingGYM Multi-Venue Recorder',
    [int]$IntervalSeconds = 60,
    [int]$WatchdogMinutes = 5,
    [switch]$Uninstall
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    return
}

if (-not $CoreDirectory) { $CoreDirectory = Join-Path $PSScriptRoot '..\..\gym-core' }
if (-not $DataDirectory) { $DataDirectory = Join-Path $PSScriptRoot '..\..\data' }
$core = (Resolve-Path -LiteralPath $CoreDirectory).Path
$python = Join-Path $core '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install the gym-core environment with uv sync first.' }
$script = Join-Path $core 'scripts\record_multi_venue_quotes.py'
$data = [IO.Path]::GetFullPath($DataDirectory)
$outDb = Join-Path $data 'live\multi_venue_quotes.sqlite3'
$wallexDb = Join-Path $data 'live\market.db'

$arguments = @(
    '-I', '-B', "`"$script`"",
    '--db', "`"$outDb`"",
    '--wallex-db', "`"$wallexDb`"",
    '--interval-s', "$IntervalSeconds"
)
$action = New-ScheduledTaskAction -Execute $python -Argument ($arguments -join ' ') -WorkingDirectory $core
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $WatchdogMinutes)
$trigger = @($logon, $watchdog)
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

if ($PSCmdlet.ShouldProcess($TaskName, "Register: $python $($arguments -join ' ') in $core")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Registered and started '$TaskName' -> $outDb (interval=${IntervalSeconds}s)."
}
