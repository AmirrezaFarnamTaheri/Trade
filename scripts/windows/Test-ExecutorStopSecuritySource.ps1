# Source/in-process checks only: never installs, starts, stops or elevates a service.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
foreach ($file in Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1') {
    $tokens = $null; $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$helper = Join-Path $PSScriptRoot 'Get-OperatorLogonSid.ps1'
$logon = & $helper -OperatorProcessId $PID -ExpectedUserSid $identity.User.Value
if ($logon -notmatch '^S-1-5-5-[0-9]+-[0-9]+$') { throw 'Missing actual token logon SID.' }
$rejected = $false
try { $null = & $helper -OperatorProcessId $PID -ExpectedUserSid 'S-1-0-0' } catch { $rejected = $true }
if (-not $rejected) { throw 'Mismatched selected operator identity accepted.' }
$rejected = $false
try { $null = & $helper -OperatorProcessId 0 -ExpectedUserSid $identity.User.Value } catch { $rejected = $true }
if (-not $rejected) { throw 'Zero selected operator process ID accepted.' }
$hard = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Invoke-ExecutorHardStop.ps1') -Raw
if ($hard -match 'Stop-Service' -or $hard -notmatch 'acknowledge-loss-of-protection') { throw 'Unbounded or unconfirmed hard-stop wrapper.' }
& (Join-Path $PSScriptRoot 'Assert-ExecutorDrillManifest.ps1') -SelfTest
& (Join-Path $PSScriptRoot 'Test-ExecutorInstalledHost.ps1') -Stage SelfTest
Write-Output 'PASS: scripts parse; actual token user/logon matched; mismatched and zero-PID bindings rejected. No privileged operations performed.'
