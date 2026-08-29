# Laptop battery-only lag: official-provider verification report

Research date: 2026-08-28. This report uses HP, AMD, and Microsoft primary
sources only. No software was downloaded and no machine state was changed.

## Conclusion

The local BIOS is behind HP's current exact-family security baseline: HP lists
BIOS **F.11**, SoftPaq **SP172952**, for the HP OmniBook X Flip 14-fk0xxx.
The observed F.10 therefore does not meet that current baseline. HP's published
reason for F.11 is firmware and processor security remediation; the sources
found do **not** claim thermal, AC/DC transition, embedded-controller, AMD PMF,
sensor, performance, or general-stability fixes.

The staged AMD PMF **26.10.15.0** is a real current AMD release for Ryzen AI
300-series systems. AMD's 2026-08-14 chipset package 8.08.12.551 lists that
exact PMF version and labels the Ryzen AI 300 PMF change only as "Bug Fixes."
AMD does not publish the fixed defects, and no official release note for the
locally active **26.10.11.0** was found. Consequently, official sources do not
establish that 26.10.15.0 fixes this battery-transition symptom.

HP approval for PMF 26.10.15.0 on this exact configuration remains unverified.
HP's 14-fk0000 family driver page is product-selection dependent and did not
expose a package/version inventory without the exact **product number/System
SKU**. The product number is required before claiming that an HP chipset, PMF,
graphics, or sensor package is approved for this machine. `14-fk0xxx`, the
serial number, and the HP family ID `2102790278` are not substitutes for that
product number. HP shows, for example, `AU5S8AV` as one 14-fk0000 configuration,
but that must not be inferred to be this laptop's product number.

Given the recorded 108 C `_HOT` hibernation and sensor-driver failure, the next
safe action is to run the built-in HP PC Hardware Diagnostics UEFI battery and
fan tests and preserve any 24-digit failure ID. Then obtain the local System
SKU/product number and resolve the HP package list. Do not characterize the
capacity-health result alone as a power-delivery or cooling pass. If diagnostics
pass, activation of the already-staged, signed, matching, best-ranked PMF
26.10.15.0 is the narrowest reversible driver test supported by AMD's release
notes; it is not yet proven HP-approved. Updating to HP BIOS F.11 is separately
warranted by HP's current security baseline, but is firmware writing and should
not be conflated with a demonstrated thermal fix.

## Evidence by research question

### 1. BIOS

- HP's [AMD Client UEFI Firmware Security Update](https://support.hp.com/kz-ru/document/ish_15255633-15255655-16?fallbackLocale=us-en&validated=true)
  (HPSBHF04133, published 2026-07-08; updated 2026-07-23 according to HP's
  [security-bulletin index](https://support.hp.com/gb-en/security-bulletins))
  lists the exact 14-fk0xxx family with BIOS F.11 Rev. 1, SP172952. This is
  direct evidence that F.11 supersedes the observed F.10 for the family.
- HP's [AMD Zen 5 RDSEED failure bulletin](https://support.hp.com/us-en/document/ish_15133409-15133445-16)
  (HPSBHF04125, published 2026-06-09; updated 2026-06-10 in HP's bulletin
  index) lists the same family and F.11/SP172952, Rev. 2.
- HP's [AMD Processors May 2026 Security Update](https://support.hp.com/us-en/document/ish_15142746-15143379-16)
  (HPSBHF04127, published and updated 2026-06-12 in HP's bulletin index) again
  lists 14-fk0xxx with F.11/SP172952, Rev. 2. HP later lists Rev. 3 for the same
  SoftPaq in its February 2026 processor-security bulletin. The revision varies
  by bulletin remediation packaging, but every current source found agrees on
  BIOS F.11 and SP172952.
- No current HP source found mentions a thermal, AC/DC, performance,
  embedded-controller, AMD PMF, sensor, or stability correction in F.11.
  Verified scope is security remediation only.

### 2. HP-approved chipset, PMF, graphics, and supported Windows

- HP's [14-fk0000 software and driver page](https://support.hp.com/sg-en/drivers/hp-omnibook-x-flip-14-inch-2-in-1-laptop-next-gen-ai-pc-14-fk0000/2102790278)
  confirms this is the correct family page, but it did not expose driver
  versions through the accessible official page. HP warns that if an operating
  system is not listed, it may not provide driver support for that product/OS.
- HP's [14-fk0000 series specification](https://support.hp.com/my-en/document/ish_12013044-12013104-16)
  identifies the family as released in March 2025 and explicitly lists Ryzen AI
  7 350 and Radeon 860M among its configurations. This matches the known CPU/GPU
  but does not identify the exact purchasable configuration or its driver set.
- Required lookup key: the laptop's **product number/System SKU**, retrievable
  locally without exposing the serial number. Once known, it must be used on
  HP's driver page to enumerate the exact Windows version and HP SoftPaqs.

### 3. PMF 26.10.11.0 versus 26.10.15.0

- AMD's [chipset 8.08.12.551 release notes](https://www.amd.com/en/resources/support-articles/release-notes/RN-RYZEN-CHIPSET-8-08-12-551.html)
  and [mobile chipset download page](https://www.amd.com/es/support/downloads/drivers.html/chipsets/laptop-chipsets/amd-ryzen-and-athlon-mobile-chipset.html)
  show release date **2026-08-14**, Windows 11 support for Ryzen AI 300, and PMF
  Ryzen AI 300 drivers at **26.10.15.0**, described only as **Bug Fixes**.
- AMD's previous [8.07.16.1035 release notes](https://www.amd.com/en/resources/support-articles/release-notes/RN-RYZEN-CHIPSET-8-07-16-1035.html)
  (package release date **2026-07-30**) show PMF Ryzen AI 300 at **26.10.14.0**,
  also described only as **Bug Fixes**.
- AMD's [8.05.04.516 release notes](https://www.amd.com/en/resources/support-articles/release-notes/RN-RYZEN-CHIPSET-8-05-04-516.html)
  (package release date **2026-05-18**) show PMF Ryzen AI 300 at **26.10.9.0**.
- No AMD or HP release note for exact version **26.10.11.0** was found, and AMD
  does not publish issue-level details for the changes through 26.10.15.0.
  Therefore a precise 26.10.11.0-to-26.10.15.0 changelog is unavailable.

### 4. Windows 11 build 26200

- Microsoft's [supported Windows client versions](https://learn.microsoft.com/en-us/windows/release-health/supported-versions-windows-client)
  (last updated **2026-02-10**) identifies build family **26200** as Windows 11
  **25H2**, General Availability Channel, available since **2025-09-30**.
  Windows 11 Pro 25H2 remains serviced through **2027-10-12**.
- Thus `26200` is not inherently an Insider-only or unsupported build. The full
  build number and Insider enrollment state are still needed to determine
  whether this particular installation is on a preview cumulative update.
- Exact HP support for 25H2 on the particular configuration is not established
  until the product-number-specific HP driver list is resolved.

### 5. Relevant advisories and interpretation

- No official HP, AMD, or Microsoft advisory was found for battery-source
  transition throttling on 14-fk0xxx, PMF 26.10.11.0, or `ACPI\\AMDI0080`.
- Microsoft's [ACPI-defined devices documentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/bringup/acpi-defined-devices)
  (last updated **2024-09-26**) states that `_HOT` is the threshold at which the
  OS hibernates, while `_PSV` begins passive cooling and `_CRT` shuts down.
  Therefore the recorded 381 K `_HOT` event is affirmative thermal protection,
  not an ordinary power-plan slowdown.
- Microsoft's [thermal design guide](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/design-guide)
  explains that Windows thermal control is cooperative across firmware, the OS,
  sensor drivers, and cooling-device drivers. That makes the nearby UMDF sensor
  failure relevant evidence, but not proof of causation.
- Microsoft's [UMDF failure diagnostic guidance](https://learn.microsoft.com/en-us/windows-hardware/drivers/wdf/determining-why-the-umdf-driver-fails-to-load-or-the-umdf-device-fails)
  directs investigators to validate the INF and inspect SetupAPI/WUDF logs. It
  does not identify `ACPI\\AMDI0080` or prescribe a generic replacement driver.

### 6. Official hardware diagnostics

- HP's [Testing for hardware failures](https://support.hp.com/ca-en/document/ish_2854458-2733239-16)
  documents UEFI diagnostics started with Esc then F2. It provides a battery
  test under Component Tests > Power > Battery and documents two fan tests.
  Failures produce a 24-digit failure ID for HP support.
- HP's [Hardware Diagnostics portal](https://support.hp.com/us-en/help/hp-pc-hardware-diagnostics)
  explains that UEFI diagnostics run outside Windows, which helps separate
  hardware faults from OS or driver faults. No download is required if the
  built-in UEFI diagnostics are present.
- These tests go beyond a battery capacity/health percentage: battery status,
  fan operation, and relevant system/component tests should all be recorded.

## Evidence limits

- No exact HP product number was available to this research lane.
- HP's dynamic product driver inventory was not accessible as a versioned list
  without that product number.
- No official source gives defect-level PMF release notes or links PMF
  26.10.15.0 to this symptom.
- No official source found ties F.11 to thermal or AC/DC behavior.
- No changes, downloads, installations, updates, support submissions, or
  account actions were performed.
