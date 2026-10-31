#Requires -RunAsAdministrator
<#
Install a DISABLED, read-only Windows SCM bootstrap (not funded, not a live
stop-protection service). Run explicitly from an elevated PowerShell window.
No secrets, T2 actions, network access, or venue APIs are provisioned.
Do not change the service to automatic start as part of this script.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $BinaryPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') { throw 'This installer runs only on Windows.' }
$ServiceName = 'TradingGYMExecutor'
$CodeRoot = Join-Path ${env:ProgramFiles} 'TradingGYM'
$CodeDir = Join-Path $CodeRoot 'Executor'
$ExePath = Join-Path $CodeDir 'gym-executor.exe'
$DataRoot = Join-Path ${env:ProgramData} 'TradingGYM'
$DataDir = Join-Path $DataRoot 'Executor'

# Only an explicit elevated action may create/modify these local resources.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'An elevated administrator token is required.'
}
$inputFile = Get-Item -LiteralPath $BinaryPath -ErrorAction Stop
if ($inputFile.PSIsContainer -or $inputFile.Extension -ine '.exe' -or
    (($inputFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
    throw 'BinaryPath must be an existing regular .exe file, not a link.'
}
if ([IO.Path]::GetFullPath($inputFile.FullName) -ieq [IO.Path]::GetFullPath($ExePath)) {
    throw 'Choose a staging binary outside the protected destination directory.'
}
if (Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'") {
    throw 'Service already exists; manual review is required before any reinstall.'
}
# Reuse of pre-existing directories is forbidden until a separate secure
# migration can prove parent ownership and reject replacement/reparse races.
foreach ($path in @($CodeRoot, $DataRoot)) {
    if (Test-Path -LiteralPath $path) {
        throw "Existing install root requires manual review: $path"
    }
}

$sourceHash = (Get-FileHash -LiteralPath $inputFile.FullName -Algorithm SHA256).Hash
$target = "$ExePath / $DataDir (service remains DISABLED)"
if (-not $PSCmdlet.ShouldProcess($target, 'Install read-only Executor service identity and ACLs')) {
    return
}

function Invoke-Sc {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    & sc.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "sc.exe failed with code $LASTEXITCODE" }
}
function Invoke-Icacls {
    param([Parameter(Mandatory = $true)][string] $Path,
          [Parameter(Mandatory = $true)][string[]] $Arguments)
    & icacls.exe $Path @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed on $Path with code $LASTEXITCODE" }
}

$created = $false
try {
    $null = New-Item -ItemType Directory -Path $CodeDir -Force
    $null = New-Item -ItemType Directory -Path $DataDir -Force
    foreach ($dir in @($CodeRoot, $CodeDir, $DataRoot, $DataDir)) {
        Invoke-Icacls -Path $dir -Arguments @('/inheritance:r')
        Invoke-Icacls -Path $dir -Arguments @(
            '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'
        )
        Invoke-Icacls -Path $dir -Arguments @('/setowner', '*S-1-5-32-544')
    }
    Copy-Item -LiteralPath $inputFile.FullName -Destination $ExePath -ErrorAction Stop
    if ((Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash -ne $sourceHash) {
        throw 'Executable hash changed during copy; refusing registration.'
    }
    Invoke-Icacls -Path $ExePath -Arguments @('/inheritance:r')
    Invoke-Icacls -Path $ExePath -Arguments @('/grant:r', '*S-1-5-18:F', '*S-1-5-32-544:F')
    Invoke-Icacls -Path $ExePath -Arguments @('/setowner', '*S-1-5-32-544')

    # Native SCM syntax separates each key from its argument. No password is
    # accepted, and this deliberately does not start the service.
    Invoke-Sc -Arguments @('create', $ServiceName, 'type=', 'own',
        'start=', 'disabled', 'obj=', 'NT AUTHORITY\LocalService',
        'binPath=', ('"' + $ExePath + '"'))
    $created = $true
    # Without this descriptor Windows may grant interactive users SERVICE_START
    # or SERVICE_STOP.  Only query rights are intentionally exposed to AU.
    $serviceScmDacl = 'D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x0002008D;;;AU)'
    Invoke-Sc -Arguments @('sdset', $ServiceName, $serviceScmDacl)
    Invoke-Sc -Arguments @('sidtype', $ServiceName, 'restricted')
    Invoke-Sc -Arguments @('description', $ServiceName,
        'READ-ONLY bootstrap; no money, stop-protection or credential capability')

    $serviceSid = ([Security.Principal.NTAccount]::new("NT SERVICE\$ServiceName")).Translate(
        [Security.Principal.SecurityIdentifier]).Value
    if ($serviceSid -notmatch '^S-1-5-80-([0-9]+-){4}[0-9]+$') {
        throw 'Windows did not resolve a valid isolated service SID.'
    }
    $readCode = "*${serviceSid}:(OI)(CI)RX"
    $modifyData = "*${serviceSid}:(OI)(CI)M"
    Invoke-Icacls -Path $CodeRoot -Arguments @('/grant:r', $readCode)
    Invoke-Icacls -Path $CodeDir -Arguments @('/grant:r', $readCode)
    Invoke-Icacls -Path $ExePath -Arguments @('/grant:r', "*${serviceSid}:RX")
    Invoke-Icacls -Path $DataRoot -Arguments @('/grant:r', $readCode)
    Invoke-Icacls -Path $DataDir -Arguments @('/grant:r', $modifyData)

    # TokenGroups is not guaranteed to expose the special logon SID. Query
    # TokenLogonSid (28) from the current elevated process token directly.
    $tokenLogonSidSource = @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class TradeTokenLogonSid
{
    [StructLayout(LayoutKind.Sequential)]
    private struct SidAndAttributes
    {
        public IntPtr Sid;
        public uint Attributes;
    }

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool OpenProcessToken(
        IntPtr process, uint access, out SafeAccessTokenHandle token);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetTokenInformation(
        SafeAccessTokenHandle token, int informationClass, IntPtr information,
        int informationLength, out int returnLength);

    [DllImport("advapi32.dll", EntryPoint = "ConvertSidToStringSidW", SetLastError = true)]
    private static extern bool ConvertSidToStringSid(
        IntPtr sid, out IntPtr stringSid);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);

    public static string Get()
    {
        SafeAccessTokenHandle token;
        if (!OpenProcessToken(GetCurrentProcess(), 0x0008, out token))
            throw new Win32Exception(Marshal.GetLastWin32Error());

        using (token)
        {
            int required;
            if (GetTokenInformation(token, 28, IntPtr.Zero, 0, out required))
                throw new InvalidOperationException("Unexpected TokenLogonSid sizing success.");
            if (Marshal.GetLastWin32Error() != 122 ||
                required < (IntPtr.Size == 8 ? 8 : 4) ||
                required > 65536)
                throw new Win32Exception(Marshal.GetLastWin32Error());

            IntPtr buffer = Marshal.AllocHGlobal(required);
            try
            {
                int returned;
                if (!GetTokenInformation(token, 28, buffer, required, out returned))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                int offset = IntPtr.Size == 8 ? 8 : 4;
                int itemSize = Marshal.SizeOf(typeof(SidAndAttributes));
                if (returned < offset || returned > required)
                    throw new InvalidOperationException("Invalid TokenLogonSid buffer.");
                int count = Marshal.ReadInt32(buffer);
                int capacity = (returned - offset) / itemSize;
                if (count < 1 || count > capacity)
                    throw new InvalidOperationException("Invalid TokenLogonSid count.");

                string found = null;
                for (int i = 0; i < count; i++)
                {
                    IntPtr item = IntPtr.Add(buffer, offset + i * itemSize);
                    SidAndAttributes group =
                        (SidAndAttributes)Marshal.PtrToStructure(item, typeof(SidAndAttributes));
                    // SE_GROUP_LOGON_ID is the pair of high attribute bits.
                    if ((group.Attributes & 0xC0000000u) != 0xC0000000u)
                        continue;
                    if (group.Sid == IntPtr.Zero || found != null)
                        throw new InvalidOperationException("Ambiguous logon SID token.");
                    IntPtr text;
                    if (!ConvertSidToStringSid(group.Sid, out text))
                        throw new Win32Exception(Marshal.GetLastWin32Error());
                    try { found = Marshal.PtrToStringUni(text); }
                    finally { LocalFree(text); }
                }
                if (found == null ||
                    !System.Text.RegularExpressions.Regex.IsMatch(
                        found, @"^S-1-5-5-[0-9]+-[0-9]+$"))
                    throw new InvalidOperationException("No unique OS-issued logon SID.");
                return found;
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }
    }
}
'@
    if (-not ('TradeTokenLogonSid' -as [type])) {
        Add-Type -TypeDefinition $tokenLogonSidSource -ErrorAction Stop
    }
    $logonSid = [TradeTokenLogonSid]::Get()
    if ($logonSid -notmatch '^S-1-5-5-[0-9]+-[0-9]+$') {
        throw 'Windows did not return a valid operator logon SID.'
    }
    # Keep authorization in CodeDir (service RX) NOT DataDir (service Modify).
    $stopSidPath = Join-Path $CodeDir 'stop-logon.sid'
    [IO.File]::WriteAllText($stopSidPath, $logonSid, [Text.Encoding]::ASCII)
    Invoke-Icacls -Path $stopSidPath -Arguments @('/inheritance:r')
    Invoke-Icacls -Path $stopSidPath -Arguments @(
        '/grant:r', '*S-1-5-18:F', '*S-1-5-32-544:F', "*${serviceSid}:R"
    )
    Invoke-Icacls -Path $stopSidPath -Arguments @('/setowner', '*S-1-5-32-544')

    & (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Isolation verification script failed.' }
    Write-Output "Registered DISABLED read-only service $ServiceName. No money or stop protection is active."
}
catch {
    if ($created) {
        try { Invoke-Sc -Arguments @('config', $ServiceName, 'start=', 'disabled') } catch {}
    }
    throw
}
