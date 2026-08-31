# DC overlay normalization test report

## Result

The experiment was stopped at preflight. No backup/export, collector, five-minute
baseline, overlay activation, AC/DC persistence check, 35-minute user test, or
rollback was started.

Three mandatory gates failed:

1. Setup required AC online and charging. The machine was already on battery:
   `PowerOnline=False`, `Charging=False`, `Discharging=True` at 85%.
2. `PendingFileRenameOperations` was present. The brief requires no pending
   restart.
3. This boot contains a critical Kernel-Power 41 record at
   `2026-08-30 17:22:07 +05:00`, reporting an unclean prior shutdown. The brief
   excludes a recent current-boot critical power error.

Because a gate failed, the brief required preserving evidence and reporting
without changes. No `powercfg /setactive` or other mutation command was run.

Evidence artifact:

`diagnostics/laptop-power-lag/dc-overlay-test-preflight-20260830T233154+0500.txt`

## Commands and exit codes

Work-board claim:

```powershell
python tools/work_board_claim.py list
python tools/work_board_claim.py claim --role power-diagnostic `
  --work-item dc-overlay-normalization-test `
  --file docs/tasks/laptop-power-lag-dc-overlay-test-report.md `
  --file 'diagnostics/laptop-power-lag/dc-overlay-test*' `
  --resource laptop-machine --resource keyboard-focus `
  --resource laptop-power-transition
```

Both commands exited 0. No path or resource conflict existed. Claim ID:
`2a9cde43e1c345dd97b7a4608a2ebec8`.

Read-only safety preflight, exit code 0:

```powershell
$os=Get-CimInstance Win32_OperatingSystem
$cs=Get-CimInstance Win32_ComputerSystem
$prod=Get-CimInstance Win32_ComputerSystemProduct
$bb=Get-CimInstance Win32_BaseBoard
$bios=Get-CimInstance Win32_BIOS
$bat=Get-CimInstance Win32_Battery
$bs=Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus
Get-PnpDevice -PresentOnly
Get-PnpDeviceProperty -InstanceId <scoped-device-id>
pnputil /enum-devices /instanceid 'ACPI\AMDI0107\0' /drivers
pnputil /enum-devices /problem
sc.exe query amdpmf
Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' `
  -Name PendingFileRenameOperations
Get-CimInstance -Namespace root\wmi -ClassName MSAcpi_ThermalZoneTemperature
Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$os.LastBootUpTime;Level=1,2,3}
Get-WinEvent -FilterHashtable @{
  LogName='Microsoft-Windows-Kernel-Power/Thermal-Operational'
  StartTime=$os.LastBootUpTime
}
```

The overall command exited 0 while the thermal WMI subquery returned
`HRESULT 0x80041003 Access denied`. No live temperature is inferred.

Final unchanged-state snapshot, exit code 0:

```powershell
$powerKey='HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes'
$bs=Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus
powercfg /getactivescheme
Get-ItemProperty -LiteralPath $powerKey |
  Select-Object ActivePowerScheme,ActiveOverlayAcPowerScheme,ActiveOverlayDcPowerScheme
$bs | Select-Object PowerOnline,Charging,Discharging,RemainingCapacity,Voltage
```

## Preflight evidence

Collected at `2026-08-30T23:31:54.0754681+05:00`
(`2026-08-30T18:31:54.0754681Z`).

| Gate | Required | Observed | Result |
|---|---|---|---|
| Model/SKU/board | BG2S4PA#ABG / 8DA7 | HP OmniBook X Flip 14-fk0xxx / BG2S4PA#ABG / 8DA7 | pass |
| BIOS | F.10 | F.10 | pass |
| PMF binding | oem125.inf 26.10.15.0, Started/problem 0 | exact match | pass |
| PMF service | RUNNING | RUNNING, exit codes 0 | pass |
| Scoped devices | present/OK/problem 0 | sensor, display, battery, AC adapter, thermal zone, PMF all OK/problem 0 | pass |
| Problem devices | none | `No devices were found on the system.` | pass |
| Setup source | AC online and charging | DC, discharging, not charging | **fail** |
| Battery level | at least 80% | 85% | pass |
| Pending restart | none | pending file-rename marker present | **fail** |
| Current-boot thermal event | none | none returned | pass |
| Current-boot WHEA/display reset | none | none returned | pass |
| Current-boot critical power event | none | Kernel-Power 41 Critical at boot | **fail** |
| Live thermal WMI | read if available | Access denied | unavailable, not invented |

The current boot began at `2026-08-30T17:22:01.5+05:00`. In addition to the
critical event 41, System recorded the known WUDFRd failures at 17:22:07 and
17:22:13, including AMD UMDF Sensor `ACPI\AMDI0080\1`, status `0xC0000365`.
These warnings were preserved but were not themselves the reason to override
the explicit stop gates.

User-only safety checks (cool surface, normal fan sound, lid open, saved work,
nonessential load closed, and immediate availability) were not requested
because machine-readable gates had already failed and no test could start.

## Proof that policy remained unchanged

At `2026-08-30T23:32:32.2125632+05:00`:

```text
Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c (High performance)
ActivePowerScheme          = 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
ActiveOverlayAcPowerScheme = ded574b5-45a0-4f42-8737-46345c09c238
ActiveOverlayDcPowerScheme = 961cc777-2547-4f9d-8174-7d86181b8a7a
PowerOnline=False; Charging=False; Discharging=True
```

These are the exact specified pre-test selectors. Since no activation occurred,
rollback was neither necessary nor authorized. The base scheme export was not
created: the brief places safety gating before exact backup and explicitly says
to stop without changes when a gate fails.

## Not completed and blocker

The reversible DC overlay experiment and 35-minute validation were not
completed. A later attempt requires a fresh boot with no pending-restart marker
or current-boot critical power error, followed by setup while AC is online,
battery at least 80% and charging. The user sensory handoff must occur only
after those machine gates pass and the collector/baseline are ready.

Nothing in this stopped attempt supports or contradicts the Max Performance
DC-overlay hypothesis.
