# Read-only validation of the administrator's protected, current-runtime existence attestation.
[CmdletBinding()]
param([string]$Path, [switch]$SelfTest)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$trusted = @('S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
function Assert-MutationPolicy($Raw, [bool]$Directory) {
    if ($null -eq $Raw.DiscretionaryAcl) { throw 'Null drill manifest DACL rejected.' }
    if (-not $Directory -and -not ([int]$Raw.ControlFlags -band [int][Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)) { throw 'Manifest DACL must be protected.' }
    $mutationMask = if ($Directory) { 0x500d0040 } else { 0x500d0156 }
    foreach ($ace in $Raw.DiscretionaryAcl) {
        if ([int]$ace.AceFlags -band [int][Security.AccessControl.AceFlags]::InheritOnly) { continue }
        if ($ace.AceType -notin @([Security.AccessControl.AceType]::AccessAllowed, [Security.AccessControl.AceType]::AccessDenied)) { throw 'Unsupported drill manifest ACL.' }
        if ($ace.AceType -eq [Security.AccessControl.AceType]::AccessAllowed -and
            ([int64]$ace.AccessMask -band $mutationMask) -ne 0 -and $ace.SecurityIdentifier.Value -notin $trusted) { throw 'Untrusted mutation of drill manifest or ancestor.' }
    }
}
if ($SelfTest) {
    # Creating unrelated children at C:\ cannot replace a protected descendant.
    Assert-MutationPolicy ([Security.AccessControl.RawSecurityDescriptor]::new('O:BAD:P(A;;FA;;;BA)(A;;0x00000004;;;AU)')) $true
    foreach ($case in @(@($false,'0x00000002'), @($true,'0x00000040'), @($true,'0x00040000'))) {
        $rejected = $false
        try { Assert-MutationPolicy ([Security.AccessControl.RawSecurityDescriptor]::new("O:BAD:P(A;;FA;;;BA)(A;;$($case[1]);;;AU)")) $case[0] } catch { $rejected=$true }
        if (-not $rejected) { throw 'Manifest policy self-test accepted untrusted mutation.' }
    }
    Write-Output 'PASS: manifest leaf writes and ancestor delete-child/DACL mutation rejected; unrelated ancestor child creation allowed.'
    return
}
$expected = Join-Path $env:ProgramFiles 'TradingGYM\Executor\installed-host-drill.json'
if ([IO.Path]::GetFullPath($Path) -ine [IO.Path]::GetFullPath($expected)) { throw 'Only the fixed protected drill manifest is accepted.' }
$item = Get-Item -LiteralPath $Path -Force
if ($item.PSIsContainer -or $item.Length -gt 65536) { throw 'Invalid drill manifest file.' }
while ($null -ne $item) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked drill manifest or ancestor rejected.' }
    $acl = Get-Acl -LiteralPath $item.FullName
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $trusted) { throw 'Untrusted drill manifest owner or ancestor.' }
    $raw = [Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorBinaryForm(), 0)
    Assert-MutationPolicy $raw $item.PSIsContainer
    $item = if ($item.PSIsContainer) { $item.Parent } else { $item.Directory }
}
