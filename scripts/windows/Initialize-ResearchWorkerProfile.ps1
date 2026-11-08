#Requires -Version 5.1
# Run explicitly from the selected ordinary operator logon before administrator installation.
[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='Medium')]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Initialize the AppContainer profile from the actual unelevated operator logon.' }
if (-not $PSCmdlet.ShouldProcess($identity.Name, 'Create per-user no-capability TradingGym.Research.R0 AppContainer profile')) { return }
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ResearchProfileInitialize {
 [DllImport("userenv.dll", CharSet=CharSet.Unicode)] public static extern int CreateAppContainerProfile(string name,string display,string description,IntPtr caps,uint count,out IntPtr sid);
 [DllImport("userenv.dll", CharSet=CharSet.Unicode)] public static extern int DeriveAppContainerSidFromAppContainerName(string name,out IntPtr sid);
 [DllImport("advapi32.dll")] public static extern IntPtr FreeSid(IntPtr sid);
}
'@
$pointer = [IntPtr]::Zero
$hr = [ResearchProfileInitialize]::CreateAppContainerProfile('TradingGym.Research.R0','TradingGym R0','Public research only; no capabilities',[IntPtr]::Zero,0,[ref]$pointer)
if ($hr -eq -2147024713) { $hr = [ResearchProfileInitialize]::DeriveAppContainerSidFromAppContainerName('TradingGym.Research.R0',[ref]$pointer) }
if ($hr -lt 0) { [Runtime.InteropServices.Marshal]::ThrowExceptionForHR($hr) }
try { $sid = [Security.Principal.SecurityIdentifier]::new($pointer).Value }
finally { [void][ResearchProfileInitialize]::FreeSid($pointer) }
Write-Output "Operator AppContainer profile initialized: user=$($identity.User.Value) SID=$sid. Runtime and boundary evidence remain NOT_VERIFIED."
