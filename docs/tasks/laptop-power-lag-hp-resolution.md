# Persistent battery lag: HP-supported resolution lane

## Objective

Determine whether HP currently publishes a model-applicable BIOS, chipset/AMD
PMF, sensor, graphics, firmware, or HP thermal/power-management resolution for
the HP OmniBook X Flip Laptop 14-fk0xxx and this battery-only severe lag. Produce
an evidence-backed report and, only when unambiguous, stage official packages
for later user-authorized installation. Do not install or flash anything.

## Known evidence

- Windows 11 Pro build 26200; AMD Ryzen AI 7 350 with Radeon 860M.
- Installed BIOS is F.10 dated 2025-10-22.
- AMD PMF `ACPI\AMDI0107\0` is Started on signed AMD PMF 26.10.15.0
  (`oem125.inf`), yet the symptom persists after multiple reboots and appears
  on about three of five unplug events.
- Earlier WUDFRd failures affected AMD UMDF Sensor `ACPI\AMDI0080\1`.
- Kernel-Power 88 recorded `_HOT = 381K` (108 C) for `\_TZ.TZS0`.
- Maximum processor state is already 100% on battery; PMF Controller and AMD
  Overlay are not set to a basic low-power cap.

## Claim, ownership, and constraints

Before any command, run `python tools/work_board_claim.py list`, then claim
`docs/tasks/laptop-power-lag-hp-resolution-report.md` and any explicit download
staging prefix. This lane owns only that report plus read-only local/provider
inspection and its claimed download staging path. It owns no existing driver,
firmware, registry, power, service, device, or application configuration.

Use official HP support/advisory/download pages as primary sources. AMD and
Microsoft primary sources may clarify component identifiers, but they cannot
substitute for an HP model-applicability decision. Do not use third-party
driver sites. Treat versions, dates, advisories, and availability as current
claims and verify them online with direct links and access dates.

Do not install, execute, unpack by running, or silently accept any package. Do
not flash BIOS, invoke HP Image Assistant remediation, change HP Smart Sense or
thermal profiles, update Windows, or alter drivers/settings. Do not download a
package until its exact model/product applicability, version, signature/source,
and purpose are established. Do not collect or report serial numbers, support
entitlements, credentials, or unrelated inventory. Stop before login, captcha,
license acceptance, final download confirmation, or any installer UI. No
component substitution and no commit.

## Required investigation

1. Read the exact model-family and non-secret product/SKU identifiers from
   local Windows inventory. Redact serial number and UUID fields. Record BIOS
   version/date, Windows build, CPU/GPU, PMF and sensor hardware IDs, installed
   driver INF/version/provider/date, and relevant HP management application
   versions.
2. Resolve the exact HP product support page. If `14-fk0xxx` spans materially
   different SKUs and a non-secret product number is insufficient, report the
   missing model choice; never pick a nearby model.
3. Search HP's support catalogue and advisories for battery-mode performance,
   AMD PMF, Smart Sense, thermal framework, sensor/WUDF, BIOS, chipset, and
   graphics issues applicable to this exact family and Windows build.
4. Compare the installed versions to every applicable HP offering. Record
   SoftPaq number, title, version, release date, supersedence, supported
   hardware IDs/models, prerequisites, restart requirement, and official URL.
5. For any BIOS candidate, verify HP's exact version ordering and release notes.
   A newer BIOS is only a finding; never stage or flash it in this lane.
6. For driver/application candidates, verify that the package is newer or is a
   documented repair/reinstall for the installed component. If HP offers a
   different component than specified, stop and report rather than substitute.
7. If an unambiguously applicable non-BIOS package is worth preserving, stage
   the untouched signed download only in the claimed staging prefix. Record
   URL, SHA-256, Authenticode status/signer, size, and filename. Do not execute
   it. A web page that only exposes a final Save/Confirm action is a single
   batched user handoff after all research is complete.

## Decision criteria

Classify each candidate as one of:

- `applicable-update`: exact family/hardware match, newer relevant version or
  advisory-directed repair, official source, prerequisites known;
- `applicable-but-not-explanatory`: exact match but no release-note/advisory
  connection to the symptom;
- `already-current`;
- `not-applicable` with the conflicting model/hardware evidence;
- `ambiguous-user-decision`: only when HP requires a genuinely personal or
  irreversible choice.

Do not recommend installation solely because a version is newer. The 108 C
thermal event makes firmware/thermal advisories safety-relevant, but it does not
authorize a BIOS flash or thermal-protection change.

## Success criteria and report

Write `docs/tasks/laptop-power-lag-hp-resolution-report.md` with:

- exact read-only commands and relevant outputs;
- direct official citations for every current provider claim;
- installed-versus-offered comparison;
- applicability evidence per candidate;
- staged-file hashes/signatures, if any;
- the one best HP-supported next action, or a precise statement that HP
  publishes no verified applicable resolution;
- anything blocked by login, product ambiguity, download confirmation, payment,
  or user choice.

No installation recommendation may be presented as completed remediation.
Release the claim only after the report and staged artifact evidence verify.
