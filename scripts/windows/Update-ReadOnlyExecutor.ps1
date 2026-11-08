#Requires -Version 5.1
<# Publish an explicit hash-pinned binary bundle to a stopped, disabled service.
   No service start, credential operation, journal access or automatic restart.
   Prior code and a sanitized receipt remain in an administrator-only backup.
#>
[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='High')]
param([string]$BinaryDirectory, [string]$HashManifest, [switch]$SelfTest)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$names = @('gym-stopctl.exe','gym-hardstop.exe','gym-provision.exe','gym-account-read.exe',
    'gym-ceiling.exe','gym-review.exe','gym-research-worker.exe','gym-executor.exe')
function Read-BundleHashes([string]$Text) {
    if ($Text.Length -gt 4096) { throw 'Oversized bundle manifest.' }
    $hashes = @{}
    foreach ($line in ($Text -split '\r?\n')) {
        if (-not $line) { continue }
        if ($line -cnotmatch '^([0-9a-fA-F]{64})  ([a-z-]+\.exe)$') { throw 'Expected SHA256, two spaces and an exact executable name.' }
        $digest, $name = $Matches[1], $Matches[2]
        if ($name -cnotin $names -or $hashes.ContainsKey($name)) { throw 'Unknown or duplicate bundle member.' }
        $hashes[$name] = $digest.ToUpperInvariant()
    }
    if ($hashes.Count -ne $names.Count) { throw 'Complete fixed binary bundle required.' }
    return $hashes
}
function Stream-Hash([IO.Stream]$Stream) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $Stream.Position=0; return [BitConverter]::ToString($sha.ComputeHash($Stream)).Replace('-','') }
    finally { $Stream.Position=0; $sha.Dispose() }
}
if ($SelfTest) {
    $valid = ($names | ForEach-Object { ('1' * 64) + '  ' + $_ }) -join "`n"
    if ((Read-BundleHashes $valid).Count -ne 8) { throw 'Manifest self-test failed.' }
    foreach ($bad in @($valid + "`n" + ('2' * 64) + '  gym-review.exe', $valid.Replace('gym-review.exe','unknown.exe'),
        $valid.Replace('gym-review.exe','../gym-review.exe'), $valid.Replace('gym-review.exe','GYM-REVIEW.exe'),
        $valid.Substring(1), $valid.Replace('  gym-review.exe',' gym-review.exe'), $valid + [char]0, '')) {
        $rejected=$false
        try { $null=Read-BundleHashes $bad } catch { $rejected=$true }
        if (-not $rejected) { throw 'Invalid bundle manifest accepted.' }
    }
    $root = Join-Path ([IO.Path]::GetTempPath()) ('gym-publication-' + [guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($root)
    $source, $target, $backup = (Join-Path $root 'source'), (Join-Path $root 'target'), (Join-Path $root 'backup')
    try {
        [IO.File]::WriteAllText($source,'new'); [IO.File]::WriteAllText($target,'old')
        $pinned=[IO.File]::Open($source,'Open','Read','Read')
        try {
            $first=Stream-Hash $pinned
            if ($first -cne (Stream-Hash $pinned)) { throw 'Pinned hashing changed.' }
            $blocked=$false
            try { $writer=[IO.File]::Open($source,'Open','Write','ReadWrite'); $writer.Dispose() } catch { $blocked=$true }
            if (-not $blocked) { throw 'Source write was not excluded.' }
        } finally { $pinned.Dispose() }
        [IO.File]::Replace($source,$target,$backup)
        if ([IO.File]::ReadAllText($target) -cne 'new' -or [IO.File]::ReadAllText($backup) -cne 'old') { throw 'Replacement did not preserve old bytes.' }
        [IO.File]::Replace($backup,$target,$source)
        if ([IO.File]::ReadAllText($target) -cne 'old') { throw 'Rollback did not restore old bytes.' }
    } finally {
        foreach ($path in @($source,$target,$backup)) { if ([IO.File]::Exists($path)) { [IO.File]::Delete($path) } }
        [IO.Directory]::Delete($root)
    }
    Write-Output 'PASS: strict complete manifests, source pinning, atomic replacement and retained-byte rollback.'
    return
}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'A separate elevated administrator setup session is required.' }
$code=Join-Path $env:ProgramFiles 'TradingGYM\Executor'
$marker=Join-Path $code 'update.pending'
function Assert-Stopped {
    $service=Get-CimInstance Win32_Service -Filter "Name = 'TradingGYMExecutor'"
    if ($null -eq $service -or $service.State -ne 'Stopped' -or $service.StartMode -ne 'Disabled' -or
        $service.StartName -ine 'NT AUTHORITY\LocalService' -or $service.PathName.Trim() -ine ('"' + (Join-Path $code 'gym-executor.exe') + '"')) { throw 'Expected fixed LocalService image, STOPPED and DISABLED.' }
}
Assert-Stopped
if (Test-Path -LiteralPath $marker) { throw 'An earlier incomplete update is preserved; inspect its backup before proceeding.' }
& (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1') -MigrationPreflight
foreach ($path in @($BinaryDirectory,$HashManifest)) {
    if (-not $path -or $path -notmatch '^[A-Za-z]:\\' -or $path.Substring(3) -match '[:"\r\n]' -or $path -match '(^|\\)\.\.?($|\\)') { throw 'Explicit local absolute bundle paths required.' }
}
$manifestFile=Get-Item -LiteralPath $HashManifest
if ($manifestFile.PSIsContainer -or ($manifestFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $manifestFile.Length -gt 4096) { throw 'Regular bounded hash manifest required.' }
$expected=Read-BundleHashes ([IO.File]::ReadAllText($manifestFile.FullName))
$serviceSid=([Security.Principal.NTAccount]::new('NT SERVICE\TradingGYMExecutor')).Translate([Security.Principal.SecurityIdentifier]).Value
$operatorSid=(Get-Content -LiteralPath (Join-Path $code 'stop-user.sid') -Raw).Trim()
function Seal([string]$Path, [bool]$Directory, [bool]$ServiceRead, [bool]$OperatorRead) {
    $acl=if ($Directory) { [Security.AccessControl.DirectorySecurity]::new() } else { [Security.AccessControl.FileSecurity]::new() }
    $acl.SetAccessRuleProtection($true,$false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    foreach ($sid in @('S-1-5-18','S-1-5-32-544')) { $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow')) }
    if ($ServiceRead) { $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($serviceSid),'ReadAndExecute','Allow')) }
    if ($OperatorRead) { $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($operatorSid),'ReadAndExecute','Allow')) }
    Set-Acl -LiteralPath $Path -AclObject $acl
}
$streams=@{}; $published=[Collections.Generic.List[string]]::new(); $prior=@{}
$backupRoot=$null; $mutationStarted=$false
$runId=[guid]::NewGuid().ToString('N')
$report=[ordered]@{ at=[DateTime]::UtcNow.ToString('o'); status='PREFLIGHT'; source_hashes=$expected; prior_hashes=$prior; data_changed=$false; service_started=$false; funded_authority=$false }
try {
    foreach ($name in $names) {
        $sourceFile=Get-Item -LiteralPath (Join-Path $BinaryDirectory $name)
        if ($sourceFile.PSIsContainer -or ($sourceFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $sourceFile.Length -lt 2 -or $sourceFile.Length -gt 67108864) { throw 'Regular bounded bundle executable required.' }
        $streams[$name]=[IO.File]::Open($sourceFile.FullName,'Open','Read','Read')
        if ((Stream-Hash $streams[$name]) -cne $expected[$name]) { throw 'Bundle hash differs from approved manifest.' }
        if ($streams[$name].ReadByte() -ne 77 -or $streams[$name].ReadByte() -ne 90) { throw 'Windows executable header required.' }
        $streams[$name].Position=0
    }
    if (-not $PSCmdlet.ShouldProcess($code,'Publish the complete pinned bundle with retained-code rollback; preserve custody and journals; no service start')) { return }
    $backupRoot=Join-Path $code ('backup-' + $runId)
    [void](New-Item -ItemType Directory -Path $backupRoot)
    Seal $backupRoot $true $false $false
    foreach ($name in $names) {
        $stage=Join-Path $backupRoot ('new-' + $name)
        $out=[IO.File]::Open($stage,'CreateNew','Write','None')
        try { $streams[$name].CopyTo($out); $out.Flush($true) } finally { $out.Dispose() }
        $operatorRead=$name -in @('gym-stopctl.exe','gym-hardstop.exe','gym-review.exe','gym-research-worker.exe')
        Seal $stage $false $true $operatorRead
        $staged=[IO.File]::OpenRead($stage)
        try { if ((Stream-Hash $staged) -cne $expected[$name]) { throw 'Staged bundle hash mismatch.' } } finally { $staged.Dispose() }
    }
    Assert-Stopped
    $mark=[IO.File]::Open($marker,'CreateNew','Write','None')
    $mutationStarted=$true
    try { $bytes=[Text.Encoding]::ASCII.GetBytes($runId); $mark.Write($bytes,0,$bytes.Length); $mark.Flush($true) } finally { $mark.Dispose() }
    Seal $marker $false $true $false
    # Publish the service image last. No helper can start or change SCM configuration.
    foreach ($name in $names) {
        Assert-Stopped
        $target=Join-Path $code $name
        $old=Join-Path $backupRoot ('old-' + $name)
        $prior[$name]=$null
        if (Test-Path -LiteralPath $target) {
            $stream=[IO.File]::OpenRead($target)
            try { $prior[$name]=Stream-Hash $stream } finally { $stream.Dispose() }
        }
        $published.Add($name)
        $stage=Join-Path $backupRoot ('new-' + $name)
        if ($null -ne $prior[$name]) { [IO.File]::Replace($stage,$target,$old); Seal $old $false $false $false }
        else { [IO.File]::Move($stage,$target) }
        Seal $target $false $true ($name -in @('gym-stopctl.exe','gym-hardstop.exe','gym-review.exe','gym-research-worker.exe'))
    }
    & (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1') -MigrationPreflight
    if ([IO.File]::ReadAllText($marker) -cne $runId) { throw 'Publication marker changed.' }
    [IO.File]::Delete($marker)
    & (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1')
    $report.status='PUBLISHED_STOPPED_DISABLED'
} catch {
    $failure=$_
    $report.status='FAILED_BEFORE_PUBLICATION'
    if ($mutationStarted) {
        $report.status='INCOMPLETE_REQUIRES_RECOVERY'
        try {
            Assert-Stopped
            if (-not [IO.File]::Exists($marker)) { [IO.File]::WriteAllText($marker,$runId); Seal $marker $false $true $false }
            for ($index=$published.Count-1; $index -ge 0; $index--) {
                $name=$published[$index]; $target=Join-Path $code $name; $old=Join-Path $backupRoot ('old-' + $name)
                if ([IO.File]::Exists($old)) {
                    [IO.File]::Replace($old,$target,(Join-Path $backupRoot ('failed-' + $name)))
                    Seal $target $false $true ($name -in @('gym-stopctl.exe','gym-hardstop.exe','gym-review.exe','gym-research-worker.exe'))
                } elseif ($null -eq $prior[$name] -and [IO.File]::Exists($target)) {
                    $stream=[IO.File]::OpenRead($target)
                    try { if ((Stream-Hash $stream) -cne $expected[$name]) { throw 'Rollback target changed.' } } finally { $stream.Dispose() }
                    [IO.File]::Delete($target)
                }
            }
            & (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1') -MigrationPreflight
            if ([IO.File]::ReadAllText($marker) -cne $runId) { throw 'Rollback marker changed.' }
            [IO.File]::Delete($marker)
            $report.status='ROLLED_BACK_STOPPED_DISABLED'
        } catch { Write-Warning 'Rollback incomplete. Publication marker retained; service must remain stopped and disabled.' }
    }
    throw $failure
} finally {
    foreach ($stream in $streams.Values) { $stream.Dispose() }
    if ($null -ne $backupRoot) {
        $receipt=Join-Path $backupRoot 'receipt.json'
        [IO.File]::WriteAllText($receipt,($report | ConvertTo-Json -Depth 5))
        Seal $receipt $false $false $false
        Write-Output ('Publication receipt: ' + $receipt)
    }
}
