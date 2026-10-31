#Requires -RunAsAdministrator
<#
T2 last-resort containment of TradingGYMExecutor ONLY. No venue writes,
credentials, flattening or safe-exit guarantee. Stops software protection too.
Run explicitly from an elevated interactive Windows administration context.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch] $AcknowledgeLossOfProtection
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows-only hard stop.' }
if (-not $AcknowledgeLossOfProtection) {
    throw 'Explicit -AcknowledgeLossOfProtection required; stop disables all automated exits.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Hard stop requires an OS-issued elevated administrative token.'
}
$ServiceName = 'TradingGYMExecutor'
$expectedBinary = Join-Path $env:ProgramFiles 'TradingGYM\Executor\gym-executor.exe'
$registered = Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'"
if ($null -eq $registered) { throw 'Executor service is missing; cannot confirm containment.' }
# Reject wrong-service substitutions. Do not stop any arbitrary PID or service.
$registeredPath = $registered.PathName.Trim('"')
if (-not [string]::Equals(
    [IO.Path]::GetFullPath($registeredPath),
    [IO.Path]::GetFullPath($expectedBinary),
    [StringComparison]::OrdinalIgnoreCase
) -or $registered.StartName -ine 'NT AUTHORITY\LocalService') {
    throw 'Service identity or protected binary path differs from installed Executor.'
}
if (-not $PSCmdlet.ShouldProcess(
    $ServiceName, 'HARD STOP: disable service and halt all software exits'
)) { return }
& sc.exe @('config', $ServiceName, 'start=', 'disabled') | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'HARD STOP NOT CONFIRMED: cannot disable service.' }
try {
    $service = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($service.Status -ne 'Stopped') {
        Stop-Service -Name $ServiceName -Force -ErrorAction Stop
        $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(5))
    }
    $verified = Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'"
    if ($verified.StartMode -ne 'Disabled' -or $verified.State -ne 'Stopped') {
        throw 'HARD STOP NOT CONFIRMED: service is still active.'
    }
}
catch {
    throw "HARD STOP NOT CONFIRMED; inspect SCM locally: $($_.Exception.Message)"
}
Write-Warning 'UNPROTECTED: Executor stopped. In-flight submissions may remain UNKNOWN. Reconcile manually before restarting.'
Write-Output 'CONFIRMED: TradingGYMExecutor disabled and stopped (containment only, not a filled exit).'
