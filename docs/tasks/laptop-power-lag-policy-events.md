# Persistent battery lag: policy and event correlation lane

## Objective

Determine, read-only, whether Windows, AMD PMF, HP policy software, ACPI,
thermal management, sensor/display drivers, or Modern Standby events explain
the intermittent severe lag immediately after AC removal on the HP OmniBook X
Flip Laptop 14-fk0xxx. Produce a correlation report; do not remediate.

## Known evidence

- The symptom persists after multiple reboots with signed AMD PMF 26.10.15.0
  installed on `ACPI\AMDI0107\0`; it occurs on about three of five unplug
  events and clears immediately on reconnect.
- AMD UMDF Sensor `ACPI\AMDI0080\1` previously logged repeated WUDFRd load
  failures.
- Kernel-Power 88 recorded a 381 K (108 C) critical thermal hibernation for
  `\_TZ.TZS0` on 2026-08-23.
- The active High performance scheme allows 100% CPU on battery. Processor
  min AC/DC is 100/5%, max 100/100%, boost 0/0, AMD PMF Controller 2/2, and
  AMD Overlay 3/3. Do not treat a basic power-plan cap as the answer.

## Claim, ownership, and constraints

Before any command, run `python tools/work_board_claim.py list`, then claim
`docs/tasks/laptop-power-lag-policy-events-report.md`. This lane owns only that
report and read-only event/policy diagnostics. It must not create diagnostic
exports elsewhere, clear logs, start/stop services, alter event channels,
registry, scheduled tasks, power plans, drivers, devices, HP/AMD profiles,
firmware, BIOS, or Windows Update. Do not download or install software. Do not
disable thermal protections. Do not reboot. Do not commit.

Do not expose secrets or unrelated user/process/file content. Limit process
inspection to executable name, publisher/path only when necessary to identify
the owner of a PMF removal veto or policy component. Do not collect command
lines containing unrelated user data. Use local timestamps and UTC explicitly.

## Required read-only evidence

1. Record boot time, current power source, exact PMF/sensor device states and
   driver bindings, AMD PMF kernel/service status, display/battery/AC adapter
   status, and `pnputil /enum-devices /problem`.
2. Capture the active scheme and exact AC/DC values for processor min/max,
   boost, energy-performance preference if present, PCIe link state, display
   adaptation, AMD PMF Controller, and AMD Overlay. Read all applicable active
   power overlays/policies; mark absent settings as absent.
3. Read only relevant registry/service/task metadata for AMD PMF, AMD sensor,
   HP thermal/Smart Sense/power management, display, and Windows power policy.
   Record effective values and component versions. Never infer effect from a
   name alone.
4. Query System and relevant operational channels for the last 30 days and
   especially windows around known AC/DC event 105 timestamps. Include:
   Kernel-Power 41/42/88/105/172/506/507/566, Kernel-Processor-Power,
   Kernel-PnP 219/225, WUDFRd, ACPI/thermal, WHEA, display resets/timeouts,
   amdpmf/AMD services, HP thermal/policy services, Modern Standby, and battery
   events. Preserve exact provider, event ID, level, time, device ID, status
   code, and relevant message.
5. Correlate event 225 PMF removal vetoes with the responsible signed component
   and nearby driver servicing/reboot events. A removal veto during installation
   is not automatically evidence of runtime lag.
6. Compare event sequences before and after PMF 26.10.15.0 activation/reboots.
   Count WUDFRd sensor failures, thermal events, display failures, unexpected
   shutdowns, PMF service failures, and AC/DC transitions in each interval.
7. If live-capture results exist, consume them read-only and align their user
   labels with event timestamps. Do not edit or duplicate its artifacts. If
   they do not yet exist, report which correlations remain pending.

## Analysis criteria

For each hypothesis, label it `supported`, `contradicted`, or `not observed`:

- firmware/thermal emergency throttling;
- AMD PMF or HP policy applying an abnormal DC policy;
- AMD UMDF Sensor failure affecting policy input;
- display/GPU reset or power-state transition;
- interrupt/DPC storm or device removal/restart;
- storage or memory pressure;
- Modern Standby transition mistakenly occurring while active;
- basic processor maximum-state or overlay cap.

Evidence must be temporally aligned with a lag transition to call a hypothesis
supported. Historical 108 C and WUDFRd events establish risk and a lead, not
causation for every unplug event.

## User interaction

This lane should not interrupt the user. Any sensory unplug/replug steps belong
to the live-capture lane and must be batched there after all collectors are
ready. If user labels are needed, wait for that lane's report.

## Success criteria and report

Write `docs/tasks/laptop-power-lag-policy-events-report.md` with exact commands,
relevant output, counts/timelines, before/after PMF comparison, hypothesis table,
and named missing observations. State clearly whether evidence indicates a
thermal safety risk. Do not claim the issue fixed and do not propose a settings
change as a substitute for evidence. Release the claim after verifying the
report exists and contains no secrets or unrelated user data.
