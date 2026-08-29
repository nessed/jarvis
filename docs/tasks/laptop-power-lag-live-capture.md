# Persistent battery lag: synchronized live capture lane

## Objective

Capture objective Windows performance, power-source, device, and event evidence
across repeated AC-to-battery transitions on the HP OmniBook X Flip Laptop
14-fk0xxx. The laptop becomes nearly unusable on roughly three of five unplug
events and returns to normal immediately when AC is restored. This lane does
not diagnose by changing settings; it produces evidence that distinguishes CPU
throttling, interrupt/DPC pressure, storage pressure, display stalls, thermal
policy, and device/service failures during a reproduced event.

## Known evidence

- Windows 11 Pro build 26200; BIOS F.10 dated 2025-10-22.
- AMD Ryzen AI 7 350 with Radeon 860M.
- AMD PMF `ACPI\AMDI0107\0` is now Started on signed `oem125.inf`, version
  26.10.15.0, after multiple completed reboots. The symptom persists.
- AMD UMDF Sensor is `ACPI\AMDI0080\1`; earlier System events repeatedly
  recorded WUDFRd load failures for it.
- Kernel-Power 88 recorded critical thermal hibernation for `\_TZ.TZS0` at
  `_HOT = 381K` (108 C) on 2026-08-23.
- The High performance plan allows 100% maximum processor state on battery.
  AMD PMF Controller is 2 and Overlay is Best performance on AC and DC. A basic
  battery power-plan cap does not explain the symptom.

## Claim, ownership, and constraints

Before any command or edit, run `python tools/work_board_claim.py list`, then
claim this lane's output paths and physical resources. This lane owns only
`diagnostics/laptop-power-lag/live-capture*`. Use resource key
`laptop-power-transition` for the machine transition and `keyboard-focus` for
the user-marked run; do not run beside other machine benchmarks or physical-I/O
lanes. Report a conflict and stop.

The lane may create a capture script and timestamped text/CSV logs only under
that prefix. It may read Windows counters, PnP state, services, power status,
and event logs. It must not change power schemes, registry values, services,
drivers, firmware, BIOS, HP profiles, display settings, or devices. Do not
download or install software. Do not disable thermal protections. Do not
reboot. Do not commit. Do not collect environment variables, credentials,
serial numbers, unrelated processes, filenames, browser data, or user content.

## Preparation and baseline

1. Confirm the exact model, current boot time, power source, PMF and sensor
   device states, current driver INF/version, and PMF service state.
2. Capture the active power scheme and processor min/max, boost, AMD PMF
   Controller, and AMD Overlay AC/DC values. They are invariants, not knobs.
3. Record a pre-run System event-log bookmark or exact UTC timestamp.
4. Build the collector using Windows-native PowerShell/.NET only. Parse-check
   it before execution. It must flush samples incrementally so a lag or sleep
   cannot erase the reproduction.
5. Capture at one-second resolution where Windows exposes the counter:
   power-source state, battery percentage/discharge, processor frequency,
   processor performance percentage, processor utility/time, processor queue,
   DPC and interrupt time/rate, disk queue/latency/throughput, available memory,
   GPU engine utilization if available, and thermal-zone data if readable.
   Record unavailable counters explicitly; do not substitute invented metrics.
6. Snapshot only the scoped devices at every transition: AMD PMF
   `ACPI\AMDI0107\0`, AMD UMDF Sensor `ACPI\AMDI0080\1`, display adapters,
   batteries, AC adapter, and ACPI thermal devices. Record status/problem code,
   not unrelated device inventory.

## Single batched user handoff

Do all preparation and start the collector before interrupting the user. Then
ask once for this sensory sequence:

1. Leave AC connected for 60 seconds.
2. Unplug AC and observe pointer/system responsiveness for 60 seconds or until
   severe lag is unmistakable.
3. Reconnect AC for 30 seconds.
4. Repeat until five unplug transitions are complete.
5. For each transition, report only `normal`, `lag`, or `uncertain`, plus the
   approximate second lag began. Do not ask the user to run commands.

The collector must detect AC/DC edges itself. If a marker is needed, use a
single safe keypress that records only UTC time and cycle number. Do not split
the five cycles into multiple user interruptions. Stop early if the machine
approaches thermal shutdown, sleeps, crashes, or becomes unsafe to operate.

## Post-capture commands and correlation

- Stop the collector cleanly and preserve all raw artifacts.
- Query System events from the pre-run bookmark through capture end for
  Kernel-Power, Kernel-Processor-Power, Kernel-PnP, WUDFRd, ACPI, display,
  WHEA, amdpmf/AMD services, and thermal messages. Preserve event time, ID,
  level, provider, device ID, and message.
- Run `pnputil /enum-devices /instanceid "ACPI\AMDI0107\0" /drivers`, scoped
  PnP property queries, `sc.exe query amdpmf`, and
  `pnputil /enum-devices /problem` after capture.
- Correlate each user-labelled transition to a window from 15 seconds before
  unplug through 15 seconds after reconnect. Compare lag and normal cycles.

## Success criteria and report

The lane succeeds only if at least one user-labelled lag transition and one
normal transition have synchronized counter/device/event evidence, or all five
transitions are captured cleanly without reproduction. Report:

- exact commands and complete relevant outputs;
- raw artifact paths and UTC/local time mapping;
- per-cycle AC/DC times and user labels;
- minimum/average/maximum CPU frequency/performance, queue, DPC/interrupt,
  disk, memory, and GPU values for each comparison window;
- any device problem, driver/service transition, thermal event, counter gap,
  sleep, or crash;
- what the evidence rules in or out, without claiming a fix.

If the collector fails the same way twice, stop under the repository blocker
rule. Release the claim after artifacts and report are verified. Do not delete
test evidence.
