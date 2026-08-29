# HP UEFI Diagnostics installation and offline-test report

Date: 2026-08-29 (Asia/Karachi)

## Result

No installer was launched and no UAC prompt was created. `SP172931` passed all
identity, hash, signature, model, board, and OS applicability checks, but this
computer currently has no supported installation target with an established
non-destructive rollback:

- The only physical disk is the internal NVMe drive.
- Its existing EFI System Partition is 104,857,600 bytes (100 MiB), below HP's
  stated 256 MB minimum for all diagnostic tools.
- No existing `HP_TOOLS` partition or safely inventoried HP UEFI Diagnostics
  installation/removal entry was found.
- Installing to the internal disk could therefore require creating a new
  `HP_TOOLS` partition. HP documents that action but does not publish an exact
  supported uninstall/removal procedure that restores the prior partition
  layout. Manually deleting or editing EFI/HP_TOOLS files is prohibited.
- No removable/USB disk was connected. HP documents that a USB install can
  relabel the device `HP_TOOLS`, and that restoring ordinary USB use requires
  formatting it. Selecting such a device and authorizing its data loss is a
  user decision.

The brief requires the target and exact rollback to be established before the
package is executed. Those preconditions are not met, so stopping before UAC or
installer launch is the required outcome. No disk-versus-USB choice was guessed.

## Package and machine verification

Exact command:

```powershell
$package='C:\Users\Ali\Desktop\jarvis\docs\tasks\laptop-power-lag-hp-downloads\sp172931.exe'
Get-Item -LiteralPath $package | Select-Object FullName,Length,LastWriteTime
Get-FileHash -LiteralPath $package -Algorithm SHA256
Get-AuthenticodeSignature -LiteralPath $package | Select-Object Status,StatusMessage,@{n='SignerSubject';e={$_.SignerCertificate.Subject}},@{n='SignerThumbprint';e={$_.SignerCertificate.Thumbprint}}
Get-ItemProperty -LiteralPath 'HKLM:\HARDWARE\DESCRIPTION\System\BIOS' | Select-Object SystemManufacturer,SystemProductName,SystemSKU,SystemFamily,BaseBoardProduct,BIOSVersion,BIOSReleaseDate
```

Relevant output:

```text
FullName: C:\Users\Ali\Desktop\jarvis\docs\tasks\laptop-power-lag-hp-downloads\sp172931.exe
Length: 50437144
LastWriteTime: 2026-08-29 00:46 local time
SHA-256: 2981B6C92F5AF2B3E7FC6282288D4BE6C6AC6CAC727F208E7BF8635096F23858
Authenticode Status: Valid
StatusMessage: Signature verified.
SignerSubject: CN=HP Inc., O=HP Inc., L=Palo Alto, S=California, C=US
SignerThumbprint: DD48CA569CE21D808A05767D7F502A38B63E1529

SystemManufacturer: HP
SystemProductName: HP OmniBook X Flip Laptop 14-fk0xxx
SystemSKU: BG2S4PA#ABG
SystemFamily: 103C_5335M8 HP OmniBook X
BaseBoardProduct: 8DA7
BIOSVersion: F.10
BIOSReleaseDate: 10/22/2025
```

All values exactly match the approved package and machine evidence. The staged
file was read only and remains unchanged.

## Live HP metadata verification

Official source:
[SP172931 CVA](https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172931.cva)

Exact command:

```powershell
$u='https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172931.cva'
$r=Invoke-WebRequest -Uri $u -UseBasicParsing
$t=$r.Content
if($t -is [byte[]]){$t=[Text.Encoding]::UTF8.GetString($t)}
$lines=$t -split "`r?`n"
$patterns='^Version=','^VendorName=','^SoftpaqNumber=','^SoftPaqSHA256=','^SysId120=','^SysName120=','^W11_25H2=','minimum size of 256MB','FAT or FAT32 partition','UEFI System Partition','SupersededSoftpaqNumber=','^SystemMustBeRebooted='
foreach($p in $patterns){$lines | Where-Object {$_ -match $p}}
```

Relevant output:

```text
HTTP 200; 44852 bytes
Version=10.8.6.0
VendorName=HP
SoftpaqNumber=SP172931
SoftPaqSHA256=2981B6C92F5AF2B3E7FC6282288D4BE6C6AC6CAC727F208E7BF8635096F23858
SysId120=0x8DA7
SysName120=HP OMNIBOOK X FLIP 14 INCH 2-IN-1 LAPTOP NEXT GEN AI
W11_25H2=OEM
SupersededSoftpaqNumber=SP171649
SystemMustBeRebooted=0
- The HP PC Hardware Diagnostics UEFI requires a minimum size of 256MB of disk storage space in order for all the diagnostic tools to be installed or executed on the system.
- The HP PC Hardware Diagnostics UEFI must be run from a FAT or FAT32 partition with the volume name, HP_TOOLS. Alternatively, it can be run from the UEFI System Partition.
```

The CVA's `SystemMustBeRebooted=0` is package metadata. No claim is made about
an actual installer result because the installer was not started.

## Installed state and available targets

Exact inventory command:

```powershell
$roots=@('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')
Get-ItemProperty $roots -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -match 'HP PC Hardware Diagnostics|HP UEFI|UEFI Diagnostics'} | Select-Object DisplayName,DisplayVersion,Publisher,InstallLocation,UninstallString,QuietUninstallString,InstallDate
$paths=@('C:\EFI\HP','C:\System.sav\Util\HPDiags','C:\Program Files\HP\HP PC Hardware Diagnostics Windows','C:\Program Files (x86)\HP\HP PC Hardware Diagnostics Windows','C:\ProgramData\HP\HP PC Hardware Diagnostics')
foreach($p in $paths){[pscustomobject]@{Path=$p;Exists=(Test-Path -LiteralPath $p)}}
Get-Disk | Select-Object Number,FriendlyName,BusType,PartitionStyle,IsBoot,IsSystem,OperationalStatus,Size
Get-Partition | Select-Object DiskNumber,PartitionNumber,DriveLetter,Type,GptType,Size,IsBoot,IsSystem,IsHidden,IsReadOnly
Get-Volume | Select-Object DriveLetter,FileSystemLabel,FileSystem,DriveType,HealthStatus,SizeRemaining,Size
```

Relevant output:

```text
No HP PC Hardware Diagnostics UEFI uninstall/inventory record returned.

C:\EFI\HP                                                    False
C:\System.sav\Util\HPDiags                                   False
C:\Program Files\HP\HP PC Hardware Diagnostics Windows       False
C:\Program Files (x86)\HP\HP PC Hardware Diagnostics Windows False
C:\ProgramData\HP\HP PC Hardware Diagnostics                 False

Disk 0: SAMSUNG MZVL21T0HCLR-00BH1, NVMe, GPT, boot/system,
        Online, 1,024,209,543,168 bytes
No second or removable disk was returned.

Disk 0 partition 1: System/ESP, hidden, no drive letter,
                    104,857,600 bytes
Disk 0 partition 2: Microsoft Reserved, 16,777,216 bytes
Disk 0 partition 3: C:, Basic/NTFS, 1,022,522,032,128 bytes
Disk 0 partition 4: Recovery, 1,028,653,056 bytes
Disk 0 partition 5: Recovery, 533,725,184 bytes
```

The EFI System Partition was not mounted, opened, or modified. Therefore its
contents and any resident diagnostics version remain intentionally unknown.
The safe way to identify a resident UEFI Diagnostics version is the user-visible
`Esc`/`F2` screen after work is saved; this lane did not reboot or enter UEFI.

## Target and rollback evidence

HP's official installation instructions describe two target choices:

- **UEFI Partition on Hard Drive (recommended)**.
- **USB Flash Drive**, with a FAT32 partition; the installer can create or
  rename the volume to `HP_TOOLS`.

Source:
[HP - How to install HP PC Hardware Diagnostics UEFI](https://support.hp.com/us-en/document/c03705107)

The same HP page states that removing Diagnostics from a USB for normal reuse
requires formatting the USB and optionally clearing the `HP_TOOLS` label. That
is a destructive rollback and requires the user to identify an approved,
disposable device and confirm its data may be changed. No USB was present, so
capacity, filesystem, and pre-existing-data disposition could not be recorded.

For hard-disk installation, HP documents selecting the UEFI partition and, when
needed, creating an `HP_TOOLS` partition. The current 100 MiB ESP is below the
CVA's 256 MB minimum and no HP_TOOLS partition exists. Neither the SP172931 CVA
nor the official installation page provides a supported uninstall operation
that restores a newly created partition to the exact pre-install layout. The
only removal-related HP material found describes deleting a partition or EFI
files, which this brief expressly forbids and which is not a non-destructive
rollback.

HP also documents that when the full diagnostics partition is absent, a Basic
System Diagnostics tool embedded in system ROM may appear at `F2`; that is not
evidence that version 10.8.6.0 is installed and it is not a substitute for the
specified package.

Source:
[HP - Using HP PC Hardware Diagnostics UEFI](https://support.hp.com/us-en/document/ish_12139597-12226032-16)

## Installation, reboot, and offline tests

Not completed, by design:

- `Start-Process -FilePath $package -Verb RunAs -PassThru` was **not** run.
- No UAC, license, target picker, Install/Next/Finish, or reboot prompt appeared.
- No package extraction or HP installer log was created.
- No partition, volume label, USB, EFI content, firmware, BIOS, driver, device,
  service, registry, power plan, thermal policy, or fan setting was changed.
- No post-install version/invariant checks were applicable because there was no
  installation.
- No reboot, shutdown, UEFI entry, Fast Test, Extensive Test, Power Source,
  Battery, System Board, or Fan test was started.
- No offline result, safety observation, or 24-digit Failure ID exists yet.

## Exact blocker and next handoff

The user must choose one target path after being told its impact:

1. **Internal disk:** requires HP to demonstrate in the visible installer that
   it can use a supported target without resizing/creating a partition, and a
   documented removal path must be established first. Current evidence does
   not meet either condition.
2. **USB:** the user must connect and identify a disposable/approved USB drive
   of at least 256 MB and explicitly confirm that its contents and label may be
   changed. HP's documented rollback is reformatting the USB, which erases it.

Choosing USB is not authorized merely because the internal-disk target is
blocked. After the user chooses and the target metadata/rollback are recorded,
the verified package can be launched visibly and the user can handle UAC,
license acceptance, target selection, and final Install confirmation. Until
then, installation would violate the brief.
