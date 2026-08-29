# HP-supported resolution for persistent battery-only lag

Accessed: 2026-08-29 (Asia/Karachi)

## Answer

The machine resolves unambiguously to HP product number `BG2S4PA` (regional
suffix `#ABG`), model record `2103018136`, family `14-fk0000`, platform
`Enstrom_25C1`, and system-board ID `8DA7`. No serial number or UUID was read or
recorded.

HP does **not** publish an exact-SKU AMD PMF, AMD UMDF Sensor, Smart Sense,
thermal-framework, or general AMD chipset package for Windows 11 25H2. The HP
graphics package is older than the installed graphics driver. Therefore the
catalogue does not provide a justified PMF/sensor/graphics reinstall or update
for this symptom.

HP does publish BIOS F.11 (`SP172952`) for this exact board. It supersedes the
installed F.10 and is the minimum version in HP security bulletin HPSBHF04134.
Its only symptom-relevant release note is the generic phrase "improved system
stability"; neither the bulletin nor its release notes identify battery-only
lag, PMF, sensors, or thermal throttling. It is an applicable update, but it is
not established as the fix for this fault. No BIOS package was staged or run.

The one best HP-supported next action is to run the built-in HP UEFI hardware
diagnostics before changing firmware: Fast Test first; if clear, Extensive
Test; then Power Source, Battery, System Board, and Fan component tests. This
runs outside Windows and is the cleanest way to distinguish battery/power-path
or cooling hardware from Windows/driver behavior. Record any 24-digit Failure
ID and the test name. This judgment is supported by the mandated high-confidence
consult at
`docs/consults/2026-08-29-laptop-hp-next-action/response.md`.

## Exact identity and installed state

Read-only inventory command (the selected fields intentionally exclude serial
and UUID properties):

```powershell
$cs=Get-CimInstance Win32_ComputerSystem; [pscustomobject]@{Manufacturer=$cs.Manufacturer;Model=$cs.Model;SystemSKUNumber=$cs.SystemSKUNumber;SystemFamily=$cs.SystemFamily} | Format-List; $csp=Get-CimInstance Win32_ComputerSystemProduct; [pscustomobject]@{Vendor=$csp.Vendor;Name=$csp.Name;Version=$csp.Version;SKUNumber=$csp.SKUNumber} | Format-List; Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,@{n='ReleaseDate';e={$_.ReleaseDate.ToString('yyyy-MM-dd')}} | Format-List; Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture | Format-List; Get-CimInstance Win32_Processor | Select-Object Name,Manufacturer,MaxClockSpeed | Format-List; Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID,DriverVersion,@{n='DriverDate';e={$_.DriverDate.ToString('yyyy-MM-dd')}} | Format-List
```

Relevant output:

```text
Manufacturer: HP
Model: HP OmniBook X Flip Laptop 14-fk0xxx
SystemSKUNumber: BG2S4PA#ABG
SystemFamily: 103C_5335M8 HP OmniBook X
BIOS: Insyde F.10, 2025-10-22
OS: Microsoft Windows 11 Pro, 10.0.26200, 64-bit
CPU: AMD Ryzen AI 7 350 w/ Radeon 860M
GPU: AMD Radeon(TM) 860M Graphics
GPU PNP ID: PCI\VEN_1002&DEV_1114&SUBSYS_8DA7103C&REV_C2\4&27F652EA&0&0041
GPU driver: 32.0.31035.1003, 2026-07-24
```

Board and full Windows build command:

```powershell
Get-ItemProperty -LiteralPath 'HKLM:\HARDWARE\DESCRIPTION\System\BIOS' | Select-Object SystemManufacturer,SystemProductName,SystemSKU,SystemFamily,BaseBoardManufacturer,BaseBoardProduct,BIOSVendor,BIOSVersion,BIOSReleaseDate | Format-List
Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' | Select-Object ProductName,DisplayVersion,CurrentBuild,UBR,EditionID,InstallationType | Format-List
```

Relevant output:

```text
BaseBoardProduct: 8DA7
SystemSKU: BG2S4PA#ABG
DisplayVersion: 25H2
CurrentBuild: 26200
UBR: 9168
EditionID: Professional
```

Microsoft identifies build 26200 as Windows 11 25H2; build 26200.9168 is the
August 2026 servicing level. Sources: [Microsoft 25H2 build mapping](https://learn.microsoft.com/en-us/windows-insider/release-notes/release-preview-24h2-25h2/build-26100-8514-26200-8514)
and [KB5121003](https://support.microsoft.com/en-us/servicing/os/windows-11/2026/08/kb5121003-windows-11-24h2-25h2-security-update).

Driver command:

```powershell
$ids=@('ACPI\AMDI0107\0','ACPI\AMDI0080\1'); foreach($id in $ids){Get-PnpDevice -InstanceId $id | Select-Object Status,Class,FriendlyName,InstanceId,Problem | Format-List; Get-CimInstance Win32_PnPSignedDriver | Where-Object {$_.DeviceID -eq $id} | Select-Object DeviceName,DeviceID,DriverProviderName,DriverVersion,@{n='DriverDate';e={$_.DriverDate.ToString('yyyy-MM-dd')}},InfName,IsSigned,Signer | Format-List}
Get-CimInstance Win32_PnPSignedDriver | Where-Object {$_.DeviceID -like 'PCI\VEN_1002&DEV_1114*'} | Select-Object DeviceName,DeviceID,DriverProviderName,DriverVersion,@{n='DriverDate';e={$_.DriverDate.ToString('yyyy-MM-dd')}},InfName,IsSigned,Signer | Format-List
```

Relevant output:

| Component | State | Installed driver | INF | Provider/signature |
|---|---|---|---|---|
| AMD PMF `ACPI\AMDI0107\0` | Started/OK, no problem | 26.10.15.0, 2026-07-24 | `oem125.inf` | AMD; signed by Microsoft Windows Hardware Compatibility Publisher |
| AMD UMDF Sensor `ACPI\AMDI0080\1` | Started/OK, no problem | 1.1.0.37, 2026-01-09 | `oem97.inf` | AMD; signed by Microsoft Windows Hardware Compatibility Publisher |
| Radeon 860M, `VEN_1002&DEV_1114`, subsystem `8DA7103C` | present | 32.0.31035.1003, 2026-07-24 | `oem52.inf` | AMD; signed by Microsoft Windows Hardware Compatibility Publisher |

Management-application command:

```powershell
Get-AppxPackage | Where-Object {$_.Name -match 'HP|myHP|HPAudio|SystemEvent|Smart'} | Select-Object Name,Version,Publisher | Sort-Object Name
$roots=@('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'); Get-ItemProperty $roots -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -match 'HP|AMD.*(Chipset|Software)'} | Select-Object DisplayName,DisplayVersion,Publisher,InstallDate | Sort-Object DisplayName
```

Relevant output:

```text
HP Thermal Control                 1.11.60.0
HP AI Experience Center           2.6.1003.0
HP Support Assistant              9.54.3.0
AMD Chipset Software              8.08.12.551
AMD Software                      26.7.1
```

## Exact HP product and catalogue resolution

HP's public typeahead lookup for the non-secret product number returned model
record `2103018136`:

```powershell
Invoke-WebRequest -Uri 'https://support.hp.com/typeahead?q=BG2S4PA&cc=us&lc=en' -UseBasicParsing
```

```json
{"matches":[{"productId":2103512713,"productname":"BG2S4PAR"},{"productId":2103018136,"productname":"BG2S4PA"}],"totalCount":2}
```

The no-serial HP product-specification API mapped that record as follows:

```text
productName: HP OmniBook X Flip 14 inch 2-in-1 Laptop Next Gen AI PC 14-fk0000 (AK5G3AV)
productNumber: BG2S4PA
productNumberOid: 2103018136
productSeriesOid: 2102790278
productPlatform: Enstrom_25C1
productLineCode: M8
```

Request used:

```powershell
$body=@{cc='us';lc='en';utcOffset='M0700';devices=@(@{seriesOid=$null;modelOid=2103018136;serialNumber=$null;displayProductNumber='BG2S4PA';countryOfPurchase='au'});skipSyncCall=$false;captchaToken=''} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri 'https://support.hp.com/wcc-services/profile/devices/warranty/specs?cache=true' -ContentType 'application/json' -Body $body
```

Official product page: [HP model record 2102790295](https://support.hp.com/us-en/product/setup-user-guides/hp-omnibook-x-flip-14-inch-2-in-1-laptop-next-gen-ai-pc-14-fk0000/model/2102790295).

HP's OS endpoint offered Windows 11 25H2, 24H2, and generic Windows 11 for this
exact product record:

```powershell
Invoke-RestMethod -Uri 'https://support.hp.com/wcc-services/swd-v2/osVersionData?cc=us&lc=en&productOid=2103018136'
```

The exact-SKU 25H2 catalogue request was:

```powershell
$id='110141152151151213134311128151108159116121510139'; $body=@{productLineCode='M8';lc='en';cc='us';osTMSId=$id;osName='Windows';productNumberOid=2103018136;productSeriesOid=2102790278;platformId=$id}|ConvertTo-Json; Invoke-RestMethod -Method Post -Uri 'https://support.hp.com/wcc-services/swd-v2/driverDetails' -ContentType 'application/json' -Body $body
```

The complete returned categories were BIOS, Network, Audio, Software-PoS,
Chipset, Diagnostic, Keyboard/Mouse/Input, Software-Solutions, and Graphics.
There was no PMF, AMD UMDF Sensor/SFH, Smart Sense, thermal framework, or
general AMD chipset package in the response. The exact family support page also
currently reports no model alerts: [HP 14-fk0000 support page](https://support.hp.com/us-en/product/setup-user-guides/hp-omnibook-x-flip-14in-2in-1-laptop-next-gen-ai-pc-14-fk0000/2102790278).

## Installed-versus-offered decision table

| Candidate | HP offering and applicability evidence | Installed comparison | Release-note connection | Classification |
|---|---|---|---|---|
| BIOS | F.11 Rev.A, `SP172952`, effective 2026-05-11; CVA lists `SYSID\8DA7`, Windows 11, supersedes `SP165946` F.10; HP bulletin lists 14-fk0xxx minimum F.11 | F.10, board 8DA7 | "Improved system stability"; security bulletin fixes InsydeH2O update-tool buffer overflows, not battery lag | `applicable-update` (security/stability; not proven explanatory) |
| BIOS shown in exact-SKU 25H2 catalogue | F.10 Rev.A, `SP165946`, 2025-11-25, routine | same version as installed | "Improved system stability" | `already-current`, but superseded by the separately published F.11 package and bulletin |
| AMD PMF | no offering in exact-SKU 25H2 catalogue | 26.10.15.0, started/OK | none published | `already-current` as far as HP's catalogue can establish; no HP repair package |
| AMD UMDF Sensor | no offering in exact-SKU 25H2 catalogue | 1.1.0.37, started/OK | none published | `already-current` as far as HP's catalogue can establish; no HP repair package |
| AMD chipset / thermal framework / Smart Sense | no such package in exact-SKU 25H2 response | chipset bundle 8.08.12.551; HP Thermal Control 1.11.60.0 | none published | no verified HP candidate |
| AMD graphics | 32.0.22068.0 Rev.D, `SP173172`, 2026-05-18, routine, exact-SKU API | installed 32.0.31035.1003 is numerically newer | generic reliability only | `applicable-but-not-explanatory`; do not downgrade/reinstall from this evidence |
| HP Support Assistant | 9.54.3.0 Rev.A, `SP173774`, 2026-07-07 | installed 9.54.3.0 | updated app only | `already-current` |
| HP PC Hardware Diagnostics UEFI | 10.8.6.0 Rev.A, `SP172931`, 2026-05-11; CVA explicitly includes `SysId120=0x8DA7` and Windows 11 25H2 | no safely readable installed UEFI version was found; no EFI partition was mounted or changed | improves Fan, Serial Port, Drive Self-Test and general reliability; diagnostic, not remediation | `applicable-but-not-explanatory`; use as the supported diagnostic path |
| AMD NPU / Windows Studio Effects | NPU 32.00.0203.329 `SP173329`; Studio Effects 2.0.11.0 `SP156960` | not material to the reported battery transition fault | NPU reliability / routine camera-effects updates | `not-applicable` to this symptom |

BIOS sources: [F.11 CVA](https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172952.cva),
[F.11 release notes](https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172952.html),
[F.10 CVA](https://ftp.hp.com/pub/softpaq/sp165501-166000/sp165946.cva),
and [HP security bulletin HPSBHF04134](https://support.hp.com/kz-ru/document/ish_15277136-15277140-16?fallbackLocale=us-en&validated=true).
The bulletin is High severity, dated 2026-07-13 and updated 2026-07-14; it lists
CVE-2025-12050 through CVE-2025-12053 and identifies F.11/SP172952 for
14-fk0xxx.

Diagnostics source: [SP172931 CVA](https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172931.cva).
HP states that this package requires at least 256 MB and runs from a FAT/FAT32
`HP_TOOLS` partition or the UEFI System Partition. It can install to disk or USB;
that installation was deliberately not performed.

## Staged official artifact

Only the non-BIOS diagnostics package was preserved. It was downloaded directly
from HP and was not executed or unpacked.

```text
Filename: sp172931.exe
Purpose: HP PC Hardware Diagnostics UEFI 10.8.6.0 Rev.A
Source: https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172931.exe
Size: 50,437,144 bytes
SHA-256: 2981B6C92F5AF2B3E7FC6282288D4BE6C6AC6CAC727F208E7BF8635096F23858
HP CVA SHA-256: 2981B6C92F5AF2B3E7FC6282288D4BE6C6AC6CAC727F208E7BF8635096F23858
Authenticode: Valid - "Signature verified."
Signer: HP Inc.
Signer issuer: DigiCert Trusted G4 Code Signing RSA4096 SHA384 2021 CA1
Signer thumbprint: DD48CA569CE21D808A05767D7F502A38B63E1529
Signer validity: 2026-01-26 through 2027-01-26
Timestamp authority: DigiCert SHA256 RSA4096 Timestamp Responder 2025 1
```

Verification command and output basis:

```powershell
$file='C:\Users\Ali\Desktop\jarvis\docs\tasks\laptop-power-lag-hp-downloads\sp172931.exe'; Get-Item -LiteralPath $file; Get-FileHash -LiteralPath $file -Algorithm SHA256; Get-AuthenticodeSignature -LiteralPath $file
```

No graphics, chipset, PMF, sensor, application, or BIOS package was staged.

## Exact user-only UEFI diagnostic procedure

This is an offline, sensory/interactive step; it cannot be driven safely from
the current Windows session.

1. Save work. Hold the power button for at least five seconds to turn the PC
   off.
2. Turn it on and immediately press `Esc` repeatedly, about once per second.
   When the Startup Menu appears, press `F2`.
3. In HP PC Hardware Diagnostics UEFI, choose **System Tests > Fast Test > Run
   once**. If pass one is clear, choose **Continue > Run once** for pass two.
4. If both passes are clear, choose **System Tests > Extensive Test > Run
   once**. HP says this can take two hours or more.
5. Then choose **Component Tests** and run the available **Power Source**,
   **Battery**, **System Board**, and **Fan** tests. For the battery-path fault,
   perform the Battery test with AC disconnected if the on-screen instructions
   permit it.
6. Photograph or write down each result. If anything fails, preserve the test
   name and 24-digit Failure ID from the result or **Test Logs**.

HP's official procedure and test descriptions are at
[HP PCs - Testing for hardware failures](https://support.hp.com/ca-en/document/ish_2854458-2733239-16).
HP says Fast Test is about four minutes, Extensive Test is two hours or more,
and the Battery Test is about two minutes (calibration can take much longer).

If the diagnostics are absent from `F2`, do not install the staged file yet.
That would require a later user-authorized installation to the EFI/HP_TOOLS
partition or USB. No login, captcha, payment, entitlement, or product ambiguity
blocked this investigation.

## Scope and unresolved point

The prior `108 C` ACPI thermal event was supplied as known evidence and was not
re-created. It makes the hardware diagnostic step safety-relevant, but it does
not prove the current lag is thermal and does not authorize a BIOS flash or a
thermal-protection change.

There is a current HP publication inconsistency: the exact-SKU 25H2 catalogue,
whose records were updated on 2026-08-22, still labels F.10 as latest, while
HP's live F.11 CVA says it supersedes F.10 and HP's 2026-07 security bulletin
lists F.11 as the minimum for this family. The board-ID match makes F.11
applicable, but the discrepancy is another reason to preserve the pre-change
diagnostic baseline and not present a flash as completed remediation.
