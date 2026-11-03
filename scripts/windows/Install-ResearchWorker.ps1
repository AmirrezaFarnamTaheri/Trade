#Requires -Version 5.1
<# Explicit operator-only installation. Never invoked by tests or the launcher.
   RuntimeSource must be a trusted CPython embeddable distribution, including all
   dependencies and gym under Lib\site-packages. No network/package installation.
   PublicSourceDirectory MUST be a separately curated public-only publication,
   never executor/service data. The operator attests this; no secret scanning claim.
   Run elevated as the same Windows identity that will launch R0 (profile is per-user).
#>
[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='High')]
param(
    [Parameter(Mandatory=$true)][string]$InstallDirectory,
    [Parameter(Mandatory=$true)][string]$RuntimeSource,
    [Parameter(Mandatory=$true)][string]$PublicSourceDirectory,
    [Parameter(Mandatory=$true)][switch]$ConfirmPublicOnly,
    [Parameter(Mandatory=$true)][string]$StopPipe,
    [Parameter(Mandatory=$true)][string]$T2Pipe,
    [Parameter(Mandatory=$true)][string]$VaultPath,
    [Parameter(Mandatory=$true)][string]$CoreJournalPath,
    [Parameter(Mandatory=$true)][string]$ServiceName
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $ConfirmPublicOnly) { throw 'Public-only publication attestation required; never use service data.' }
function LocalPath([string]$Path) {
    if ($Path.Length -le 3 -or $Path -notmatch '^[A-Za-z]:\\' -or $Path.Substring(3) -match '[:"\r\n]' -or $Path -match '(^|\\)\.\.?($|\\)') { throw "Explicit local absolute path required: $Path" }
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}
function NoLinks([string]$Path, [bool]$Tree = $true) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point rejected: $($item.FullName)" }
        $item = $item.Parent
    }
    if ($Tree) {
        Get-ChildItem -LiteralPath $Path -Force | ForEach-Object {
            if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point rejected: $($_.FullName)" }
            if ($_.PSIsContainer) { NoLinks $_.FullName $true }
        }
    }
}
$InstallDirectory = LocalPath $InstallDirectory
$RuntimeSource = LocalPath $RuntimeSource
$PublicSourceDirectory = LocalPath $PublicSourceDirectory
if (Test-Path -LiteralPath $InstallDirectory) { throw 'Fresh installation directory required; no in-place runtime or snapshot replacement.' }
$trustedSids = @('S-1-5-18', 'S-1-5-32-544', 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
function ProtectedSource([string]$Path, [bool]$Contents) {
    $acl = Get-Acl -LiteralPath $Path
    $raw = [Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorBinaryForm(), 0)
    if ($null -eq $raw.DiscretionaryAcl -or $raw.Owner.Value -notin $trustedSids) { throw "Untrusted owner or null DACL: $Path" }
    $mask = if ($Contents) { 0x500d0156 } else { 0x500d0040 }
    foreach ($ace in $raw.DiscretionaryAcl) {
        if ($ace.AceFlags -band [Security.AccessControl.AceFlags]::InheritOnly) { continue }
        if ($ace.AceType -notin @([Security.AccessControl.AceType]::AccessAllowed, [Security.AccessControl.AceType]::AccessDenied)) { throw "Unsupported ACL ACE: $Path" }
        if ($ace.AceType -eq [Security.AccessControl.AceType]::AccessAllowed -and ([int64]$ace.AccessMask -band $mask) -ne 0 -and $ace.SecurityIdentifier.Value -notin $trustedSids) { throw "User-writable source or ancestor: $Path" }
    }
}
NoLinks $RuntimeSource
ProtectedSource $RuntimeSource $true
Get-ChildItem -LiteralPath $RuntimeSource -Force -Recurse | ForEach-Object { ProtectedSource $_.FullName $true }
$parent = (Get-Item -LiteralPath $RuntimeSource).Parent
while ($null -ne $parent) { ProtectedSource $parent.FullName $false; $parent = $parent.Parent }
NoLinks $PublicSourceDirectory
ProtectedSource $PublicSourceDirectory $true
Get-ChildItem -LiteralPath $PublicSourceDirectory -Force -Recurse | ForEach-Object { ProtectedSource $_.FullName $true }
$parent = (Get-Item -LiteralPath $PublicSourceDirectory).Parent
while ($null -ne $parent) { ProtectedSource $parent.FullName $false; $parent = $parent.Parent }
$installParent = Split-Path -Parent $InstallDirectory
NoLinks $installParent $false
ProtectedSource $installParent $true
$parent = (Get-Item -LiteralPath $installParent).Parent
while ($null -ne $parent) { ProtectedSource $parent.FullName $false; $parent = $parent.Parent }
if (Test-Path -LiteralPath (Join-Path $RuntimeSource 'pyvenv.cfg')) { throw 'venv/launcher redirect runtime rejected' }
$pth = @(Get-ChildItem -LiteralPath $RuntimeSource -Filter '*._pth' -File)
if ($pth.Count -ne 1 -or $pth[0].BaseName -notmatch '^python3[0-9]{2,3}$') { throw 'CPython embeddable runtime with one versioned _pth required' }
$stem = $pth[0].BaseName
foreach ($name in @('python.exe', "$stem.dll", "$stem.zip", 'Lib\site-packages\gym\services\research_worker.py', 'Lib\site-packages\gym\services\research_mcp.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $RuntimeSource $name) -PathType Leaf)) { throw "Missing self-contained runtime member: $name" }
}
foreach ($name in @('market.db', 'research.sqlite3')) {
    if (-not (Test-Path -LiteralPath (Join-Path $PublicSourceDirectory $name) -PathType Leaf)) { throw "Public source missing: $name" }
}
if ($StopPipe -notmatch '^\\\\\.\\pipe\\[^\\]+$' -or $T2Pipe -notmatch '^\\\\\.\\pipe\\[^\\]+$') { throw 'Explicit local stop/T2 pipe names required' }
$VaultPath = LocalPath $VaultPath
$CoreJournalPath = LocalPath $CoreJournalPath
if ($ServiceName -notmatch '^[A-Za-z0-9_.-]{1,128}$') { throw 'Invalid SCM service name' }
if (-not $PSCmdlet.ShouldProcess($InstallDirectory, 'Create no-capability AppContainer profile; copy/protect trusted runtime; publish public SQLite backups')) { return }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Explicit elevated operator step required' }
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ResearchContainerInstall {
 [DllImport("userenv.dll", CharSet=CharSet.Unicode)] public static extern int CreateAppContainerProfile(string name, string display, string description, IntPtr caps, uint count, out IntPtr sid);
 [DllImport("userenv.dll", CharSet=CharSet.Unicode)] public static extern int DeriveAppContainerSidFromAppContainerName(string name, out IntPtr sid);
 [DllImport("advapi32.dll")] public static extern IntPtr FreeSid(IntPtr sid);
}
'@
$sidPointer = [IntPtr]::Zero
$hr = [ResearchContainerInstall]::CreateAppContainerProfile('TradingGym.Research.R0', 'TradingGym R0', 'Public research only; no capabilities', [IntPtr]::Zero, 0, [ref]$sidPointer)
if ($hr -eq -2147024713) { $hr = [ResearchContainerInstall]::DeriveAppContainerSidFromAppContainerName('TradingGym.Research.R0', [ref]$sidPointer) } # ERROR_ALREADY_EXISTS
if ($hr -lt 0) { [Runtime.InteropServices.Marshal]::ThrowExceptionForHR($hr) }
try { $appSid = [Security.Principal.SecurityIdentifier]::new($sidPointer).Value }
finally { [void][ResearchContainerInstall]::FreeSid($sidPointer) }
function Seal([string]$Path, [bool]$Directory) {
    # Only SYSTEM/Administrators can mutate; this exact AppContainer gets RX.
    $acl = if ($Directory) { [Security.AccessControl.DirectorySecurity]::new() } else { [Security.AccessControl.FileSecurity]::new() }
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    $inherit = if ($Directory) { [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit' } else { [Security.AccessControl.InheritanceFlags]::None }
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544', $appSid, $identity.User.Value)) {
        $rights = if ($sid -in @('S-1-5-18', 'S-1-5-32-544')) { [Security.AccessControl.FileSystemRights]::FullControl } else { [Security.AccessControl.FileSystemRights]::ReadAndExecute }
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid), $rights, $inherit, [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}
# Seal the empty root BEFORE copying any executable. On failure no binding is published.
[void][IO.Directory]::CreateDirectory($InstallDirectory)
Seal $InstallDirectory $true
$runtime = Join-Path $InstallDirectory 'runtime'
$inputs = Join-Path $InstallDirectory 'inputs'
[void][IO.Directory]::CreateDirectory($runtime)
[void][IO.Directory]::CreateDirectory($inputs)
Copy-Item -Path (Join-Path $RuntimeSource '*') -Destination $runtime -Recurse -Force
# Never import site, user paths, venv configuration, or operator-provided _pth directives.
[IO.File]::WriteAllText((Join-Path $runtime "$stem._pth"), "$stem.zip`n.`nLib\site-packages`n", [Text.UTF8Encoding]::new($false))
Get-ChildItem -LiteralPath $InstallDirectory -Force -Recurse | ForEach-Object { Seal $_.FullName $_.PSIsContainer }
# This fixed helper uses sqlite3.backup, never copies WAL files or opens a service path.
$backup = @'
import sqlite3, sys
from pathlib import Path
source, target = map(Path, sys.argv[1:])
runtime = target.parent / 'runtime'
assert sys.prefix == sys.base_prefix and Path(sys.base_prefix).resolve() == runtime.resolve(), 'venv/redirect runtime'
assert Path(sys.executable).resolve() == (runtime / 'python.exe').resolve(), 'redirect executable'
assert sys.flags.isolated and sys.flags.no_site
from gym.services.research_mcp import handle
from gym.services.research_worker import main
assert {t['name'] for t in handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, target)['result']['tools']} == {'strategy_catalog', 'research_state', 'market_coverage'}
for name in ('market.db', 'research.sqlite3'):
    src = sqlite3.connect((source / name).as_uri() + '?mode=ro', uri=True)
    dst = sqlite3.connect(target / name)
    try:
        src.backup(dst)
        dst.execute('PRAGMA journal_mode=DELETE')
        assert dst.execute('PRAGMA quick_check').fetchone() == ('ok',)
    finally:
        dst.close()
        src.close()
'@
& (Join-Path $runtime 'python.exe') -I -S -B -c $backup $PublicSourceDirectory $inputs
if ($LASTEXITCODE -ne 0) { throw 'Public snapshot publication failed; no binding published' }
$targets = @{ stop_pipe=$StopPipe; t2_pipe=$T2Pipe; vault=$VaultPath; core_journal=$CoreJournalPath; service=$ServiceName }
[IO.File]::WriteAllText((Join-Path $InstallDirectory 'boundary.json'), ($targets | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
Get-ChildItem -LiteralPath $InstallDirectory -Force -Recurse | ForEach-Object { Seal $_.FullName $_.PSIsContainer }
[IO.File]::WriteAllText((Join-Path $InstallDirectory 'binding.txt'), $appSid, [Text.UTF8Encoding]::new($false))
Seal (Join-Path $InstallDirectory 'binding.txt') $false
Write-Output "Installed operator-selected R0 publication. Runtime/token/negative boundaries NOT_VERIFIED until explicit launch and probes. SID=$appSid"
