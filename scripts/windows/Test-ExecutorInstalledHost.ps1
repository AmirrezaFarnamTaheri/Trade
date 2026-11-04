#Requires -Version 5.1
<# Explicit four-stage, synthetic-only drill on a fresh reviewed installation.
   Custody (administrator) -> BindWorker (administrator, after worker installation)
   -> Operator (actual selected unelevated logon) -> Contain (administrator).
   Never calls an account API. Synthetic bytes include NUL and cannot form an API header.
   Custody refuses any existing vault content; it never replaces a real credential.
   Stages preserve evidence/history and leave the service DISABLED. BindWorker parks
   the main loop; Contain is then required to stop it. No result promotes authority.
#>
[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='High')]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Custody','BindWorker','Operator','Contain','SelfTest')][string]$Stage,
    [string]$BinaryDirectory,
    [string]$WorkerInstallDirectory,
    [string]$OperatorReportPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Assert-OperatorReport($Report, $State) {
    if ($Report.run_id -cne $State.run_id -or $Report.user_sid -cne $State.user_sid -or
        $Report.logon_sid -cne $State.logon_sid -or $Report.service_pid -ne $State.service_pid -or
        $Report.worker_denials -ne $true -or @($Report.stops).Count -ne 4) { throw 'Incomplete or different-runtime operator evidence.' }
    $commands = @($Report.stops | ForEach-Object { $_.command })
    if (($commands -join ',') -cne 'status,pause,exit-only,halt') { throw 'Missing operator STOP command.' }
    foreach ($stop in $Report.stops) {
        if ($stop.acknowledged -ne $true -or $stop.elapsed_ms -lt 0 -or $stop.elapsed_ms -gt 1000) { throw 'Operator STOP was unacknowledged or exceeded 1s.' }
    }
}
if ($Stage -eq 'SelfTest') {
    $state = [pscustomobject]@{ run_id='test'; user_sid='operator'; logon_sid='logon'; service_pid=42 }
    $report = [pscustomobject]@{ run_id='test'; user_sid='operator'; logon_sid='logon'; service_pid=42; worker_denials=$true;
        stops=@('status','pause','exit-only','halt' | ForEach-Object { [pscustomobject]@{ command=$_; acknowledged=$true; elapsed_ms=10 } }) }
    Assert-OperatorReport $report $state
    foreach ($field in @('run_id','user_sid','logon_sid','service_pid','worker_denials','stops')) {
        $copy = $report | ConvertTo-Json -Depth 5 | ConvertFrom-Json
        $copy.$field = if ($field -eq 'service_pid') { 43 } elseif ($field -eq 'worker_denials') { $false } elseif ($field -eq 'stops') { @() } else { 'wrong' }
        $rejected = $false
        try { Assert-OperatorReport $copy $state } catch { $rejected = $true }
        if (-not $rejected) { throw "Self-test accepted altered $field" }
    }
    foreach ($change in @('late','unacknowledged')) {
        $copy = $report | ConvertTo-Json -Depth 5 | ConvertFrom-Json
        if ($change -eq 'late') { $copy.stops[0].elapsed_ms = 1001 } else { $copy.stops[0].acknowledged = $false }
        $rejected = $false
        try { Assert-OperatorReport $copy $state } catch { $rejected = $true }
        if (-not $rejected) { throw "Self-test accepted $change STOP" }
    }
    Write-Output 'PASS: operator evidence rejects altered identities, missing worker denials and late/unacknowledged STOP.'
    return
}
if ($env:OS -ne 'Windows_NT') { throw 'Windows required.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$elevated = ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (($Stage -eq 'Operator') -eq $elevated) { throw 'Operator requires the selected unelevated logon; other stages require a separate elevated administrator.' }
$code = Join-Path $env:ProgramFiles 'TradingGYM\Executor'
$vault = Join-Path $env:ProgramData 'TradingGYM\Executor\Vault'
$statePath = Join-Path $code 'installed-host-drill.json'
$secretPath = Join-Path $code 'installed-host-drill.secret'
$savedCiphertext = Join-Path $code 'installed-host-drill.dpapi-backup'
$serviceName = 'TradingGYMExecutor'
function LocalPath([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:\\' -or $Path.Substring(3) -match '[:"\r\n]' -or $Path -match '(^|\\)\.\.?($|\\)') { throw 'Explicit local absolute path required.' }
    return [IO.Path]::GetFullPath($Path)
}
function Invoke-DrillSc([string[]]$Arguments) {
    & sc.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'SCM drill operation failed.' }
}
function ServiceInfo { Get-CimInstance Win32_Service -Filter "Name = 'TradingGYMExecutor'" }
function WaitState([string]$Expected) {
    $controller = Get-Service -Name $serviceName
    try { $controller.WaitForStatus([ServiceProcess.ServiceControllerStatus]::$Expected, [TimeSpan]::FromSeconds(15)) }
    finally { $controller.Dispose() }
}
function StopNormal {
    if ((ServiceInfo).State -ne 'Stopped') { Stop-Service -Name $serviceName; WaitState 'Stopped' }
    Invoke-DrillSc @('config', $serviceName, 'start=', 'disabled')
}
function StartNormal([string]$Argument = '') {
    Invoke-DrillSc @('config', $serviceName, 'start=', 'demand')
    try {
        if ($Argument) { Invoke-DrillSc @('start', $serviceName, $Argument) } else { Start-Service -Name $serviceName }
        WaitState 'Running'
    } finally { Invoke-DrillSc @('config', $serviceName, 'start=', 'disabled') }
}
function SealFile([string]$Path, [string]$Owner, [string]$Reader = '') {
    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new($Owner))
    foreach ($sid in @('S-1-5-18','S-1-5-32-544',$Owner) | Select-Object -Unique) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid), 'FullControl', 'Allow'))
    }
    if ($Reader) { $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($Reader), 'Read', 'Allow')) }
    Set-Acl -LiteralPath $Path -AclObject $acl
}
function SaveState($State) {
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
    SealFile $statePath 'S-1-5-32-544' $State.user_sid
}
function LoadState {
    & (Join-Path $PSScriptRoot 'Assert-ExecutorDrillManifest.ps1') -Path $statePath
    return Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
}
function AssertHashes($State) {
    foreach ($property in $State.binary_hashes.PSObject.Properties) {
        if ((Get-FileHash -LiteralPath (Join-Path $code $property.Name) -Algorithm SHA256).Hash -cne $property.Value) { throw 'Installed drill binaries changed.' }
    }
}
if ($Stage -eq 'Custody') {
    & (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1')
    if (@(Get-ChildItem -LiteralPath $vault -Force).Count -ne 0 -or (Test-Path -LiteralPath $statePath) -or (Test-Path -LiteralPath $secretPath) -or (Test-Path -LiteralPath $savedCiphertext)) { throw 'Fresh empty vault and no prior drill required; preserve existing custody history.' }
    $BinaryDirectory = LocalPath $BinaryDirectory
    $hashes = @{}
    foreach ($name in @('gym-executor.exe','gym-stopctl.exe','gym-hardstop.exe','gym-provision.exe','gym-account-read.exe','gym-research-worker.exe')) {
        $expected = (Get-FileHash -LiteralPath (Join-Path $BinaryDirectory $name) -Algorithm SHA256).Hash
        if ((Get-FileHash -LiteralPath (Join-Path $code $name) -Algorithm SHA256).Hash -cne $expected) { throw 'Installed binary differs from chosen reviewed build.' }
        $hashes[$name] = $expected
    }
    if (-not $PSCmdlet.ShouldProcess($serviceName, 'Fresh synthetic custody, restart, corruption refusal and missing-ciphertext recovery; no account API')) { return }
    $runId = [guid]::NewGuid().ToString('N')
    $operatorSid = (Get-Content -LiteralPath (Join-Path $code 'stop-user.sid') -Raw).Trim()
    $profileKey = Get-ItemProperty -LiteralPath ('HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\' + $operatorSid)
    $profileRoot = LocalPath ([Environment]::ExpandEnvironmentVariables($profileKey.ProfileImagePath))
    $profileCanary = Join-Path $profileRoot ("TradingGYM-boundary-$runId.txt")
    $canaryContent = [Text.Encoding]::ASCII.GetBytes('TradingGYM AppContainer boundary canary; no private data.')
    $canaryFile = [IO.File]::Open($profileCanary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $canaryFile.Write($canaryContent, 0, $canaryContent.Length) } finally { $canaryFile.Dispose() }
    $synthetic = [byte[]]::new(64)
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($synthetic) } finally { $rng.Dispose() }
    $synthetic[0] = 0 # Also guarantees any accidental account read fails before WinHTTP.
    $original = $null
    $completed = $false
    try {
        [void](New-Item -ItemType File -Path $secretPath -ErrorAction Stop)
        SealFile $secretPath $identity.User.Value
        [IO.File]::WriteAllBytes($secretPath, $synthetic)
        [Array]::Clear($synthetic, 0, $synthetic.Length)
        StartNormal
        & (Join-Path $code 'gym-provision.exe') --secret-file $secretPath
        if ($LASTEXITCODE -ne 0) { throw 'Synthetic provisioning not acknowledged; preserve uncertain history.' }
        StopNormal
        StartNormal # Normal startup decrypts the current service-context DPAPI ciphertext.
        StopNormal
        $generations = @(Get-ChildItem -LiteralPath $vault -Filter '*.dpapi' -File)
        if ($generations.Count -ne 1) { throw 'Expected exactly one fresh synthetic generation.' }
        $generation = $generations[0].FullName
        $original = [IO.File]::ReadAllBytes($generation)
        $damaged = [byte[]]$original.Clone()
        $damaged[0] = $damaged[0] -bxor 1
        [IO.File]::WriteAllBytes($generation, $damaged)
        Invoke-DrillSc @('config', $serviceName, 'start=', 'demand')
        try { Start-Service -Name $serviceName -ErrorAction Stop } catch { } # Refusal is expected; verify SCM result independently.
        WaitState 'Stopped'
        if ((ServiceInfo).ExitCode -eq 0) { throw 'Corrupted custody did not produce a fail-closed service error.' }
        [IO.File]::WriteAllBytes($generation, $original)
        StartNormal
        StopNormal
        Move-Item -LiteralPath $generation -Destination $savedCiphertext
        & (Join-Path $PSScriptRoot 'Invoke-ExecutorCredentialRecovery.ps1') -SecretFile $secretPath -Confirm:$false
        StopNormal
        $replacements = @(Get-ChildItem -LiteralPath $vault -Filter '*.dpapi' -File)
        if ($replacements.Count -ne 1) { throw 'Expected one replacement current ciphertext generation.' }
        $currentGeneration = $replacements[0].FullName
        Move-Item -LiteralPath $savedCiphertext -Destination $generation
        StartNormal
        StopNormal
        $state = [pscustomobject]@{ run_id=$runId; created_utc=[DateTime]::UtcNow.ToString('o'); profile_canary=$profileCanary;
            user_sid=$operatorSid;
            logon_sid=(Get-Content -LiteralPath (Join-Path $code 'stop-logon.sid') -Raw).Trim();
            binary_hashes=[pscustomobject]$hashes; custody_verified=$true; current_generation=$currentGeneration; worker_install=''; service_pid=0; targets=$null }
        SaveState $state
        $completed = $true
        Write-Output "PASS: synthetic service DPAPI provision/restart/corruption refusal/recovery. DISABLED and STOPPED. Current ciphertext=$currentGeneration; profile canary=$profileCanary. Install actual worker publication, then run BindWorker."
    } finally {
        [Array]::Clear($synthetic, 0, $synthetic.Length)
        try {
            StopNormal
            if ($null -ne $original -and (Test-Path -LiteralPath $savedCiphertext)) { Move-Item -LiteralPath $savedCiphertext -Destination $generation }
            elseif (-not $completed -and $null -ne $original) { [IO.File]::WriteAllBytes($generation, $original) }
        } finally { if (Test-Path -LiteralPath $secretPath) { Remove-Item -LiteralPath $secretPath -Force } }
    }
    return
}
$state = LoadState
if ($Stage -ne 'Operator') { AssertHashes $state }
if ($Stage -eq 'BindWorker') {
    & (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1')
    $WorkerInstallDirectory = LocalPath $WorkerInstallDirectory
    $targets = Get-Content -LiteralPath (Join-Path $WorkerInstallDirectory 'boundary.json') -Raw | ConvertFrom-Json
    if ($targets.stop_pipe -cne '\\.\pipe\TradingGYM.Stop.v1' -or $targets.t2_pipe -cne '\\.\pipe\TradingGYM.Privileged.v1' -or
        $targets.service -cne $serviceName -or (Split-Path -Parent $targets.vault) -ine $vault -or
        $targets.vault -ine $state.current_generation -or $targets.core_journal -ine (Join-Path $vault 'credentials.sqlite') -or
        $targets.profile_canary -ine $state.profile_canary) { throw 'Worker targets must name actual current private custody files, profile canary and fixed service pipes.' }
    foreach ($name in @('vault','core_journal','profile_canary')) {
        $target = Get-Item -LiteralPath $targets.$name
        if ($target.PSIsContainer -or ($target.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Missing or linked actual boundary target.' }
    }
    if (-not $PSCmdlet.ShouldProcess($serviceName, 'Park service main loop; publish protected existence evidence for actual operator worker probes; Contain required afterward')) { return }
    try {
        StartNormal '--stop-isolation-drill'
        $state.worker_install = $WorkerInstallDirectory
        $state.targets = $targets
        $state.service_pid = (ServiceInfo).ProcessId
        $state.created_utc = [DateTime]::UtcNow.ToString('o')
        SaveState $state
    } catch {
        $bindingFailure = $_
        & (Join-Path $code 'gym-hardstop.exe') --acknowledge-loss-of-protection
        if ($LASTEXITCODE -ne 0) { throw "Drill binding failed and hard containment was not confirmed; use the fixed hard-stop helper manually. Original error: $bindingFailure" }
        throw $bindingFailure
    }
    Write-Output 'Main-loop drill RUNNING with DISABLED startup; account reads disabled. Run Operator from the bound unelevated logon, then Contain as administrator.'
    return
}
if ($Stage -eq 'Operator') {
    $OperatorReportPath = LocalPath $OperatorReportPath
    if (Test-Path -LiteralPath $OperatorReportPath) { throw 'Fresh operator evidence path required.' }
    $logon = (& (Join-Path $PSScriptRoot 'Get-OperatorLogonSid.ps1')).Trim()
    if ($identity.User.Value -cne $state.user_sid -or $logon -cne $state.logon_sid -or
        (ServiceInfo).ProcessId -ne $state.service_pid) { throw 'Actual operator token or service runtime differs from protected binding.' }
    if (-not $PSCmdlet.ShouldProcess($serviceName, 'Measure operator STOP and launch actual no-capability research child against private resources')) { return }
    $stops = @()
    foreach ($command in @('status','pause','exit-only','halt')) {
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $reply = & (Join-Path $code 'gym-stopctl.exe') $command 2>&1
        $watch.Stop()
        if ($LASTEXITCODE -ne 0 -or ($reply -join ' ') -notmatch '^ACKNOWLEDGED:' -or $watch.ElapsedMilliseconds -gt 1000 -or
            ($command -eq 'status' -and ($reply -join ' ') -notmatch 'mode=Disarmed$')) { throw 'STOP failed or startup was not DISARMED.' }
        $stops += [pscustomobject]@{ command=$command; acknowledged=$true; elapsed_ms=$watch.ElapsedMilliseconds }
    }
    & (Join-Path $PSScriptRoot 'Test-ResearchWorkerBoundary.ps1') -Launcher (Join-Path $code 'gym-research-worker.exe') -InstallDirectory $state.worker_install -ExistenceManifest $statePath
    if ($LASTEXITCODE -ne 0) { throw 'Actual worker denial probes failed or are unverified.' }
    $report = [pscustomobject]@{ run_id=$state.run_id; user_sid=$identity.User.Value; logon_sid=$logon; service_pid=$state.service_pid; worker_denials=$true; stops=$stops }
    Assert-OperatorReport $report $state
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OperatorReportPath -Encoding UTF8
    Write-Output 'PASS: actual operator STOP<=1s with hung main loop, DISARMED startup and actual AppContainer denial probes. Run Contain as administrator.'
    return
}
Assert-OperatorReport (Get-Content -LiteralPath (LocalPath $OperatorReportPath) -Raw | ConvertFrom-Json) $state
if ((ServiceInfo).ProcessId -ne $state.service_pid -or (ServiceInfo).State -ne 'Running') { throw 'Different runtime; cannot contain a different process as drill evidence.' }
if (-not $PSCmdlet.ShouldProcess($serviceName, 'Suspend exact service process, prove retained-handle hard containment<=10s, then restart without entry authority')) { return }
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class ExecutorDrillSuspend {
 [DllImport("kernel32.dll", SetLastError=true)] static extern SafeProcessHandle OpenProcess(uint access, bool inherit, uint pid);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool QueryFullProcessImageName(SafeProcessHandle h, uint flags, StringBuilder path, ref uint size);
 [DllImport("kernel32.dll")] public static extern uint WaitForSingleObject(SafeProcessHandle h, uint ms);
 [DllImport("ntdll.dll")] static extern int NtSuspendProcess(SafeProcessHandle h);
 [DllImport("ntdll.dll")] public static extern int NtResumeProcess(SafeProcessHandle h);
 public static SafeProcessHandle Suspend(uint pid, string expected) {
  var h=OpenProcess(0x00101800, false, pid);
  try {
   if(h.IsInvalid) throw new Win32Exception();
   var path=new StringBuilder(32768); uint size=32768;
   if(!QueryFullProcessImageName(h,0,path,ref size) || !String.Equals(path.ToString(),expected,StringComparison.OrdinalIgnoreCase)) throw new Exception("Service process image mismatch");
   if(NtSuspendProcess(h)!=0) throw new Exception("Exact process suspension failed");
   return h;
  } catch { h.Dispose(); throw; }
 }
}
'@
$held = $null
try {
    $held = [ExecutorDrillSuspend]::Suspend($state.service_pid, (Join-Path $code 'gym-executor.exe'))
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $reply = & (Join-Path $code 'gym-hardstop.exe') --acknowledge-loss-of-protection 2>&1
    $watch.Stop()
    if ($LASTEXITCODE -ne 0 -or ($reply -join ' ') -notmatch '^CONFIRMED UNPROTECTED:' -or $watch.ElapsedMilliseconds -gt 10000 -or
        [ExecutorDrillSuspend]::WaitForSingleObject($held, 0) -ne 0) { throw 'Hard containment deadline/process-exit evidence failed.' }
    $containMs = $watch.ElapsedMilliseconds
    StartNormal
    # Normal startup always creates a fresh DISARMED gate; actual operator confirms on the next run.
    StopNormal
    & (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1')
    $result = [pscustomobject]@{ run_id=$state.run_id; custody_verified=$state.custody_verified; operator_verified=$true; hard_containment_ms=$containMs;
        stopped_disabled=$true; funded_authority=$false; permission_status='UNVERIFIED'; note='Current custody journal tested; future funded ledger and venue permission/exits remain unqualified.' }
    $result | ConvertTo-Json -Depth 5
} finally {
    try {
        if ($null -ne $held -and [ExecutorDrillSuspend]::WaitForSingleObject($held, 0) -ne 0) {
            [void][ExecutorDrillSuspend]::NtResumeProcess($held)
            & (Join-Path $code 'gym-hardstop.exe') --acknowledge-loss-of-protection
            if ($LASTEXITCODE -ne 0) { throw 'Drill cleanup containment not confirmed; manual hard stop required.' }
        }
    } finally {
        if ($null -ne $held) { $held.Dispose() }
        Invoke-DrillSc @('config', $serviceName, 'start=', 'disabled')
    }
}
