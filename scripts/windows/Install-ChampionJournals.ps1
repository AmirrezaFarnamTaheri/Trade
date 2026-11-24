#Requires -Version 5.1
<# Schedules the daily S1+S5 Leader Journal (03:55) and 2-hourly Champion Ensemble Forward Shadow Journal.
   Read-only market.db & multi_venue_quotes.sqlite3 access; never touches v1 mix-journal.jsonl; executor remains DISARMED.
   Remove with -Uninstall.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$CoreDirectory,
    [string]$DataDirectory,
    [string]$EvidenceDirectory,
    [string]$GoldSymbol = 'XAUTUSDT',
    [switch]$Uninstall
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$leaderTask = 'TradingGYM S1-S5 Leader Journal'
$champTask = 'TradingGYM Champion Forward Journal'

if ($Uninstall) {
    foreach ($t in @($leaderTask, $champTask)) {
        if ($PSCmdlet.ShouldProcess($t, 'Unregister scheduled task')) {
            Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
        }
    }
    return
}

if (-not $CoreDirectory) { $CoreDirectory = Join-Path $PSScriptRoot '..\..\gym-core' }
if (-not $DataDirectory) { $DataDirectory = Join-Path $PSScriptRoot '..\..\data' }
if (-not $EvidenceDirectory) { $EvidenceDirectory = Join-Path $PSScriptRoot '..\..\evidence' }

$core = (Resolve-Path -LiteralPath $CoreDirectory).Path
$python = Join-Path $core '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install the gym-core environment with uv sync first.' }

$data = [IO.Path]::GetFullPath($DataDirectory)
$evid = [IO.Path]::GetFullPath($EvidenceDirectory)
$dbPath = Join-Path $data 'live\market.db'
$mvPath = Join-Path $data 'live\multi_venue_quotes.sqlite3'
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

# 1. Daily S1+S5 Leader Journal (03:55 local, right after Mix Journal V2)
$leaderScript = Join-Path $core 'scripts\record_leader_journal.py'
$leaderJournal = Join-Path $data 'live\allocation\s1-s5-leader-journal.jsonl'
$leaderReg = Join-Path $evid '2026-11-24-s1-s5-prospective-registration.json'
$leaderArgs = @('-I', '-B', "`"$leaderScript`"", '--db', "`"$dbPath`"", '--journal', "`"$leaderJournal`"", '--registration', "`"$leaderReg`"")
$leaderAction = New-ScheduledTaskAction -Execute $python -Argument ($leaderArgs -join ' ') -WorkingDirectory $core
$leaderTrigger = New-ScheduledTaskTrigger -Daily -At '03:55'

if ($PSCmdlet.ShouldProcess($leaderTask, "Register daily at 03:55 -> $leaderJournal")) {
    Register-ScheduledTask -TaskName $leaderTask -Action $leaderAction -Trigger $leaderTrigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output "Registered '$leaderTask' daily at 03:55 -> $leaderJournal."
}

# 2. 2-Hourly Champion Ensemble Forward Journal (1d Slow Core + 2h Frozen GRU-Ignition)
$champScript = Join-Path $core 'scripts\record_champion_journal.py'
$champJournal = Join-Path $data 'live\allocation\champion-ensemble-journal.jsonl'
$champModel = Join-Path $data 'live\models\gru-ignition-v1.json'
$champReg = Join-Path $evid '2026-11-25-champion-ensemble-registration.json'
$champScore = Join-Path $evid '2026-11-25-champion-forward-score.json'
$champArgs = @(
    '-I', '-B', "`"$champScript`"",
    '--db', "`"$dbPath`"",
    '--multi-venue-db', "`"$mvPath`"",
    '--journal', "`"$champJournal`"",
    '--model', "`"$champModel`"",
    '--registration', "`"$champReg`"",
    '--score-out', "`"$champScore`"",
    '--gold-symbol', "$GoldSymbol"
)
$champAction = New-ScheduledTaskAction -Execute $python -Argument ($champArgs -join ' ') -WorkingDirectory $core
$champTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 2)

if ($PSCmdlet.ShouldProcess($champTask, "Register every 2h -> $champJournal")) {
    Register-ScheduledTask -TaskName $champTask -Action $champAction -Trigger $champTrigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output "Registered '$champTask' every 2 hours (gold=$GoldSymbol) -> $champJournal."
}
