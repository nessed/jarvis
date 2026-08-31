$ErrorActionPreference = 'Continue'
$outputPath = 'C:\Users\Ali\Desktop\jarvis\diagnostics\laptop-power-lag\bios-f11-preflight-security.txt'

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add('TIMESTAMP ' + (Get-Date -Format o))
$lines.Add('SECURE BOOT')
try {
    $lines.Add('Enabled=' + [string](Confirm-SecureBootUEFI))
} catch {
    $lines.Add('Error=' + $_.Exception.Message)
}

$lines.Add('TPM')
try {
    $tpm = Get-Tpm
    $lines.Add(($tpm | Select-Object TpmPresent,TpmReady,TpmEnabled,TpmActivated,TpmOwned,RestartPending,ManufacturerIdTxt,ManufacturerVersion | Format-List | Out-String).TrimEnd())
} catch {
    $lines.Add('Error=' + $_.Exception.Message)
}

$lines.Add('BITLOCKER POWERSHELL')
try {
    $bitLocker = Get-BitLockerVolume -MountPoint 'C:'
    $lines.Add(($bitLocker | Select-Object MountPoint,VolumeStatus,ProtectionStatus,EncryptionMethod,LockStatus | Format-List | Out-String).TrimEnd())
} catch {
    $lines.Add('Error=' + $_.Exception.Message)
}

$lines.Add('BITLOCKER MANAGE-BDE')
$lines.Add(((manage-bde.exe -status C: 2>&1) | Out-String).TrimEnd())

$lines.Add('POWER SOURCE')
$battery = Get-CimInstance Win32_Battery
$lines.Add(($battery | Select-Object Name,BatteryStatus,EstimatedChargeRemaining,Status | Format-List | Out-String).TrimEnd())
$batteryStatus = Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus -ErrorAction SilentlyContinue
$lines.Add(($batteryStatus | Select-Object PowerOnline,Discharging,Charging,Critical,RemainingCapacity,Voltage,Rate | Format-List | Out-String).TrimEnd())

$lines.Add('PENDING RESTART')
$pending = [pscustomobject]@{
    CBSRebootPending = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
    WURebootRequired = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
    PendingFileRenameOperations = [bool](Get-ItemPropertyValue -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue)
}
$lines.Add(($pending | Format-List | Out-String).TrimEnd())

$parent = Split-Path -Parent $outputPath
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$lines | Set-Content -LiteralPath $outputPath -Encoding UTF8
