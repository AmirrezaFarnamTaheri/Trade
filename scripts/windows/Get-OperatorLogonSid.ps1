# Read the current process token's OS-issued TokenLogonSid (TOKEN_INFORMATION_CLASS 28).
# This is a read-only identity query; it does not change privileges or token state.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$source = @'
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
                required < (IntPtr.Size == 8 ? 8 : 4) || required > 65536)
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
    Add-Type -TypeDefinition $source -ErrorAction Stop
}
$sid = [TradeTokenLogonSid]::Get()
if ($sid -notmatch '^S-1-5-5-[0-9]+-[0-9]+$') {
    throw 'Windows did not return a valid logon SID.'
}
Write-Output $sid
