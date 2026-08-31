# HP BIOS F.11 staging, guarded flash, and battery validation lane

## Objective

Prepare and, only after a separate irreversible user confirmation, apply HP
Notebook System BIOS F.11 (`SP172952`) to the exact HP OmniBook X Flip Laptop
14-fk0xxx. Preserve a pre-flash baseline, verify the official package at every
boundary, and validate the persistent battery-only throttle for 35 minutes
after the flash. This brief authorizes no action by itself; its implementation
must stop at the final firmware confirmation and report the exact prompt.

## Exact machine identity and current state

The target is unambiguous and must match again immediately before staging and
before installer launch:

```text
Manufacturer: HP
Model: HP OmniBook X Flip Laptop 14-fk0xxx
System SKU: BG2S4PA#ABG
HP model record: 2103018136
Family: 14-fk0000 / Enstrom_25C1
System board ID: 8DA7
Current BIOS: Insyde F.10
Current BIOS release date: 2025-10-22
OS: Windows 11 Pro 25H2, build 26200.9168, 64-bit
CPU/GPU: AMD Ryzen AI 7 350 / Radeon 860M
```

AMD PMF `ACPI\AMDI0107\0` is Started on signed `oem125.inf` 26.10.15.0.
AMD UMDF Sensor `ACPI\AMDI0080\1` is Started on signed `oem97.inf` 1.1.0.37.
Updating PMF and rebooting did not resolve the fault.

## Fault and diagnostic evidence

The lag has been reproduced after multiple reboots and originally appeared on
roughly three of five unplug transitions. A synchronized battery capture showed
the objective failure after about 14m43s continuously on DC:

- actual CPU frequency dropped from 1958.06 MHz average to 616.86 MHz;
- processor performance dropped from 97.91% to 30.81%, the exposed 31% CPPC
  floor;
- CPU time reached 99.26% and processor queue averaged 98.67, maximum 117;
- disk queue remained near zero, available memory increased, GPU load fell,
  and absolute interrupt rate did not spike;
- reconnecting AC immediately restored about 2.0 GHz/99% performance and normal
  visible responsiveness;
- PMF, sensor, display, battery, AC adapter, and thermal devices remained
  status OK/problem 0 with no correlated device, WHEA, display, or service
  failure.

Kernel-Power 88 previously recorded critical thermal hibernation at
`_HOT = 381K` (108 C) for `\_TZ.TZS0`. Do not reproduce that condition
deliberately. Basic power-plan caps are not the cause: maximum processor state
is 100% on battery, and the recorded PMF/overlay settings did not impose a
simple 31% maximum.

The HP UEFI Diagnostics lane did not run offline tests. `SP172931` was verified,
but the internal 100 MiB EFI System Partition was below HP's 256 MB requirement,
no reversible local install path existed, and no user-approved USB target was
present. Therefore Fast, Extensive, Power Source, Battery, System Board, and Fan
tests are unavailable evidence—not passes.

## Official BIOS candidate evidence

Only the following exact package may be considered:

```text
Product: HP Notebook System BIOS Update (AMD Processors)
SoftPaq: SP172952
Version: F.11
Revision: A
Vendor: Insyde
System ID: 0x8DA7 / SYSID\8DA7
System name: HP OMNIBOOK X FLIP 14 INCH 2-IN-1 LAPTOP NEXT GEN AI
OS metadata: Windows 11 OEM
Supersedes: SP165946 (F.10)
Expected SHA-256: 8AC54601CFE5D64735AF3F826DDB2F2411FE0596EBC3498550FBEC53988AB68C
Official executable: https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172952.exe
Official CVA: https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172952.cva
Official release notes: https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172952.html
```

The live official CVA was read on 2026-08-30 and returned the values above plus
`Provides improved system stability.` HP security bulletin HPSBHF04134 lists
F.11/SP172952 as the minimum for the 14-fk0xxx family and addresses
CVE-2025-12050 through CVE-2025-12053. Neither the CVA, release notes, nor
bulletin says F.11 fixes battery-only lag, PMF, sensor input, or thermal
throttling. This is an applicable security/stability update and a controlled
firmware hypothesis, not a proven repair.

HP's exact-SKU Windows 11 25H2 catalogue previously still listed F.10 while the
newer live CVA and security bulletin listed F.11. That inconsistency must be
rechecked before staging. Never substitute a nearby model, a Windows Update
capsule, HP Support Assistant recommendation, AMD package, third-party BIOS,
or another SoftPaq.

The current CVA also states that due to security updates, previous BIOS versions
cannot be reinstalled after this update. Treat the flash as irreversible. A
BIOS recovery image is disaster recovery, not authorization or a promise that
F.10 can be restored.

## Claim and strict ownership

Before any command or file write, run `python tools/work_board_claim.py list`.
Claim:

- role `firmware-prep`;
- work item `hp-bios-f11-stage-and-validate`;
- `docs/tasks/laptop-power-lag-hp-bios-f11-report.md`;
- an explicit repository-local staging prefix for `SP172952` and metadata;
- `diagnostics/laptop-power-lag/bios-f11-*` for non-secret baselines and
  post-flash validation;
- resources `laptop-machine`, `keyboard-focus`, `firmware-update`, and
  `reboot-handoff`.

Do not proceed on any path or resource conflict. No machine benchmark,
battery-transition capture, Windows Update, HP installer, firmware utility,
physical-I/O lane, or long-running build may overlap the flash window.

The lane owns only its report, claimed staging/capture paths, and the exact
verified F.11 operation after user confirmation. It owns no unrelated file,
driver, service, power setting, registry key, HP/AMD application, firmware
setting, partition, USB device, or user data. Do not commit.

## Non-negotiable safety and stop rules

- Do not download, stage, extract, launch, or install anything until current
  HP metadata and exact machine identity pass the checks below.
- Stage only `SP172952`. Do not stage or run BIOS F.10, another revision,
  diagnostics `SP172931`, graphics/chipset packages, or substitutes.
- Do not use silent switches, command-line auto-flash modes, HP Image Assistant
  remediation, Windows Update firmware, or BIOS recovery to bypass prompts.
- Do not change thermal limits, fan controls, CPPC/EPP, AMD PMF, power plans,
  Secure Boot, TPM, virtualization, BIOS passwords, or other firmware settings.
- Do not suspend BitLocker speculatively or expose recovery keys/protector IDs.
  Never print, log, copy, or ask the user to paste a recovery key.
- Do not flash without stable AC power and adequate battery. Require AC online
  and at least 80% charge, or a higher threshold if HP's current installer says
  so. If battery condition, AC stability, fan, or temperature is abnormal, stop.
- The user must save work, close active applications, keep the lid open, prevent
  sleep by attendance rather than changing the power plan, and avoid touching
  power or peripherals during the flash. Disconnect nonessential peripherals.
- Never interrupt, power off, close the lid, unplug AC, force-restart, or send
  input after the user confirms the firmware flash until HP/Windows completes.
- Stop before the final irreversible Update/Flash/Restart/Confirm action and
  report the exact prompt, version transition, power state, BitLocker state,
  backup state, and recovery position to the orchestrator/user.

## Phase 1: fresh evidence and staging only

### 1. Re-verify identity and baseline

Capture exact relevant output while excluding serial number and UUID:

```powershell
Get-ItemProperty -LiteralPath 'HKLM:\HARDWARE\DESCRIPTION\System\BIOS' |
  Select-Object SystemManufacturer,SystemProductName,SystemSKU,SystemFamily,
    BaseBoardManufacturer,BaseBoardProduct,BIOSVendor,BIOSVersion,BIOSReleaseDate
Get-CimInstance Win32_BIOS |
  Select-Object Manufacturer,SMBIOSBIOSVersion,ReleaseDate
Get-CimInstance Win32_OperatingSystem |
  Select-Object Caption,Version,BuildNumber,OSArchitecture,LastBootUpTime
```

Stop unless SKU is exactly `BG2S4PA#ABG`, board exactly `8DA7`, model family
exactly 14-fk0xxx/14-fk0000, and installed BIOS exactly F.10. If BIOS is already
F.11 or another version, do not stage or launch the package; report the new
state.

Capture PMF/sensor/display/battery/AC-adapter status and problem codes,
`pnputil /enum-devices /problem`, PMF service state, active power scheme and the
previously recorded AC/DC processor/PMF/overlay values, Secure Boot state, TPM
readiness, recent critical power/thermal/firmware events, and current power
source/battery charge. Preserve a timestamped pre-flash baseline.

### 2. Backup, recovery, and BitLocker gate

This is a Class C handoff. The user must confirm—without revealing contents or
credentials—that current important files are backed up and recoverable. Record
only `BackupConfirmed=True/False`, date/time, and backup class (for example,
local external or cloud), never paths or filenames.

Read BitLocker state without exposing secrets:

```powershell
Get-BitLockerVolume -MountPoint 'C:' |
  Select-Object MountPoint,VolumeStatus,ProtectionStatus,EncryptionMethod,LockStatus
manage-bde.exe -status C:
```

Do not enumerate or print recovery passwords or protector IDs. The user must
confirm separately that a recovery key is available in a location they control;
record only `RecoveryKeyAvailabilityConfirmed=True/False`.

Re-read HP's current BIOS instructions and visible installer requirements. If
HP explicitly requires BitLocker suspension, stop and report the exact prompt,
the narrowest documented suspension duration, and the exact verification that
protection will resume. Suspension is a security-impacting change and requires
the orchestrator/user handoff. If HP does not require it, leave protection on.
After any later reboot, `ProtectionStatus` must be checked again.

Verify HP's current BIOS-recovery procedure for this exact family and whether
the installer offers a recovery-image step. Do not create, format, overwrite,
or select a USB device without the user identifying an approved target and
confirming its data impact. Do not claim that recovery can downgrade to F.10;
the CVA explicitly says previous BIOS versions cannot be reinstalled.

### 3. Re-verify official metadata and stage

Fetch the CVA and release notes fresh from the exact HTTPS URLs above. Record
access time, HTTP status, F.11/Rev.A, `0x8DA7`, Windows 11 applicability,
superseded F.10 SoftPaq, expected SHA-256, reboot/return-code metadata, release
note, and rollback prohibition. Recheck HPSBHF04134 on HP's official site.

If the exact-SKU catalogue still conflicts with the CVA/bulletin, record the
conflict. If board applicability, version, hash, source, or bulletin no longer
matches, stop. Do not choose a replacement.

Only after metadata passes, download the untouched executable from the exact
official HTTPS URL to the claimed staging prefix. Do not execute or unpack it.
Verify:

```powershell
Get-Item -LiteralPath $package | Select-Object FullName,Length,LastWriteTime
Get-FileHash -LiteralPath $package -Algorithm SHA256
Get-AuthenticodeSignature -LiteralPath $package |
  Select-Object Status,StatusMessage,@{n='SignerSubject';e={$_.SignerCertificate.Subject}},
    @{n='SignerIssuer';e={$_.SignerCertificate.Issuer}},
    @{n='SignerThumbprint';e={$_.SignerCertificate.Thumbprint}},
    TimeStamperCertificate
```

The file hash must exactly equal
`8AC54601CFE5D64735AF3F826DDB2F2411FE0596EBC3498550FBEC53988AB68C`.
Authenticode must be `Valid` and identify HP Inc. through a trusted chain. Record
the actual signer thumbprint and validity; do not pre-assume one. Stop on any
mismatch, invalid/unknown/revoked signature, redirect to another host, partial
download, or filename collision.

Phase 1 ends with a verified staged executable and evidence only. It does not
authorize launch.

## Phase 2: visible installer, stopping before firmware confirmation

Immediately before launch, repeat machine identity/current BIOS, power/charge,
BitLocker protection, staged hash, and Authenticode checks. Require AC online,
battery at least 80%, user-confirmed backup/recovery-key availability, no
pending restart, and no critical current device/thermal condition.

Launch only the verified staged package in a visible Administrator process:

```powershell
Start-Process -FilePath $package -Verb RunAs -PassThru
```

The user handles UAC and license acceptance. The agent may navigate/read the
installer only far enough to verify:

- current BIOS F.10 and target F.11;
- exact system-board applicability;
- AC/battery readiness;
- whether BitLocker suspension is required;
- whether a recovery image is offered;
- how many automatic restarts are expected;
- the exact irreversible final prompt.

Do not use automated clicking for the final action. Stop before any button or
prompt that begins flashing, schedules flashing at reboot, writes a firmware
capsule, suspends encryption, or restarts. Report the full non-secret prompt and
button labels to the orchestrator. The user alone makes the final irreversible
confirmation. Do not proceed merely because F.11 is applicable.

## Phase 3: post-flash verification (not to run during preparation)

After the user confirms the flash and Windows returns, do not assume success.
Run read-only verification:

1. `Get-CimInstance Win32_BIOS` and the BIOS registry inventory must report
   Insyde F.11 on SKU `BG2S4PA#ABG`, board `8DA7`.
2. Windows must boot normally with Secure Boot and TPM state unchanged.
3. BitLocker `ProtectionStatus` must be On. If it remains suspended, stop and
   report; do not improvise protector changes.
4. AMD PMF must remain Started on `oem125.inf` 26.10.15.0 with problem code 0;
   AMD UMDF Sensor, display, battery, AC adapter, and ACPI thermal devices must
   remain OK/problem 0; `amdpmf` must be RUNNING.
5. `pnputil /enum-devices /problem` must report no problems.
6. Active power scheme and recorded AC/DC processor/PMF/overlay values must be
   unchanged. Do not normalize or tune them in this lane.
7. Query new BIOS/firmware, Kernel-Power, WHEA, thermal, Kernel-PnP, display,
   WUDFRd, and AMD/HP service events from the pre-flash bookmark onward.
8. Record installer result, restart count, BIOS version/date, boot time, and
   any warning. Preserve logs; do not delete the staged package or evidence.

If the flash fails, the machine does not boot normally, BitLocker requests its
recovery key, or HP recovery appears, stop for the user. Never enter, display,
or capture the recovery key. Use only HP's exact recovery instructions for this
model; do not attempt F.10 downgrade because HP marks it prohibited.

## Phase 4: 35-minute battery validation (not to run during preparation)

Run this only after post-flash health checks pass and the machine is cool and
stable. Claim `laptop-machine`, `keyboard-focus`, and the new
`diagnostics/laptop-power-lag/bios-f11-*` prefix. Reuse the verified read-only
counter methodology from the prior live capture; do not change power settings.

Batch the user handoff once:

1. Keep AC connected for a five-minute synchronized baseline.
2. Unplug AC and leave the lid open for 35 continuous minutes while the
   collector flushes one-second-class samples incrementally.
3. The user labels visible responsiveness as `normal`, `lag`, or `uncertain`
   and reports the approximate second any lag begins. Do not ask them to run
   commands.
4. Reconnect AC immediately at 35 minutes, or sooner if severe lag appears.
   Capture five minutes of recovery.

Stop early and reconnect AC on any thermal warning, critical event, fan/cooling
concern, sleep, crash, unsafe temperature, or severe sustained unresponsiveness.
Do not deliberately recreate the 108 C hot trip.

Capture and compare actual CPU MHz, processor performance/utility/time, queue,
DPC/interrupt percentages and absolute rates, disk queue/latency, memory, GPU,
power-source edges, scoped device states, PMF service, and relevant events.
Success for the symptom requires all 35 minutes on battery without the prior
31%/approximately 617 MHz collapse and without visible lag, followed by normal
AC recovery. A pass does not prove the security update caused the improvement;
it only establishes non-reproduction in this controlled window. A recurrence
must preserve exact onset and comparison evidence.

## Reporting and completion

Write `docs/tasks/laptop-power-lag-hp-bios-f11-report.md` with:

- exact current HP metadata URLs, access times, and relevant outputs;
- identity, BIOS, device, power, Secure Boot, TPM, backup, and BitLocker gates;
- staged filename, size, SHA-256, Authenticode signer/issuer/thumbprint and
  validation output;
- catalogue/CVA/bulletin consistency or conflict;
- the exact installer prompts and the irreversible confirmation not taken by
  the agent;
- if the user later confirms: flash result, restart count, post-flash health,
  BitLocker-resume verification, and all firmware/events evidence;
- if validation later runs: raw artifact paths, 35-minute window statistics,
  user sensory label, and pass/recurrence result;
- every specified step not completed and the precise blocker.

Preparation of this brief is complete when the file is verified. It does not
authorize download, launch, BitLocker suspension, firmware confirmation,
reboot, post-flash checks, or battery validation. Release claims only after
owned artifacts are verified; never delete evidence before reporting.
