#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param([switch] $AcknowledgeLossOfProtection)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows-only hard stop.' }
if (-not $AcknowledgeLossOfProtection) { throw 'Explicit -AcknowledgeLossOfProtection required; disables automated exits.' }
$binary = Join-Path $env:ProgramFiles 'TradingGYM\Executor\gym-hardstop.exe'
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) { throw 'Protected gym-hardstop.exe is missing; containment NOT confirmed.' }
if (-not $PSCmdlet.ShouldProcess('TradingGYMExecutor', 'Disable restart and halt all software exits')) { return }
# Native helper authenticates the elevated token, SCM and retained process handle.
# Its own ten-second deadline covers blocked SCM RPC as well as suspended hosts.
& $binary --acknowledge-loss-of-protection
if ($LASTEXITCODE -ne 0) { throw 'HARD STOP NOT CONFIRMED; inspect SCM locally.' }
