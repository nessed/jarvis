# Laptop battery-only severe lag triage

## Symptom and objective

The user reports that the laptop becomes nearly unusable immediately after AC
power is disconnected: the pointer moves at roughly fractions of a frame per
second and the machine is broadly unresponsive. Normal performance returns as
soon as the charger is reconnected. Determine the most likely cause using
read-only evidence, without changing power, firmware, driver, or OEM settings.

This is host troubleshooting outside the JARVIS architecture. `docs/blueprint.md`
does not govern the diagnosis and no application component substitution or
architecture decision is involved.

## Ownership

This lane owns only this brief and its diagnostic report. It may write generated
diagnostic artifacts beneath the workspace. It must not edit application code,
`requirements.txt`, system configuration, registry values, power schemes,
drivers, firmware, services, scheduled tasks, or OEM utility settings. It does
not commit.

## Evidence to gather

- Windows edition/build, computer manufacturer/model, BIOS version/date.
- Current AC/battery status and the active and available power schemes.
- Full `powercfg /query`, emphasizing processor minimum/maximum state, cooling
  policy, boost/performance preferences, graphics, disk, PCIe, and battery
  thresholds.
- `powercfg /batteryreport` and `powercfg /energy` when safe; write reports only
  under `diagnostics/laptop-power-lag/` in this workspace.
- Battery status and health: charge, voltage, design/full-charge capacity,
  cycle count where exposed, and computed wear.
- Current CPU utilization and clock versus maximum clock. AC-vs-battery
  comparison is only possible if both states can be sampled without asking the
  user to perform an unbatched action; record the present power state clearly.
- Plug-and-play devices with errors, relevant recent System events, OEM power
  utilities/services, and thermal or battery sensor evidence exposed by Windows.

## Candidate causes to distinguish

- A corrupt or extreme battery power policy (especially CPU maximum state).
- OEM quiet/eco/battery mode forcing a very low platform power or thermal limit.
- Failing battery or ACPI/embedded-controller reporting fault.
- Firmware/BIOS or chipset/power-management driver problem.
- Thermal throttling or a device/driver interrupt storm that appears on DC.

## Safety and reporting

All commands are read-only except generation of local HTML/text diagnostic
artifacts in the workspace. Do not print secrets or broadly dump environment or
user data. Do not invoke `/setactive`, `/setacvalueindex`, `/setdcvalueindex`,
registry writes, driver updates, service changes, BIOS tools, or reboot/shutdown.
Report exact commands, salient output, limitations, and a ranked diagnosis. Any
fix requiring settings changes is left to the orchestrator/user decision.
