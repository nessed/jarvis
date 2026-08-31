# Reversible DC active-overlay normalization test lane

## Objective

Test one reversible Windows-supported policy variable: while the laptop is
actually on battery, activate the existing Windows **Max Performance Overlay**
in place of the existing **Better Battery-life Overlay**, then run a synchronized
35-minute battery validation. Do not expose, edit, or normalize any individual
power setting in this first test. Restore the original DC overlay after the
test regardless of outcome.

This is a controlled diagnosis of the charger-triggered overlay discontinuity,
not a permanent tuning recommendation. It must not change firmware, BIOS,
drivers, services, devices, the base power scheme, thermal limits, or registry
values directly.

## Established fault evidence

The HP OmniBook X Flip Laptop 14-fk0xxx (`BG2S4PA#ABG`, board `8DA7`) has a
persistent severe battery-only lag after multiple reboots and after AMD PMF was
updated to signed `oem125.inf` 26.10.15.0.

A synchronized live capture reproduced the failure after approximately 14m43s
continuously on battery:

- actual CPU frequency fell from a 1958.06 MHz average to 616.86 MHz;
- processor performance fell from 97.91% to 30.81%, matching the exposed 31%
  minimum CPPC throttle;
- CPU time rose to 99.26% and processor queue averaged 98.67, maximum 117;
- disk queue stayed near zero, available memory increased, GPU load fell, and
  absolute interrupt rate did not spike;
- reconnecting AC restored about 2.0 GHz/99% performance and normal visible
  responsiveness immediately;
- all scoped devices stayed OK/problem code 0, AMD PMF remained Running, and no
  correlated thermal, WHEA, display, PnP, WUDFRd, or AMD-service event appeared.

The user subsequently reported the available HP UEFI battery test healthy. No
Battery failure ID was produced. Treat that as useful user-observed hardware
evidence, not proof that every board, fan, thermal, or power-path component is
healthy and not proof that the Windows policy is causal.

BIOS F.11 is explicitly deferred. The exact HP package is applicable and
staged, but the user has not confirmed a recoverable backup or that their
BitLocker recovery key is available. F.11 also prohibits reinstalling the
previous BIOS. No BIOS installer, BitLocker suspension, flash, or reboot belongs
in this lane.

## Existing base scheme and overlays

Read-only policy inspection established:

```text
Base active scheme:
  8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  High performance

AC active overlay:
  ded574b5-45a0-4f42-8737-46345c09c238  Max Performance Overlay

DC active overlay:
  961cc777-2547-4f9d-8174-7d86181b8a7a  Better Battery-life Overlay
```

The base High performance scheme has processor minimum AC/DC 100/5%, maximum
100/100%, boost mode 0/0, PMF Controller 2/2, and AMD Overlay 3/3. The effective
DC overlay, not the base scheme alone, previously exposed EPP 100%, maximum
frequency 2500 MHz, GPU Low Power, AMD PMF Controller 1, and AMD Overlay 1.
The AC overlay exposed EPP 10%, uncapped maximum frequency, GPU None, PMF
Controller 3, and AMD Overlay 3.

Those values establish that an AC/DC discontinuity exists. They do not prove
which setting enforces the delayed 31% floor. This lane changes only the active
DC overlay selector; any effective-value changes are consequences to observe,
not separately touched settings.

## Uncertain Windows behavior that must be measured

`powercfg /setactive <overlay-guid>` is the supported Windows interface selected
for this test. The observed registry state has separate
`ActiveOverlayAcPowerScheme` and `ActiveOverlayDcPowerScheme` values, but this
brief makes no unsupported claim that `powercfg /setactive` always changes only
the currently powered source, persists across AC/DC transitions, or leaves the
other selector untouched on this Windows build.

Therefore activation and rollback must occur while the machine is confirmed on
DC, and the base scheme plus both AC/DC overlay selectors must be captured before
and after every command and power-source transition. If Windows rejects the
overlay GUID, changes the AC selector, changes the base scheme, reverts the DC
selector automatically, or touches unexpected policy state, stop and rollback.
Do not substitute registry writes or per-setting commands.

## Claim and strict ownership

Before any command or file write, run `python tools/work_board_claim.py list`.
Claim:

- role `power-diagnostic`;
- work item `dc-overlay-normalization-test`;
- `docs/tasks/laptop-power-lag-dc-overlay-test-report.md`;
- `diagnostics/laptop-power-lag/dc-overlay-test*` for scripts, scheme export,
  snapshots, counters, events, and logs;
- resources `laptop-machine`, `keyboard-focus`, and
  `laptop-power-transition`.

Do not proceed on any path or resource conflict. No benchmark, firmware task,
Windows Update, HP installer, long build, sleep test, or other physical-I/O or
power-transition lane may overlap this test. Do not commit.

The lane owns only the report, claimed artifacts, one supported overlay
activation, its rollback, and read-only verification. It owns no firmware,
driver, service, device, registry edit, base scheme modification, HP/AMD app,
thermal control, personal file, or unrelated setting.

## Forbidden actions

- Do not use `powercfg /setacvalueindex`, `powercfg /setdcvalueindex`,
  `powercfg /attributes`, registry setters, Group Policy, WMI setters, HP Thermal
  Control, AMD Software, or undocumented tools.
- Do not unhide settings or modify EPP, processor frequency/min/max/boost,
  parking, GPU policy, PMF Controller, AMD Overlay, PCIe, display, NVMe, sleep,
  lid, or thermal settings individually.
- Do not create or activate a new base scheme. Do not import the exported scheme
  unless an independently reviewed recovery requires it; ordinary rollback is
  only the original overlay selector.
- Do not update, roll back, disable, restart, or reinstall PMF, sensor, display,
  battery, ACPI, or other drivers/devices/services.
- Do not launch the staged BIOS, suspend BitLocker, flash firmware, change BIOS,
  or reboot.
- Do not disable thermal protection or continue through a thermal warning,
  cooling/fan concern, battery warning, sleep, crash, or unsafe surface heat.
- Do not collect secrets, BitLocker protector data, unrelated processes/files,
  browsing data, or user content.

## Preflight and exact backup

### 1. Safety and health gates

Require all of the following immediately before the test:

- model/SKU/board still match `BG2S4PA#ABG` / `8DA7`;
- BIOS remains F.10; PMF remains `oem125.inf` 26.10.15.0, Started/problem 0,
  and `amdpmf` RUNNING;
- sensor, display, battery, AC adapter, and ACPI thermal devices are
  present/OK/problem 0; `pnputil /enum-devices /problem` is clear;
- AC is online during setup; battery is at least 80%, charging, not critical,
  and reports no active warning;
- no pending restart, active firmware operation, recent current-boot thermal
  trip, WHEA error, display reset, or critical battery/power error;
- the machine is cool, fan behavior sounds normal to the user, lid stays open,
  work is saved, and nonessential high-load applications are closed;
- the user is available for the single sensory handoff and immediate AC
  reconnection.

Thermal-zone WMI previously returned Access denied. Retry read-only thermal
telemetry if available, but explicitly record unavailable data and never invent
a temperature. Monitor Thermal-Operational and System events plus user-visible
safety cues. Historical `_HOT=381K` (108 C) means any new passive/hot/critical
event aborts the test.

### 2. Back up the base scheme and exact selectors

Before any power command, timestamp and preserve complete relevant output:

```powershell
$powerKey='HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes'
$baseGuid='8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
$acOverlayGuid='ded574b5-45a0-4f42-8737-46345c09c238'
$dcOverlayGuid='961cc777-2547-4f9d-8174-7d86181b8a7a'

powercfg /getactivescheme
powercfg /list
Get-ItemProperty -LiteralPath $powerKey |
  Select-Object ActivePowerScheme,ActiveOverlayAcPowerScheme,ActiveOverlayDcPowerScheme
powercfg /qh $baseGuid
powercfg /qh $acOverlayGuid
powercfg /qh $dcOverlayGuid
powercfg /export 'diagnostics\laptop-power-lag\dc-overlay-test-base-scheme.pow' $baseGuid
Get-FileHash -LiteralPath 'diagnostics\laptop-power-lag\dc-overlay-test-base-scheme.pow' -Algorithm SHA256
```

Also capture `powercfg /query` for base processor minimum/maximum/boost,
PCIe/display, AMD PMF Controller, and AMD Overlay; capture the complete relevant
effective values from both existing overlays. Record the current power source
through `GetSystemPowerStatus` or the verified battery-status method.

The exact expected pre-change state is:

```text
ActivePowerScheme = 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
ActiveOverlayAcPowerScheme = ded574b5-45a0-4f42-8737-46345c09c238
ActiveOverlayDcPowerScheme = 961cc777-2547-4f9d-8174-7d86181b8a7a
```

Stop if any value differs. Re-baselining to a different state would change the
specified experiment and requires a new decision, not an automatic adjustment.

Record a pre-test event bookmark and start the existing one-second-class
collector methodology while still on AC. Flush incrementally. Capture actual
CPU MHz, performance/utility/time, queue, DPC/interrupt percentages and absolute
rates, disk queue/latency, available memory, GPU, battery/source state, scoped
devices, PMF service, sample gaps, and relevant events.

## Activation: one supported overlay command only

After a five-minute AC baseline, ask the user once to unplug AC. Confirm through
two consecutive reads that power is genuinely DC/discharging and record the
original DC selector again. Then, from a visible elevated PowerShell, execute
only:

```powershell
powercfg /setactive ded574b5-45a0-4f42-8737-46345c09c238
```

Record the exact exit code and complete output. Do not chain another mutation.
Immediately re-run the base scheme, both selector, both overlay `/qh`, base
setting, power-source, device, service, and event checks.

The activation precondition passes only if:

- Windows reports command success;
- the machine remains on DC;
- `ActiveOverlayDcPowerScheme` is now exactly the Max Performance GUID;
- `ActiveOverlayAcPowerScheme` remains its original Max Performance GUID;
- `ActivePowerScheme` remains the original High performance GUID;
- no base setting changed;
- PMF and scoped devices/services remain healthy;
- no new thermal, WHEA, display, battery, or critical power event appears.

Any unexpected condition triggers immediate rollback; do not continue to the
35-minute test.

## Transition-persistence check

The per-source behavior is uncertain and must be verified before validation:

1. With the Max Performance selector verified on DC, have the user reconnect AC
   for 60 seconds. Verify power online, base scheme unchanged, AC selector still
   Max Performance, and record what happens to the stored DC selector.
2. Have the user unplug again. Verify DC/discharging and record the effective DC
   selector and full overlay values before starting the timed window.

Continue only if DC still resolves to Max Performance and all invariants hold.
If Windows automatically restores Better Battery-life on transition, record
that supported behavior and stop. Do not force persistence through registry or
individual setting changes.

## 35-minute validation

Start the 35-minute DC window only after the second unplug and selector check.
Keep the same collector running so the activation and both source transitions
are synchronized.

The user performs one batched sensory sequence:

1. Keep the lid open and use the machine normally enough to judge pointer and
   system responsiveness for 35 continuous minutes.
2. Label the experience `normal`, `lag`, or `uncertain`, with approximate onset
   time if lag appears. Do not ask the user to run commands.
3. Reconnect AC immediately at 35 minutes, or sooner on severe lag, thermal/fan
   warning, battery warning, sleep, crash, or unsafe heat.
4. Preserve five minutes of AC recovery evidence.

A successful experimental window requires all 35 minutes without the prior
approximately 617 MHz/31% performance clamp, without a queue explosion, without
visible lag, and without new device/thermal/power failures. A non-reproduction
supports the effective-overlay hypothesis but does not prove which nested
overlay value caused it or justify permanent Max Performance on battery. A
recurrence contradicts overlay-selector normalization as a sufficient repair.

## Exact rollback

Rollback is mandatory after success, failure, abort, or non-reproduction. The
normal rollback must occur while the machine is confirmed on DC because the
selector's per-source behavior is not assumed.

If the test ends with AC reconnected for safety or responsiveness, prepare the
single rollback command first, ask the user for one brief unplug, confirm DC in
two consecutive reads, then execute only:

```powershell
powercfg /setactive 961cc777-2547-4f9d-8174-7d86181b8a7a
```

Record exact output/exit code. Reconnect AC immediately after verification.
Rollback succeeds only when:

```text
ActivePowerScheme = 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
ActiveOverlayAcPowerScheme = ded574b5-45a0-4f42-8737-46345c09c238
ActiveOverlayDcPowerScheme = 961cc777-2547-4f9d-8174-7d86181b8a7a
```

Verify the complete base scheme and both overlay outputs against the timestamped
preflight, not only the GUIDs. Verify PMF/service/devices, problem devices,
power source, and new events. The exported `.pow` is backup evidence, not the
ordinary rollback path; do not import it automatically because import can
create/replace scheme state beyond the one tested selector.

If `powercfg /setactive` fails, retry once only after confirming elevation,
exact GUID, and DC source. If it fails the same way twice, reconnect AC, preserve
evidence, write the required blocker, and stop. Do not use registry edits or
per-setting commands as a workaround.

## Reporting and completion

Write `docs/tasks/laptop-power-lag-dc-overlay-test-report.md` with:

- exact commands, exit codes, and complete relevant outputs;
- base-scheme export path/hash and timestamped preflight/post/rollback snapshots;
- actual power source plus base/AC/DC selectors at every transition;
- observed—not assumed—behavior of the DC selector across AC reconnect/unplug;
- effective overlay values before/after without claiming they were individually
  modified;
- safety gates, thermal availability, scoped device/service health, and events;
- 35-minute raw artifact paths and normal/clamp/recovery statistics;
- user sensory label and onset;
- the exact rollback proof;
- anything not completed and the precise blocker.

Do not leave the DC overlay normalized after the experiment. Do not claim a
permanent fix from one 35-minute pass. Release all claims only after artifacts
and rollback are verified. Preserve evidence; do not reboot or delete it.

Preparation of this brief changes no setting and authorizes no firmware,
driver, service, device, registry, base-scheme, or per-setting modification.
