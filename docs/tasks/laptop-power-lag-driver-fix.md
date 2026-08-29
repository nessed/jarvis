# Laptop battery-only lag: AMD PMF driver activation lane

## Objective and symptom

Fix the HP OmniBook X Flip Laptop 14-fk0xxx becoming nearly unusable as soon
as AC power is disconnected, then returning to normal immediately when AC is
reconnected. Mouse motion drops to fractions of a frame per second and the
machine becomes broadly unresponsive.

## Known evidence

- Windows 11 Pro build 26200; BIOS F.10 dated 2025-10-22.
- AMD Ryzen AI 7 350 with Radeon 860M.
- AMD Platform Management Framework device `ACPI\AMDI0107\0` is Started.
- The device currently uses `oem59.inf`, AMD PMF 26.10.11.0 dated 2026-05-08.
- `oem125.inf`, AMD PMF 26.10.15.0 dated 2026-07-24, is already staged and
  marked Best Ranked but is not attached to the device.
- AMD UMDF Sensor `ACPI\AMDI0080\1` is Started on 1.1.0.37; System events on
  2026-08-21 recorded WUDFRd load failures for this device.
- Kernel-Power event 88 on 2026-08-23 recorded critical thermal hibernation
  for ACPI zone `\_TZ.TZS0` at `_HOT = 381K` (108 C), followed by sleep reason
  `Thermal Zone`.
- Battery health is approximately 95.7% (56,620/59,160 mWh), with 214 cycles.
- The active High performance plan permits 100% CPU on battery; AMD Overlay is
  Best performance and PMF Controller is 2 on both AC and DC. Do not change the
  power plan as a substitute for fixing the PMF driver mismatch.

## Ownership and constraints

This lane owns this brief, read-only verification, and only narrowly scoped,
reversible activation of the already-staged `oem125.inf` driver after evidence
confirms it is the intended driver for `ACPI\AMDI0107\0`. It may not edit any
other repository file, install a different driver package, download software,
change power schemes, registry values, services, firmware, BIOS, OEM profiles,
or unrelated devices. It must not delete `oem59.inf` or any driver package.
It must not commit. No component or driver substitution is permitted. Do not
print or collect secrets, environment variables, tokens, or unrelated user
data. Do not perform destructive actions.

If Windows requires a reboot or any user-facing final confirmation, stop before
that outward action and report it for the orchestrator's batched handoff.

## Required pre-change verification

1. Confirm the computer model, current power source, and current device state.
2. Capture `pnputil /enum-devices /instanceid "ACPI\AMDI0107\0" /drivers`.
3. Confirm `oem125.inf` is already staged, signed, matches `ACPI\AMDI0107`, and
   remains Best Ranked; confirm `oem59.inf` remains the Installed driver.
4. Capture the active scheme and relevant PMF/processor AC/DC values.
5. Capture recent PMF, ACPI, sensor, thermal, display, and Kernel-Power events.
6. Establish a rollback path that rebinds the device to `oem59.inf` without
   deleting either package. If that exact rollback cannot be established, make
   no change and report the blocker.

## Allowed activation

Only after every precondition passes, activate the already-staged signed
`oem125.inf` for `ACPI\AMDI0107\0` using the narrowest Windows-supported driver
installation mechanism. Do not force-remove, uninstall, or delete the existing
driver. Record the exact command and complete output. If activation requests a
restart, do not restart automatically.

## Success criteria

- `ACPI\AMDI0107\0` is Started with AMD PMF 26.10.15.0 using `oem125.inf`.
- No new problem code appears on AMD PMF, AMD UMDF Sensor, display, battery, or
  ACPI devices.
- The active power scheme and all recorded AC/DC values remain unchanged.
- With the laptop deliberately tested on battery by the user when requested,
  pointer and system responsiveness stay normal for at least five minutes.
- CPU frequency, processor queue, disk pressure, battery discharge, and System
  events show no new severe throttle, driver failure, or critical thermal event.
- AC reconnection and a second battery transition do not reproduce the lag.

## Rollback criteria

Rollback to `oem59.inf` if 26.10.15.0 causes a device problem code, display or
sensor failure, worse responsiveness, instability, unexpected power behavior,
or a new thermal/power critical event. Verify the device is Started again on
26.10.11.0 and that no package was deleted. If rollback requires a reboot or
confirmation, stop and hand it to the orchestrator rather than guessing.

## Reporting

Report what was verified, the exact command/output for any activation, whether
a reboot is pending, before/after device binding, focused battery-mode evidence,
and anything specified but not completed. A claim that the issue is fixed must
name the verification command and the user's required visual responsiveness
check; terminal responsiveness alone is insufficient.

## Execution record (2026-08-28)

Pre-change verification passed except for activation authority:

- `Get-CimInstance Win32_ComputerSystem`, `GetSystemPowerStatus`, and
  `Get-PnpDevice` reported HP OmniBook X Flip Laptop 14-fk0xxx, AC online,
  battery 69%, AMD PMF and AMD UMDF Sensor both `OK`, and PMF problem code 0.
- `pnputil /enum-devices /instanceid "ACPI\AMDI0107\0" /drivers` reported
  `oem59.inf` 26.10.11.0 installed and signed `oem125.inf` 26.10.15.0 as Best
  Ranked for exact matching ID `ACPI\AMDI0107`.
- `pnputil /enum-devices /problem` reported no devices with problem codes.
- Active scheme remained High performance. Processor min AC/DC was 100/5%,
  max 100/100%, boost mode 0/0, AMD PMF Controller 2/2, and AMD Overlay 3/3.
- Events confirmed repeated WUDFRd failures for `ACPI\AMDI0080\1` (latest
  2026-08-26), PMF removal vetoes (2026-08-22), and Kernel-Power 88 critical
  thermal hibernations at 381 K (2026-08-23).

Rollback material was exported without deleting either package:

```text
pnputil /export-driver oem59.inf diagnostics\laptop-power-lag\amd-pmf-driver-backup\oem59
Driver package exported successfully.
Total driver packages:      1
Exported driver packages:   1

pnputil /export-driver oem125.inf diagnostics\laptop-power-lag\amd-pmf-driver-backup\oem125
Driver package exported successfully.
Total driver packages:      1
Exported driver packages:   1
```

The exact non-deleting rollback is Windows
`UpdateDriverForPlugAndPlayDevicesW` with hardware ID `ACPI\AMDI0107`, the
exported `oem59\amdpmf.inf`, and `INSTALLFLAG_FORCE`; its non-null
`bRebootRequired` result prevents an automatic reboot.

First activation attempt and complete output:

```text
pnputil /add-driver "diagnostics\laptop-power-lag\amd-pmf-driver-backup\oem125\amdpmf.inf" /install
Microsoft PnP Utility

Adding driver package:  amdpmf.inf
Driver package added successfully. (Already exists in the system)
Published Name:         oem125.inf

Total driver packages:  1
Added driver packages:  0
```

This exited 1 and did not bind the package. The second activation mechanism
called `UpdateDriverForPlugAndPlayDevicesW` for exact ID `ACPI\AMDI0107` and
the exported `oem125\amdpmf.inf`, with flags 0 and a non-null reboot pointer.
Complete output:

```text
Exception calling "Run" with "2" argument(s): "Access is denied"
CategoryInfo          : NotSpecified: (:) [], MethodInvocationException
FullyQualifiedErrorId : Win32Exception
```

Post-attempt enumeration confirmed the binding is unchanged: the device is
Started on `oem59.inf` 26.10.11.0; `oem125.inf` remains staged, signed, and
Best Ranked. No reboot was requested or initiated. Activation, post-change
health checks, and the five-minute battery test remain blocked until the API
call runs in a genuinely Administrator-elevated Windows process.

## Elevated activation and verification (2026-08-28)

The user approved UAC. The activation script completed and wrote
`diagnostics/laptop-power-lag/activate-amd-pmf-oem125.log`:

```text
ActivationSucceeded=True
RebootRequired=True
DeviceAfter.Status=OK
DeviceAfter.DriverInf=oem125.inf
DeviceAfter.DriverVersion=26.10.15.0
DeviceAfter.ProblemCode=0
PnPUtilAfter.ExitCode=0
VerificationSucceeded=True
```

Independent verification command:

```powershell
pnputil /enum-devices /instanceid "ACPI\AMDI0107\0" /drivers
Get-PnpDevice -InstanceId 'ACPI\AMDI0107\0'
Get-PnpDeviceProperty -InstanceId 'ACPI\AMDI0107\0' -KeyName 'DEVPKEY_Device_DriverInfPath','DEVPKEY_Device_DriverVersion','DEVPKEY_Device_DriverDate','DEVPKEY_Device_Service','DEVPKEY_Device_ProblemCode'
Get-Service -Name amdpmf
sc.exe query amdpmf
pnputil /enum-devices /problem
```

Exact relevant output:

```text
Status:                     Started
Driver Name:                oem125.inf
Driver Version:             07/24/2026 26.10.15.0
Driver Status:              Best Ranked / Installed
Status       : OK
Problem      : CM_PROB_NONE
Present      : True
DEVPKEY_Device_DriverInfPath oem125.inf
DEVPKEY_Device_DriverVersion 26.10.15.0
DEVPKEY_Device_DriverDate    7/24/2026 5:00:00 AM
DEVPKEY_Device_Service       amdpmf
DEVPKEY_Device_ProblemCode   0
Name        : amdpmf
DisplayName : AMD PMF Kernel Driver
Status      : Running
STATE              : 4  RUNNING
WIN32_EXIT_CODE    : 0  (0x0)
pnputil /enum-devices /problem: No devices were found on the system.
```

Read-only AC power and performance sample:

```text
PowerLineStatus=1
BatteryPercent=80
Win32_Processor CurrentClockSpeed=2000 MHz MaxClockSpeed=2000 MHz LoadPercentage=10
Processor frequency min/avg/max=2000/2000/2000 MHz
Processor performance min/avg/max=99.26/99.30/99.33%
Processor queue min/avg/max=0/0.33/1
Disk queue min/avg/max=0.01/0.04/0.09
Processor time min/avg/max=39.08/44.77/53.05%
```

`powercfg` independently confirmed the scheme and recorded values were
unchanged: High performance; processor min AC/DC 100/5%, max 100/100%, boost
mode 0/0, PMF Controller 2/2, and Overlay 3/3. No reboot was initiated.
Because the driver API returned `RebootRequired=True`, restart and the required
five-minute battery/reconnect visual responsiveness checks remain pending.
