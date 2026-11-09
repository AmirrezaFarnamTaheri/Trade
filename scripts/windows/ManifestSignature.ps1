#Requires -Version 5.1
<# Native ECDSA P-256 / SHA-256 check of an executor update manifest; dot-source, then call Test-ManifestSignature.
   Runs inside the elevated update session using only .NET Framework, never user-writable code.
   Key file: JSON {"curve":"P-256","x":hex,"y":hex}. Signature file: hex of the 64-byte r||s (IEEE P1363) form.
   Produced by `gymctl release-keygen` and `gymctl release-sign`.
#>
function ConvertFrom-HexBytes([string]$Hex, [int]$Length) {
    if ($Hex -cnotmatch "^[0-9a-f]{$($Length * 2)}$") { throw 'Malformed hex value.' }
    $bytes = New-Object byte[] $Length
    for ($i = 0; $i -lt $Length; $i++) { $bytes[$i] = [Convert]::ToByte($Hex.Substring($i * 2, 2), 16) }
    return ,$bytes
}

function Test-ManifestSignature([string]$Manifest, [string]$Signature, [string]$PublicKey) {
    foreach ($path in @($Manifest, $Signature, $PublicKey)) {
        $item = Get-Item -LiteralPath $path
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -gt 4096) {
            throw 'Regular bounded manifest, signature and key files required.'
        }
    }
    $key = [IO.File]::ReadAllText($PublicKey) | ConvertFrom-Json
    if ($key.curve -cne 'P-256') { throw 'Pinned update key must be ECDSA P-256.' }
    $parameters = New-Object Security.Cryptography.ECParameters
    $parameters.Curve = [Security.Cryptography.ECCurve+NamedCurves]::nistP256
    $point = New-Object Security.Cryptography.ECPoint
    $point.X = ConvertFrom-HexBytes $key.x 32
    $point.Y = ConvertFrom-HexBytes $key.y 32
    $parameters.Q = $point
    $ecdsa = [Security.Cryptography.ECDsa]::Create($parameters)
    try {
        $sig = ConvertFrom-HexBytes ([IO.File]::ReadAllText($Signature).Trim()) 64
        $data = [IO.File]::ReadAllBytes($Manifest)
        return $ecdsa.VerifyData($data, $sig, [Security.Cryptography.HashAlgorithmName]::SHA256)
    } finally { $ecdsa.Dispose() }
}
