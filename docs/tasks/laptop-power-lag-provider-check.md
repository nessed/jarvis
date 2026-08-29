# Laptop battery-only lag: HP/AMD provider verification lane

## Objective and symptom

Research current authoritative HP, AMD, and Microsoft information relevant to
an HP OmniBook X Flip Laptop 14-fk0xxx becoming nearly unusable immediately
when AC power is disconnected and returning to normal immediately on reconnect.
Produce a source-linked report only; do not change the machine.

## Known local evidence

- Windows 11 Pro build 26200; BIOS F.10 dated 2025-10-22.
- AMD Ryzen AI 7 350 with Radeon 860M.
- AMD PMF device `ACPI\AMDI0107\0` is Started on installed `oem59.inf`, version
  26.10.11.0 dated 2026-05-08.
- A signed matching `oem125.inf`, version 26.10.15.0 dated 2026-07-24, is staged
  and marked Best Ranked but is not attached to the device.
- AMD UMDF Sensor `ACPI\AMDI0080\1` is Started on 1.1.0.37; WUDFRd failures for
  this device were recorded on 2026-08-21.
- Kernel-Power event 88 on 2026-08-23 recorded critical thermal hibernation in
  ACPI zone `\_TZ.TZS0` at `_HOT = 381K` (108 C), followed by sleep reason
  `Thermal Zone`.
- Battery health is approximately 95.7% with 214 cycles; Windows power policy
  does not impose an obvious DC CPU or AMD Overlay cap.

## Ownership and constraints

This lane owns this brief and current-source research/reporting only. It must
not edit other files, change drivers or settings, install or download software,
update BIOS/firmware, contact support, submit forms, create accounts, or perform
any outward-facing or destructive action. It must not commit. Do not substitute
another model's BIOS, firmware, driver, or remediation. Do not expose secrets,
serial numbers, account data, tokens, or unrelated user information.

## Research questions

Use current primary sources only: the exact HP model's official support pages,
HP advisories, AMD release notes/support documents, Microsoft documentation or
release-health pages, and Microsoft Update Catalog metadata when applicable.

1. What is the latest BIOS explicitly offered for HP OmniBook X Flip Laptop
   14-fk0xxx, and does it supersede F.10 or mention thermal, AC/DC, performance,
   embedded-controller, AMD PMF, sensor, or stability fixes?
2. What HP-approved AMD chipset/PMF/graphics versions are offered for the exact
   model and supported Windows build?
3. What do authoritative release notes say changed between AMD PMF 26.10.11.0
   and 26.10.15.0, if published?
4. Is Windows 11 build 26200 a stable public, preview, Insider, or unsupported
   configuration for this model as of the research date?
5. Are there official advisories for AMD PMF power-source transition throttling,
   WUDFRd failures on `ACPI\AMDI0080`, critical ACPI thermal events, or this HP
   model family?
6. Does HP specify an official hardware diagnostic for battery power delivery,
   cooling/fan function, or thermal sensors beyond capacity health?

Do not infer compatibility from a nearby HP model or a generic third-party
driver site. If an exact-model source cannot be found, state that limitation.

## Success criteria

- Every time-sensitive claim has a direct link to an authoritative current
  source and includes the source's publication/update date when available.
- The exact HP model and each relevant package/version are matched explicitly.
- The report distinguishes verified facts from inferences and identifies any
  mismatch between local BIOS/drivers and HP's supported versions.
- The report gives the orchestrator a clear evidence-backed recommendation:
  activate the staged PMF driver, use a different HP-provided exact component,
  update firmware, run an official diagnostic, or stop for provider support.
  Any component differing from the specified staged PMF driver is a proposed
  substitution and must be presented as a user decision, never performed.

## Rollback and stop criteria

This lane makes no machine change, so no rollback should be necessary. If a
site attempts an automatic download, login, account action, support submission,
or update, cancel/stop and report it. If sources conflict, preserve both links
and stop short of a recommendation that depends on choosing without evidence.

## Reporting

Lead with the current-source conclusion. Provide direct links beside each
claim, exact versions and dates, unsupported or missing evidence, and the next
safe action. State explicitly that no machine state was changed.
