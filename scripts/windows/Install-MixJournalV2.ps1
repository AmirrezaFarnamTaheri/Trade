#Requires -Version 5.1
<# Schedules the daily Track B mix-journal-v2.jsonl append at 03:50 local (5m after v1 Allocation Journal).
   Read-only market.db access; never modifies v1 mix-journal.jsonl; zero order authority.
   Remove with -Uninstall.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$CoreDirectory,
    [string]$DataDirectory,
    [string]$TaskName = 'TradingGYM Mix Journal V2',
    [string]$DailyAt = '03:50',
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
$script = Join-Path $core 'scripts\record_mix_journal_v2.py'
$data = [IO.Path]::GetFullPath($DataDirectory)
$dbPath = Join-Path $data 'live\market.db'
$journalPath = Join-Path $data 'live\allocation\mix-journal-v2.jsonl'

$arguments = @('-I', '-B', "`"$script`"", '--db', "`"$dbPath`"", '--journal', "`"$journalPath`"")
$action = New-ScheduledTaskAction -Execute $python -Argument ($arguments -join ' ') -WorkingDirectory $core
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

if ($PSCmdlet.ShouldProcess($TaskName, "Register daily at $DailyAt -> $journalPath")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output "Registered '$TaskName' daily at $DailyAt -> $journalPath."
}
