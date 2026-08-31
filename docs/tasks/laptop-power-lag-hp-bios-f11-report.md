# HP BIOS F.11 guarded staging report

## Outcome

Phase 1 is complete. The exact HP `SP172952` package for system board `8DA7`
is staged from HP, its SHA-256 exactly matches the live HP CVA, and its
Authenticode signature is valid and identifies HP Inc.

Phase 2 was not started. The executable was not run and no installer screen was
opened because the mandatory launch gates did not all pass:

- `BackupConfirmed=False` (no user confirmation recorded).
- `RecoveryKeyAvailabilityConfirmed=False` (no user confirmation recorded).
- BitLocker protection is On and HP's current notebook BIOS instructions require
  suspension before the update. It was not suspended.
- Battery charge was 78%, below the lane's 80% minimum, although AC was online.
- Windows reports pending-restart state: TPM `RestartPending=True` and
  `PendingFileRenameOperations=True`.

No BIOS flash/capsule was scheduled, no firmware was changed, no reboot was
requested, and no power, thermal, TPM, Secure Boot, or BitLocker setting was
changed.

## Fresh machine identity and health

Captured locally at `2026-08-30T21:48:47.4020938+05:00` using the BIOS registry,
`Get-CimInstance Win32_BIOS`, `Win32_OperatingSystem`, `Win32_ComputerSystem`,
`Win32_BaseBoard`, `Win32_Processor`, and `Win32_VideoController`. Serial number
and UUID were excluded.

| Field | Fresh value |
|---|---|
| Manufacturer/model | HP / HP OmniBook X Flip Laptop 14-fk0xxx |
| System SKU | `BG2S4PA#ABG` |
| Family | `103C_5335M8 HP OmniBook X` / 14-fk0xxx |
| Baseboard | HP `8DA7` |
| Installed BIOS | Insyde `F.10`, release date 2025-10-22 |
| OS | Windows 11 Pro `10.0.26200`, build 26200, 64-bit |
| Last boot | 2026-08-30 17:22:01 local |
| CPU/GPU | AMD Ryzen AI 7 350 / AMD Radeon 860M |

Device and service capture at `2026-08-30T21:49:33.1495080+05:00`:

- AMD PMF `ACPI\AMDI0107\0`: Started/OK, problem `CM_PROB_NONE`, signed
  `oem125.inf` 26.10.15.0 dated 2026-07-24.
- AMD UMDF Sensor `ACPI\AMDI0080\1`: Started/OK, problem `CM_PROB_NONE`, signed
  `oem97.inf` 1.1.0.37 dated 2026-01-09.
- Radeon 860M, Microsoft AC adapter, battery, and ACPI thermal zone TZS0:
  Present/OK, problem `CM_PROB_NONE`.
- `sc.exe query amdpmf`: `STATE : 4 RUNNING`, `WIN32_EXIT_CODE : 0`.
- `pnputil /enum-devices /problem`: `No devices were found on the system.`

The pre-flash event query at `2026-08-30T21:55:37.5618343+05:00` covered the
current boot. It found 72 scoped events: one Critical, one Error, two Warnings.
The Critical/Error are the boot records for the unexpected shutdown at
2026-08-30 16:50:42 (Kernel-Power 41 and EventLog 6008). One warning is the
known boot-time WUDFRd `0xC0000365` event for `ACPI\AMDI0080\1`; the sensor is
currently Started/OK. Kernel-Power 125 enumerated TZS0 with `_PSV=378K`,
`_HOT=381K`, and `_CRT=398K`. No new WHEA, display, firmware, or thermal-trip
error was found after this boot.

## Power-policy baseline

Captured at `2026-08-30T21:54:39.3678554+05:00` with `powercfg` and the active
overlay registry values. The base active scheme remains High performance
`8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c`. AC uses Max Performance overlay
`ded574b5-45a0-4f42-8737-46345c09c238`; DC uses Better Battery-life overlay
`961cc777-2547-4f9d-8174-7d86181b8a7a`.

| Setting | Base AC/DC | AC overlay | DC overlay |
|---|---|---|---|
| Processor minimum | 100% / 5% | 80% | 5% |
| Processor maximum | 100% / 100% | not defined in overlay | 100% |
| Boost mode | Disabled / Disabled | not defined | not defined |
| EPP class 0 | 0% / 0% | 10% | 100% |
| EPP class 1 | 0% / 0% | 10% | 90% |
| Maximum frequency class 0 | 0 / 0 MHz | 0 MHz (uncapped) | 2500 MHz |
| Maximum frequency class 1 | 0 / 0 MHz | 0 MHz (uncapped) | 3300 MHz |
| AMD PMF Controller | 2 / 2 | 3 | 1 |
| AMD Overlay | 3 / 3 | 3 (Best performance) | 1 (Better battery) |

The full non-secret preflight state is preserved in
`diagnostics/laptop-power-lag/bios-f11-preflash-baseline.md` and elevated
security output in
`diagnostics/laptop-power-lag/bios-f11-preflight-security.txt`.

## Secure Boot, TPM, BitLocker, power, and restart gates

An elevated, read-only inventory completed at
`2026-08-30T21:51:05.4223500+05:00`. It did not enumerate protector IDs or
recovery passwords.

| Gate | Evidence | Result |
|---|---|---|
| Secure Boot | Enabled=True | pass |
| TPM | Present/Ready/Enabled/Activated/Owned=True | pass, but `RestartPending=True` |
| BitLocker C: | FullyEncrypted; Protection On; XTS-AES 128; Unlocked | protected; suspension not authorized |
| Protector types | Numerical Password and TPM only | recorded without IDs or secrets |
| AC | `PowerOnline=True` | pass at capture |
| Battery | 78%, charging, not critical | fail: below 80% |
| Windows restart | CBS=False; Windows Update=False; PendingFileRenameOperations=True | fail |
| Backup | `BackupConfirmed=False` | fail / user confirmation absent |
| Recovery key availability | `RecoveryKeyAvailabilityConfirmed=False` | fail / user confirmation absent |

## Official HP package evidence

All sources below are HP-owned. The CVA and release notes were fetched without
a host redirect at `2026-08-30T21:51:38.2132592+05:00`; both returned HTTP 200.
The exact-SKU catalogue was rechecked at
`2026-08-30T21:51:56.0914694+05:00`.

- CVA: https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172952.cva
- Release notes: https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172952.html
- Executable: https://ftp.hp.com/pub/softpaq/sp172501-173000/sp172952.exe
- Security bulletin HPSBHF04134:
  https://support.hp.com/at-de/document/ish_15277121-15278425-16/hpsbhf04134
- HP notebook BIOS update procedure:
  https://support.hp.com/in-en/document/ish_3894564-1633733-16
- HP notebook BIOS recovery procedure:
  https://support.hp.com/us-en/document/ish_3932413-2337994-16?pStoreID=%40%406qFsI
- Exact-SKU catalogue API:
  https://support.hp.com/wcc-services/swd-v2/driverDetails

Fresh CVA/release-note findings:

- HP Notebook System BIOS Update (AMD Processors), part `P018YS-B2D`.
- SoftPaq `SP172952`, Insyde `F.11`, revision A.
- `SYSID\8DA7="KRK"`, `SysId01=0x8DA7`.
- `HP OMNIBOOK X FLIP 14 INCH 2-IN-1 LAPTOP NEXT GEN AI`, Windows 11 OEM.
- Supersedes `SP165946` (F.10).
- Expected SHA-256:
  `8AC54601CFE5D64735AF3F826DDB2F2411FE0596EBC3498550FBEC53988AB68C`.
- `SystemMustBeRebooted=0`, while return codes 3010 and 1024 explicitly mean a
  restart is required to complete installation.
- Release note: improved system stability.
- Rollback prohibition: because of the included security updates, previous BIOS
  versions cannot be reinstalled after this update.
- HPSBHF04134 lists the exact 14-fk0xxx family with F.11/SP172952 as the
  applicable minimum BIOS.

The publication conflict remains: the live exact-SKU Windows 11 25H2 catalogue
request for product-number OID `2103018136`, series OID `2102790278`, product
line M8 still returns F.10 Rev.A / SP165946 as the newest BIOS (updated
2026-08-22), while the live F.11 CVA and HP security bulletin explicitly list
board 8DA7 / family 14-fk0xxx. No substitute was selected.

## Staged evidence and verification

Downloaded untouched at `2026-08-30T21:54:07.9456525+05:00`:

```text
File: docs/tasks/laptop-power-lag-hp-bios-f11-staging/sp172952.exe
Size: 16099808 bytes
SHA256: 8AC54601CFE5D64735AF3F826DDB2F2411FE0596EBC3498550FBEC53988AB68C
Authenticode status: Valid (Signature verified.)
Signer: CN=HP Inc., O=HP Inc., L=Palo Alto, S=California, C=US
Issuer: CN=DigiCert Trusted G4 Code Signing RSA4096 SHA384 2021 CA1, O="DigiCert, Inc.", C=US
Signer serial: 04979E12E8FA5906177A998FC648A741
Signer thumbprint: DD48CA569CE21D808A05767D7F502A38B63E1529
Signer validity: 2026-01-26T05:00:00+05:00 through 2027-01-26T04:59:59+05:00
Timestamp signer: CN=DigiCert SHA256 RSA4096 Timestamp Responder 2025 1, O="DigiCert, Inc.", C=US
Timestamp thumbprint: DD6230AC860A2D306BDA38B16879523007FB417E
```

Preserved metadata files:

| File | Size | SHA-256 |
|---|---:|---|
| `sp172952.cva` | 2,854 bytes | `7DE3CF75B9318F048A00D4EB749C867CABAF318CB59C4290D18B65F932F7E58A` |
| `sp172952.html` | 1,446 bytes | `66A05A2124BA8923893F41D196603A6805EB44BABDB789909D9197ECA2EF9E16` |

Verification commands were `Get-Item`, `Get-FileHash -Algorithm SHA256`, and
`Get-AuthenticodeSignature`. The executable hash equals the fresh CVA value
byte-for-byte and the signature status is Valid.

## HP safety requirements and irreversible boundary

HP's current notebook BIOS instructions require the AC power cord to remain
connected, applications to be closed, and BitLocker protection to be suspended
before the update. HP warns that failure to disable BitLocker can lead to a
recovery-key problem after reboot. This lane did not suspend BitLocker because
that security-impacting change requires a user handoff. The narrow safe scope,
if later authorized, is suspension for the single firmware reboot/update cycle,
followed immediately after Windows returns by verifying
`ProtectionStatus=On`; no protector details or recovery material should be
printed.

HP's documented visible flow is UAC **Yes**, InstallShield **Next**, license
acceptance, HP BIOS Update and Recovery **Next**, choose **Update**, then
**Next**, followed by **Restart Now** and a firmware screen such as **Apply
Update Now**. The exact local prompts were not observed because the installer
was not launched. In particular, neither **Update > Next**, **Restart Now**, nor
**Apply Update Now** was clicked; the former may already prepare/schedule the
capsule and is therefore beyond this agent's authorized boundary.

HP documents notebook recovery via Windows+B (or Windows+V) and, on supported
models, a USB recovery drive. HP also says this process is not supported on HP
Sure Start models and may not succeed depending on model/cause. The exact
14-fk0xxx product page links the generic recovery procedure but does not
guarantee downgrade or recovery behavior for this unit. No recovery USB was
created or selected. The F.11 CVA explicitly prohibits reinstalling previous
BIOS versions, so recovery is not evidence that F.10 can be restored.

## User-only handoff and work not performed

Before an installer launch can be reconsidered, the user must provide only
non-secret confirmations that important data is backed up and recoverable, and
that a BitLocker recovery key is available under their control. They must not
paste or expose that key. They must also save work, close applications,
disconnect nonessential peripherals, keep stable AC connected and the lid open,
and allow the battery to reach at least 80% (or any higher threshold the HP
installer states). Windows pending-restart state must first be cleared and
rechecked. A separate explicit decision is required before narrowly suspending
BitLocker.

Not performed because Phase 2 gates failed: installer launch, local prompt
inspection, BitLocker suspension, capsule preparation, final firmware
confirmation, reboot, flash, post-flash verification, and 35-minute battery
validation. The staged F.11 update is an applicable security/stability update,
not a proven fix for the battery-only lag.
