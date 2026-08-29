# Persistent battery lag: policy and event correlation report

## Scope and conclusion

Read-only collection ran on 2026-08-29 between approximately 00:39 and
00:48 local time (UTC+05:00). No setting, service, device, driver, task, event
channel, or file outside this report was changed.

The strongest policy lead is that the displayed base plan is not the whole
effective policy. The base plan is `High performance`, but Windows has separate
active overlays:

- AC: `Max Performance Overlay` (`ded574b5-45a0-4f42-8737-46345c09c238`).
- DC: `Better Battery-life Overlay` (`961cc777-2547-4f9d-8174-7d86181b8a7a`).

The DC overlay selects processor EPP 100%, maximum frequency 2500 MHz, GPU
`Low Power`, AMD PMF Controller 1, and AMD Overlay 1 (`Better battery`). The AC
overlay selects EPP 10%, no maximum-frequency cap, GPU policy `None`, AMD PMF
Controller 3, and AMD Overlay 3 (`Best performance`). This is a real,
charger-triggered policy discontinuity that the base-plan values alone hide.
It is not yet proof of the intermittent extreme lag: a user-labeled bad
transition and performance trace are still missing, and the same DC overlay
should ordinarily apply on every unplug rather than three of five.

Two other leads remain material but uncorrelated with a labeled bad unplug:

- The AMD UMDF Sensor still records `WUDFRd` load failure `0xC0000365` once on
  every observed boot, including both boots after PMF 26.10.15.0 was activated.
- Windows Error Reporting recorded repeated historical graphics-kernel live
  dumps and an AMD display-driver monitor-power-state hang before the final PMF
  activation. No corresponding display reset, live dump, or PMF service
  failure was recorded after activation or within ten seconds of the 14
  post-activation AC/DC events.

## Safety finding

There is a confirmed thermal safety risk, independent of whether it causes
every unplug lag. On 2026-08-23 at 19:47:47 local, Kernel-Power 88 recorded a
critical thermal hibernation for `\_TZ.TZS0` at `_HOT = 381 K` (about 108 C).
Thermal-Operational 114 recorded `_TMP = 382 K` and passive cooling engagement.
At boot, Kernel-Power 125 reports `_PSV = 378 K`, `_HOT = 381 K`, and
`_CRT = 398 K`. No new thermal event occurred after the final PMF activation,
but the historical event is direct evidence that thermal protection was
required and must not be disabled.

## System and device state

Collection command:

```powershell
$os=Get-CimInstance Win32_OperatingSystem
$bat=Get-CimInstance Win32_Battery
Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus
Get-PnpDevice -PresentOnly | Where-Object {
  $_.InstanceId -match 'AMDI0107|AMDI0080' -or
  $_.Class -in @('Battery','Display')
}
pnputil /enum-devices /problem
pnputil /enum-devices /instanceid 'ACPI\AMDI0107\0' /drivers
pnputil /enum-devices /instanceid 'ACPI\AMDI0080\1' /drivers
```

Relevant output:

- Local collection time: `2026-08-29T00:39:05+05:00`; UTC:
  `2026-08-28T19:39:05Z`.
- Last boot: `2026-08-29T00:06:31.5+05:00`.
- Model: `HP OmniBook X Flip Laptop 14-fk0xxx`.
- BIOS: Insyde `F.10`, release date 2025-10-22.
- At the later authoritative battery query, `PowerOnline=True`,
  `Discharging=False`, remaining capacity 45020, and charge 79%.
- `pnputil /enum-devices /problem`: `No devices were found on the system.`
- AMD PMF `ACPI\AMDI0107\0`: Started/OK, problem code 0, `oem125.inf`,
  version `26.10.15.0` dated 2026-07-24, service `amdpmf`, WHCP-signed.
- AMD UMDF Sensor `ACPI\AMDI0080\1`: Started/OK, problem code 0,
  `oem97.inf`, version `1.1.0.37` dated 2026-01-09, service `WUDFRd`,
  WHCP-signed.
- AMD Radeon 860M: Started/OK, problem code 0, version
  `32.0.31035.1003` dated 2026-07-24.
- Microsoft AC adapter and ACPI battery: Started/OK, problem code 0.
- ACPI thermal zone `ACPI\THERMALZONE\TZS0`: Started/OK, problem code 0.

Service verification:

```powershell
sc.exe query amdpmf
sc.exe qc amdpmf
sc.exe query amdpmfservice
sc.exe qc amdpmfservice
sc.exe query WUDFRd
sc.exe qc WUDFRd
```

All three were RUNNING with exit code 0. `amdpmf.sys` and `WUDFRd.sys` are
demand-start kernel drivers. `amdpmfservice.exe` is a demand-start LocalSystem
service at version 26.10.15.0. Sensor Service and Sensor Monitoring Service
were also running. No AMD PMF service-control failure was found in either
comparison interval.

Relevant component inventory:

- AMD Chipset Software `8.08.12.551`.
- AMD PMF Ryzen AI 300 Series_2 Driver `26.10.15.0`.
- AMD SFH1.1 Driver / Sensor Fusion Hub `1.1.0.37`.
- AMD display software `26.7.1`; graphics driver `32.0.31035.1003`.
- AMD Audio Sensor Service `1.0.3.38`, present and OK.
- HP Thermal Control app `1.11.60.0`.
- HP Application Enabling Services `1.87.4769.0`, present and OK.
- HP Application Driver `1.66.3710.0`, present and OK.

The relevant scheduled-task query found no AMD PMF or HP thermal/power policy
task. It found only disabled AMD auto-update, HP Support Assistant warranty
tasks, and unrelated built-in power/input tasks. No effective PMF policy value
was present under `HKLM:\SYSTEM\CurrentControlSet\Services\amdpmf\Parameters`;
the service registry metadata only establishes component configuration, not
the behavior implied by its names.

## Effective power policy

Commands:

```powershell
powercfg /getactivescheme
powercfg /list
powercfg /query SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMIN
powercfg /query SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX
powercfg /query SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE
powercfg /query SCHEME_CURRENT SUB_PCIEXPRESS ASPM
powercfg /query SCHEME_CURRENT SUB_VIDEO ADAPTBRIGHT
powercfg /qh
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes'
powercfg /qh ded574b5-45a0-4f42-8737-46345c09c238
powercfg /qh 961cc777-2547-4f9d-8174-7d86181b8a7a
```

Base active scheme (`High performance`):

| Setting | AC | DC |
|---|---:|---:|
| Processor minimum | 100% | 5% |
| Processor maximum | 100% | 100% |
| Boost mode | Disabled (0) | Disabled (0) |
| Processor EPP, classes 0/1/2 | 0 / 0 / 0 | 0 / 0 / 0 |
| PCIe link-state management | Off | Off |
| Adaptive brightness | Off | Off |
| AMD PMF Controller | 2 | 2 |
| AMD Overlay | 3 (`Best performance`) | 3 (`Best performance`) |

`ADAPTBRIGHTNESS` was absent/invalid; the applicable setting is
`ADAPTBRIGHT`, shown above.

Active overlay state and relevant overlay values:

| Effective overlay setting | AC: Max Performance | DC: Better Battery-life |
|---|---:|---:|
| Processor minimum, class 0 | 80% | 5% |
| Processor minimum, class 1 | 100% | absent in visible DC overlay output |
| Processor maximum, class 0 | absent | 100% |
| Processor EPP, class 0 | 10% | 100% |
| Processor EPP, class 1 | 10% | 90% |
| Maximum frequency, class 0 | 0 (uncapped) | 2500 MHz |
| Maximum frequency, class 1 | 0 (uncapped) | 3300 MHz |
| Core-parking minimum, class 0 | DC field 100%; AC absent | 10% |
| Core-parking minimum, class 1 | absent | 0% |
| GPU preference | None | Low Power |
| AMD PMF Controller | 3 | 1 |
| AMD Overlay | 3 (`Best performance`) | 1 (`Better battery`) |
| Primary NVMe idle timeout | absent | 30 ms |

This proves that AC removal activates a lower-power policy bundle. It does not
show whether any one value is producing the extreme intermittent stall.

## Event and servicing timeline

All timestamps below are local (UTC+05:00). The final activation boundary is
the clean boot at `2026-08-28T17:28:54.5`; driver configuration and device
start occurred just before it.

- 2026-08-15 11:59:06: PMF 26.10.15.0 configured (`oem125.inf`). Removal was
  vetoed at 11:59:11; the device started at 12:42:28.
- 2026-08-22 02:46:41: PMF 26.10.11.0 configured (`oem59.inf`). Removal was
  vetoed at 02:46:46; the device started at 13:11:29.
- 2026-08-23 19:47:47: thermal passive cooling and three Kernel-Power 88
  records; critical thermal hibernation at `_HOT=381 K`.
- 2026-08-26 01:12: AMD display-driver monitor-power-state hang was reported
  through WER after a bugcheck (`0x19C`, AMD display stack).
- 2026-08-28 17:23:29: PMF 26.10.15.0 configured again (`oem125.inf`).
- 2026-08-28 17:23:32-17:23:35: Driver Watchdog 900/901 recorded a PMF device
  event running 5468 ms during servicing; removal veto and reboot-required
  events followed.
- 2026-08-28 17:26:30: PMF 26.10.15.0 started, service `amdpmf`.
- 2026-08-28 17:28:54: clean reboot began the final post-activation interval.
- 2026-08-28 17:29:04: AMD UMDF Sensor `WUDFRd` load failed with
  `0xC0000365`.
- 2026-08-29 00:06:35: Kernel-Power 41 recorded an unclean reboot with
  bugcheck code 0 and `SleepInProgress=5`; causation is not established.
- 2026-08-29 00:06:41: AMD UMDF Sensor `WUDFRd` load failed again with the
  same status.

### PMF removal-veto interpretation

There were seven System Kernel-PnP 225 PMF veto records in 30 days: three on
August 15, two on August 22, and two on August 28. Every group occurred five
seconds after a PMF driver configuration event and alongside Device Management
1000/1065 plus UserPnp 8000 (`reboot required`). None occurred after the final
activation boundary or at a runtime AC/DC transition.

The August 28 veto owners were:

- `svchost.exe -s DPS`, the Microsoft Diagnostic Policy Service. The binary is
  Microsoft-signed and version `10.0.26100.1`.
- `atieclxx.exe`, AMD External Events Utility. The binary is version
  `6.14.11.1290`, company AMD, and has a valid Microsoft Windows Hardware
  Compatibility Publisher signature.

August 15 also included AMD Radeon Software. The evidence identifies these as
installation-time removal vetoes, not runtime lag evidence.

## Before/after counts

Command method:

```powershell
$windowStart=Get-Date '2026-07-30T00:41:14+05:00'
$boundary=Get-Date '2026-08-28T17:28:54.5+05:00'
$sys=Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$windowStart}
# Count by ProviderName, Id, device/message, and interval.
```

| Metric | Before final activation | After final activation |
|---|---:|---:|
| Interval | 2026-07-30 00:41 to 2026-08-28 17:28 | 2026-08-28 17:28 to about 2026-08-29 00:45 |
| AC/DC transitions, Kernel-Power 105 | 651 | 14 |
| AMD sensor WUDFRd failures, PnP 219 | 19 | 2 |
| Critical thermal records, Kernel-Power 88 | 3 | 0 |
| Unexpected reboots, Kernel-Power 41 | 11 | 1 |
| Display reset 4101 | 0 | 0 |
| Modern Standby enter/exit 506/507 | 558 / 557 | 5 / 5 |
| PMF removal veto 225 | 7 | 0 |
| PMF service-control failures | 0 | 0 |

The intervals differ greatly in duration. The pre-interval also includes a
temporary 26.10.15.0 installation followed by reversion to 26.10.11.0, so this
is a chronology, not a controlled version comparison.

The post-activation structured Kernel-Power 105 sequence was:

| Local timestamp | `AcOnline` |
|---|---|
| 2026-08-28 17:29:46.691 | false |
| 2026-08-28 17:39:52.863 | true |
| 2026-08-28 17:39:55.578 | false |
| 2026-08-28 18:08:44.328 | true |
| 2026-08-28 18:59:37.457 | false |
| 2026-08-28 18:59:42.434 | true |
| 2026-08-28 19:55:18.868 | false |
| 2026-08-28 22:10:33.685 | true |
| 2026-08-28 22:30:15.130 | false |
| 2026-08-28 22:30:54.788 | true |
| 2026-08-28 23:14:51.949 | false |
| 2026-08-28 23:16:45.278 | true |
| 2026-08-29 00:33:57.077 | false |
| 2026-08-29 00:34:01.375 | true |

A ±10-second correlation around each transition found no warning/error,
thermal, display, PMF, or sensor event. One event, the 19:55:18 unplug, was
followed one second later by Modern Standby entry 506 (`Idle Timeout`). The
other 13 transitions had no 506/507 event within ten seconds. There are no
user labels yet to say which of these transitions were laggy.

## Other event evidence

Commands:

```powershell
Get-WinEvent -FilterHashtable @{LogName='System';StartTime=(Get-Date).AddDays(-30)}
Get-WinEvent -FilterHashtable @{
  LogName='Microsoft-Windows-Kernel-Power/Thermal-Operational'
  StartTime=(Get-Date).AddDays(-30)
}
Get-WinEvent -FilterHashtable @{
  LogName='Application'; ProviderName='Windows Error Reporting'; Id=1001
  StartTime=(Get-Date).AddDays(-30)
}
powercfg /a
```

- Kernel-Processor-Power produced 336 event 55 information records only. They
  enumerate CPPC capabilities; no processor throttling warning was recorded.
- The Display provider produced 51 event 4107 information records only
  (`SetDisplayConfig` force enumeration), not reset/timeout 4101.
- WHEA Errors was empty and WHEA Operational contained information records
  only. System `WHEA-Logger` produced no records.
- WER recorded repeated historical `LiveKernelEvent 193` graphics-kernel dumps
  on August 14, 15, 19, 21, and 23. It recorded an AMD display-driver
  `DRVSETMONITORPOWERSTATE_HANG` bugcheck report on August 26. No such WER
  event exists after the final PMF activation.
- Seventeen low-virtual-memory warnings were confined to August 15. None was
  post-activation or aligned to the current transition set. No post-activation
  storage warning/error was found.
- Modern Standby S0 Low Power Idle (network connected) is supported; S3 is
  unavailable. Post-activation standby entries were attributable to idle
  timeout, lid, or austerity policy. Only the single idle-timeout entry was
  within ten seconds of a charger transition.
- `powercfg /requests` could not be read because the command requires an
  elevated interactive prompt; no claim is made about current power requests.
- DriverFrameworks-UserMode/Operational is disabled, so it supplied no
  historical detail beyond System PnP 219.

## Hypothesis assessment

The required labels apply to the current intermittent lag. Historical risk or
a plausible mechanism is noted separately and is not promoted to `supported`
without a labeled bad transition.

| Hypothesis | Label | Evidence |
|---|---|---|
| Firmware/thermal emergency throttling | **not observed** | No thermal event occurred after final activation or within ±10 s of 14 AC/DC events. Historical 381 K critical hibernation confirms a serious safety lead, not current-transition causation. |
| AMD PMF or HP policy applying an abnormal DC policy | **not observed** | A large AC/DC policy discontinuity is confirmed and is the strongest current lead. Whether it becomes abnormal on the laggy 3/5 transitions needs live effective-frequency/PMF telemetry and user labels. |
| AMD UMDF Sensor failure affecting policy input | **not observed** | The same `0xC0000365` sensor load failure persists once per boot, but no sensor failure is logged at an AC/DC transition. It remains a plausible input-quality lead. |
| Display/GPU reset or power-state transition | **not observed** | No post-activation reset, timeout, or WER live dump is transition-aligned. Historical graphics live dumps and the AMD monitor-power-state hang make this a high-value lead, not proof of current lag. |
| Interrupt/DPC storm or device removal/restart | **not observed** | No runtime PMF veto/restart event is aligned. Event logs do not measure DPC/ISR latency; live trace is missing. |
| Storage or memory pressure | **not observed** | No post-activation storage or memory-pressure warning is aligned. The only low-memory cluster was August 15. |
| Modern Standby transition mistakenly occurring while active | **contradicted** | Thirteen of 14 post-activation AC/DC events had no standby transition within ±10 s. One unplug was followed by an idle-timeout standby entry, but it is not user-labeled as laggy. |
| Basic processor maximum-state or overlay cap | **not observed** | Base maximum processor state is 100% on AC and DC, contradicting a basic max-state explanation. A real DC overlay cap/bias exists (2500 MHz, EPP 100, GPU Low Power), but its causal alignment with bad versus good unplug events is not yet observed. |

## Missing observations

No live-capture artifact existed under
`diagnostics/laptop-power-lag/live-capture` when checked. The following
correlations therefore remain pending:

1. User labels for a known-good and known-bad unplug, with exact local
   timestamps matched to Kernel-Power 105.
2. Effective CPU frequency, utility, throttling reason, GPU clocks/utilization,
   disk latency, memory pressure, and DPC/ISR behavior across those transitions.
3. Confirmation that the active DC overlay and PMF/HP profile values are the
   same on a good unplug and a bad unplug, or identification of the value that
   diverges.
4. Thermal sensor readings during a bad transition; event logs only record the
   emergency threshold, not ordinary transient throttling.
5. Driver-framework detail at the time of the sensor load failure; its
   operational channel is disabled and was not altered in this read-only lane.

Until those observations exist, the evidence supports prioritizing the
AC/DC overlay transition, AMD sensor input, and AMD display power-state path in
the live capture. It does not support disabling thermal protection or claiming
the PMF driver update fixed the issue.
