# HP UEFI Diagnostics installation and offline test lane

## Objective

Install the already staged, HP-signed HP PC Hardware Diagnostics UEFI package
only after re-verifying its exact identity and establishing a supported target
and rollback. Then arrange HP's offline Fast, Extensive, Power Source, Battery,
System Board, and Fan tests for the HP OmniBook X Flip Laptop 14-fk0xxx. This is
a diagnostic step, not a BIOS update and not a claim that hardware is faulty.

## Why this lane exists

The severe battery-only lag persists after AMD PMF 26.10.15.0 was installed and
after multiple reboots. A synchronized capture objectively reproduced the
fault after about 14m43s continuously on battery:

- actual CPU frequency fell from a 1958.06 MHz average to 616.86 MHz;
- processor performance fell from 97.91% to 30.81%, matching the exposed 31%
  minimum CPPC throttle;
- CPU time rose to 99.26% and processor queue averaged 98.67, max 117;
- disk queue stayed near zero, available memory increased, GPU load fell, and
  absolute interrupt rate did not spike;
- reconnecting AC restored about 2.0 GHz/99% performance and normal visible
  responsiveness immediately;
- PMF, sensor, display, battery, AC adapter, and ACPI thermal devices remained
  OK/problem code 0 with no correlated driver or device failure.

The machine also recorded Kernel-Power 88 critical thermal hibernation at
`_HOT = 381K` (108 C) for `\_TZ.TZS0` on 2026-08-23. That makes offline battery,
fan, board, and thermal-path diagnostics the safest next evidence step. It does
not authorize raising thermal limits, bypassing protections, or flashing BIOS.

## Exact machine and package identity

Machine evidence, excluding serial number and UUID:

```text
Model: HP OmniBook X Flip Laptop 14-fk0xxx
Product number: BG2S4PA (regional suffix #ABG)
HP model record: 2103018136
Family: 14-fk0000
Platform: Enstrom_25C1
System board ID: 8DA7
Installed BIOS: Insyde F.10, 2025-10-22
OS: Windows 11 Pro 25H2, build 26200.9168, 64-bit
```

The staged package was downloaded directly from HP and has not been executed
or unpacked:

```text
Path: C:\Users\Ali\Desktop\jarvis\docs\tasks\laptop-power-lag-hp-downloads\sp172931.exe
Product: HP PC Hardware Diagnostics UEFI 10.8.6.0 Rev.A
HP SoftPaq: SP172931
HP source: https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172931.exe
HP CVA: https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172931.cva
Size: 50,437,144 bytes
SHA-256: 2981B6C92F5AF2B3E7FC6282288D4BE6C6AC6CAC727F208E7BF8635096F23858
HP CVA SHA-256: 2981B6C92F5AF2B3E7FC6282288D4BE6C6AC6CAC727F208E7BF8635096F23858
Authenticode: Valid, Signature verified
Signer: HP Inc.
Signer issuer: DigiCert Trusted G4 Code Signing RSA4096 SHA384 2021 CA1
Signer thumbprint: DD48CA569CE21D808A05767D7F502A38B63E1529
Signer validity: 2026-01-26 through 2027-01-26
```

HP's CVA explicitly includes `SysId120=0x8DA7`, Windows 11 25H2, and states a
minimum 256 MB target on a FAT/FAT32 `HP_TOOLS` partition or UEFI System
Partition. The package can install to disk or USB. A target choice is not to be
guessed when its rollback and data impact differ.

## Claim and strict ownership

Before any command, run `python tools/work_board_claim.py list`. Claim:

- role `diagnostic-install`;
- work item `hp-uefi-diagnostics-install-test`;
- report path `docs/tasks/laptop-power-lag-hp-uefi-test-report.md`;
- any new repository-local installer logs or screenshots explicitly named in
  the claim;
- resources `laptop-machine`, `keyboard-focus`, and `reboot-handoff`.

Do not proceed on a path or resource conflict. The staged executable is
read-only input and must not be renamed, replaced, deleted, or modified. The
lane owns no BIOS, firmware settings, driver, device, power plan, registry,
service, thermal policy, personal USB contents, or unrelated application.

No other machine benchmark, live battery capture, firmware operation, or
physical-I/O lane may run concurrently. Do not commit.

## Non-negotiable safety constraints

- This lane installs HP PC Hardware Diagnostics UEFI `SP172931` only. It must
  not run or stage BIOS `SP172952`, flash BIOS F.11, update firmware, install a
  different SoftPaq, or substitute another diagnostic package.
- Do not change power schemes, AMD/HP profiles, registry values, services,
  drivers, devices, CPPC/EPP values, fan behavior, or thermal thresholds.
- Never disable thermal protection or continue a test after a thermal warning,
  shutdown, burning smell, battery swelling, abnormal fan failure, or unsafe
  surface temperature.
- Do not use silent or undocumented installer switches. Do not accept a license,
  final Install/Next/Finish action, UAC prompt, reboot prompt, or target choice
  on the user's behalf.
- Do not mount, format, repartition, or directly edit the EFI System Partition.
  Do not erase or overwrite a USB device. A USB target requires the user to
  identify a disposable/approved device and confirm its data may be changed.
- Do not reboot, shut down, or enter UEFI until the orchestrator has batched the
  user handoff and the user has saved work.
- Do not collect or report serial number, UUID, credentials, unrelated files,
  or personal USB content.

## Required pre-install verification

Run and preserve exact relevant output:

```powershell
$package='C:\Users\Ali\Desktop\jarvis\docs\tasks\laptop-power-lag-hp-downloads\sp172931.exe'
Get-Item -LiteralPath $package | Select-Object FullName,Length,LastWriteTime
Get-FileHash -LiteralPath $package -Algorithm SHA256
Get-AuthenticodeSignature -LiteralPath $package | Select-Object Status,StatusMessage,@{n='SignerSubject';e={$_.SignerCertificate.Subject}},@{n='SignerThumbprint';e={$_.SignerCertificate.Thumbprint}}
Get-ItemProperty -LiteralPath 'HKLM:\HARDWARE\DESCRIPTION\System\BIOS' | Select-Object SystemManufacturer,SystemProductName,SystemSKU,SystemFamily,BaseBoardProduct,BIOSVersion,BIOSReleaseDate
```

Stop without execution unless size, SHA-256, signature status, signer,
thumbprint, product family, and board ID exactly match the evidence above.
Re-read the staged HP CVA or official URL and confirm version 10.8.6.0,
`SysId120=0x8DA7`, and the target requirements. Do not rely on filename alone.

Before permitting an install target, determine from HP documentation or the
visible installer whether that target has a supported removal/rollback path:

- For a local disk/UEFI target, record the HP-provided uninstall/remove method
  and the exact pre-install state/version without mounting or editing EFI
  directly.
- For USB, the user must identify the exact removable device and authorize its
  data impact. Record capacity, filesystem, and pre-existing-data decision
  without printing filenames. Do not select or format it yet.

If no exact non-destructive rollback/removal can be established for the chosen
target, make no installation. Report the blocker. Do not choose the other target
as a workaround; disk-versus-USB data impact is a Class C user decision.

## Installation handoff

After every precondition passes, launch only the verified package in a visible
Administrator process:

```powershell
Start-Process -FilePath $package -Verb RunAs -PassThru
```

The agent may navigate and read the installer. The user handles UAC, target
selection, license acceptance, and the final install confirmation. Before that
single confirmation, report the exact target, files/partition the HP installer
says it will change, free-space requirement, restart behavior, and rollback.

Do not allow an automatic restart. If installation offers one, select the
documented defer/later option only when this is not itself a final confirmation;
otherwise stop and hand it to the user. Preserve the complete non-secret
installer result and any HP log path.

## Post-install verification before reboot

Verification must use supported Windows/HP evidence, not direct EFI edits:

1. Confirm the installer returned success and identify installed Diagnostics
   UEFI version 10.8.6.0 and target using its result, supported inventory, or
   HP-created log.
2. Recompute the staged executable hash and signature to prove the input was
   unchanged.
3. Confirm BIOS remains F.10, AMD PMF remains `oem125.inf` 26.10.15.0 and
   Started/problem 0, `amdpmf` remains RUNNING, active power settings remain
   unchanged, and `pnputil /enum-devices /problem` remains clear.
4. Record whether the installer says a restart is required. Do not infer it.
5. Confirm the documented rollback/removal path is still available. Do not
   exercise rollback unless installation verification fails.

If installation causes a Windows device/service problem, unexpected firmware
change, package mismatch, or incomplete target write, stop. Use only the exact
pre-established HP-supported rollback. If rollback requires confirmation or
reboot, hand it to the user; never guess or force it.

## Single batched reboot and offline-test handoff

Only after installation verifies, ask the user once to save work and perform
the complete offline sequence. The user performs all sensory/interactive UEFI
steps:

1. Shut down only when the orchestrator explicitly hands off. Power on and
   press `Esc` repeatedly, about once per second; choose `F2` from Startup Menu.
2. Confirm HP PC Hardware Diagnostics UEFI reports version 10.8.6.0. If it does
   not appear or reports another version, stop and photograph the screen.
3. Run **System Tests > Fast Test > Run once**. If pass one is clear, continue
   with the second pass.
4. If Fast Test passes, run **System Tests > Extensive Test > Run once**. HP
   states this can take two hours or more. Keep AC connected unless the test's
   own instructions require otherwise.
5. Run available **Component Tests** for **Power Source**, **Battery**,
   **System Board**, and **Fan**. For Battery, disconnect AC only if the HP UEFI
   screen instructs it. Reconnect immediately after the test.
6. Photograph or write down every result. For a failure, preserve the exact
   test name, status, 24-digit Failure ID, and displayed recommendation.

Abort and power off safely if diagnostics report fan/cooling failure, critical
temperature, battery swelling/failure, or another safety warning. Do not run a
15-minute Windows battery reproduction in this lane; offline hardware tests
come first.

## Completion and rollback criteria

The lane is complete only when:

- pre-install identity/hash/signature/model checks all match;
- the chosen target and exact supported rollback were user-confirmed;
- installation reports HP UEFI Diagnostics 10.8.6.0 success;
- Windows post-install invariants remain healthy and unchanged;
- the user reports the UEFI version and every requested test result;
- any Failure ID is preserved exactly;
- no BIOS flash, thermal bypass, driver/power change, or automatic reboot
  occurred.

Rollback is required if package verification differs, installation is partial,
the wrong target/version is installed, or Windows/boot behavior regresses.
Use only the pre-established HP-supported removal path. After rollback, verify
the pre-install diagnostic state, BIOS F.10, PMF 26.10.15.0, device/service
health, and boot behavior. Never delete EFI files manually.

Write `docs/tasks/laptop-power-lag-hp-uefi-test-report.md` with exact commands
and outputs, target/rollback evidence, installer result, reboot disposition,
offline test results, Failure IDs, safety observations, and everything specified
but not completed. Release all claims only after report verification. Preserve
all artifacts until the outcome is reported.
