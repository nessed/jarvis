"""Tests for executor.system_control.power.

Every subprocess call is faked (a recording ``run`` stand-in returning a
canned ``CompletedProcess``-like object) -- nothing here touches this
machine's real power plan, radios, or display output. The wifi-guard tests
are the sharp edge docs/tasks/laptop-system-control.md calls out: they
simulate "this is the machine's active default-route adapter", not merely
"this is the only adapter", and assert the disabling ``netsh`` command is
never invoked when the guard fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from executor.system_control import power


@dataclass
class _FakeResult:
    stdout: str = ""
    returncode: int = 0


@dataclass
class _RecordingRunner:
    """Stands in for ``subprocess.run``: records every call, returns a canned result."""

    result: _FakeResult = field(default_factory=_FakeResult)
    calls: list[dict] = field(default_factory=list)

    def __call__(self, args, **kwargs):
        self.calls.append({"args": list(args), "kwargs": kwargs})
        return self.result


# ---------------------------------------------------------------------------
# Power plans
# ---------------------------------------------------------------------------

_POWERCFG_LIST_OUTPUT = """Existing Power Schemes (* Active)
-----------------------------------
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced) *
Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (High performance)
Power Scheme GUID: a1841308-3541-4fab-bc81-f71556f20b4a  (Power saver)
"""


def test_list_power_plans_parses_powercfg_list_output() -> None:
    runner = _RecordingRunner(result=_FakeResult(stdout=_POWERCFG_LIST_OUTPUT))

    plans = power.list_power_plans(run=runner)

    assert plans == [
        power.PowerPlan(guid="381b4222-f694-41f0-9685-ff5bb260df2e", name="Balanced", active=True),
        power.PowerPlan(
            guid="8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", name="High performance", active=False
        ),
        power.PowerPlan(guid="a1841308-3541-4fab-bc81-f71556f20b4a", name="Power saver", active=False),
    ]
    assert runner.calls[0]["args"] == ["powercfg", "/list"]


def test_get_active_power_plan_returns_the_starred_plan() -> None:
    runner = _RecordingRunner(result=_FakeResult(stdout=_POWERCFG_LIST_OUTPUT))

    active = power.get_active_power_plan(run=runner)

    assert active is not None
    assert active.guid == "381b4222-f694-41f0-9685-ff5bb260df2e"


def test_get_active_power_plan_returns_none_when_nothing_is_starred() -> None:
    output = _POWERCFG_LIST_OUTPUT.replace(" *", "")
    runner = _RecordingRunner(result=_FakeResult(stdout=output))

    assert power.get_active_power_plan(run=runner) is None


def test_set_power_plan_shells_setactive_with_guid_as_its_own_argument() -> None:
    runner = _RecordingRunner()

    power.set_power_plan("a1841308-3541-4fab-bc81-f71556f20b4a", run=runner)

    assert runner.calls[0]["args"] == [
        "powercfg",
        "/setactive",
        "a1841308-3541-4fab-bc81-f71556f20b4a",
    ]


# ---------------------------------------------------------------------------
# Wifi listing
# ---------------------------------------------------------------------------

_NETSH_INTERFACES_OUTPUT = """There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 4b2a1c3e-1111-2222-3333-abcdefabcdef
    Physical address       : aa:bb:cc:dd:ee:ff
    State                  : connected
    SSID                   : HomeNetwork
"""


def test_list_wifi_interfaces_pairs_name_and_state() -> None:
    runner = _RecordingRunner(result=_FakeResult(stdout=_NETSH_INTERFACES_OUTPUT))

    interfaces = power.list_wifi_interfaces(run=runner)

    assert interfaces == [power.WifiInterface(name="Wi-Fi", state="connected")]
    assert runner.calls[0]["args"] == ["netsh", "wlan", "show", "interfaces"]


# ---------------------------------------------------------------------------
# The sharp edge: set_wifi_enabled's default-route guard
# ---------------------------------------------------------------------------


def test_set_wifi_enabled_refuses_to_disable_the_default_route_adapter() -> None:
    """Simulates "Wi-Fi IS the machine's active default-route adapter" -- the
    exact scenario the guard exists for, not merely "the only adapter"."""
    runner = _RecordingRunner()

    def fake_default_route_interface_fn(*, run):
        return "Wi-Fi"

    with pytest.raises(power.WifiGuardError):
        power.set_wifi_enabled(
            "Wi-Fi",
            False,
            run=runner,
            default_route_interface_fn=fake_default_route_interface_fn,
        )

    # The disabling netsh command must never have been reached.
    assert runner.calls == []


def test_set_wifi_enabled_guard_is_case_insensitive_and_whitespace_tolerant() -> None:
    runner = _RecordingRunner()

    def fake_default_route_interface_fn(*, run):
        return "  wi-fi  "

    with pytest.raises(power.WifiGuardError):
        power.set_wifi_enabled(
            "Wi-Fi", False, run=runner, default_route_interface_fn=fake_default_route_interface_fn
        )
    assert runner.calls == []


def test_set_wifi_enabled_allows_disabling_a_secondary_adapter() -> None:
    """The default-route adapter is Wi-Fi; disabling a *different* named
    adapter (e.g. a secondary/virtual one) must proceed."""
    runner = _RecordingRunner()

    def fake_default_route_interface_fn(*, run):
        return "Wi-Fi"

    power.set_wifi_enabled(
        "Ethernet 2",
        False,
        run=runner,
        default_route_interface_fn=fake_default_route_interface_fn,
    )

    assert runner.calls[0]["args"] == [
        "netsh",
        "interface",
        "set",
        "interface",
        "name=Ethernet 2",
        "admin=disabled",
    ]


def test_set_wifi_enabled_never_guards_an_enable_request() -> None:
    """Enabling a radio cannot disconnect anything, so it must never consult
    the default-route detector at all."""
    runner = _RecordingRunner()
    detector_calls: list[object] = []

    def fake_default_route_interface_fn(*, run):
        detector_calls.append(run)
        return "Wi-Fi"

    power.set_wifi_enabled(
        "Wi-Fi", True, run=runner, default_route_interface_fn=fake_default_route_interface_fn
    )

    assert detector_calls == []
    assert runner.calls[0]["args"] == [
        "netsh",
        "interface",
        "set",
        "interface",
        "name=Wi-Fi",
        "admin=enabled",
    ]


def test_set_wifi_enabled_proceeds_when_no_default_route_is_found() -> None:
    runner = _RecordingRunner()

    def fake_default_route_interface_fn(*, run):
        return None

    power.set_wifi_enabled(
        "Wi-Fi", False, run=runner, default_route_interface_fn=fake_default_route_interface_fn
    )

    assert runner.calls[0]["args"][-1] == "admin=disabled"


def test_default_route_interface_reads_powershell_output() -> None:
    runner = _RecordingRunner(result=_FakeResult(stdout="Wi-Fi\n"))

    result = power.default_route_interface(run=runner)

    assert result == "Wi-Fi"
    assert runner.calls[0]["args"][0] == "powershell"
    assert "-Command" in runner.calls[0]["args"]


def test_default_route_interface_returns_none_on_blank_output() -> None:
    runner = _RecordingRunner(result=_FakeResult(stdout="   \n"))

    assert power.default_route_interface(run=runner) is None


# ---------------------------------------------------------------------------
# Bluetooth radio (PnP)
# ---------------------------------------------------------------------------


def test_list_bluetooth_radios_parses_json_list() -> None:
    payload = (
        '[{"InstanceId": "BTHENUM\\\\DEV_1", "FriendlyName": "Intel Bluetooth", "Status": "OK"}]'
    )
    runner = _RecordingRunner(result=_FakeResult(stdout=payload))

    devices = power.list_bluetooth_radios(run=runner)

    assert devices == [
        power.PnpDevice(instance_id="BTHENUM\\DEV_1", friendly_name="Intel Bluetooth", status="OK")
    ]


def test_list_bluetooth_radios_normalizes_a_single_object_to_a_list() -> None:
    payload = '{"InstanceId": "BTHENUM\\\\DEV_1", "FriendlyName": "Intel Bluetooth", "Status": "OK"}'
    runner = _RecordingRunner(result=_FakeResult(stdout=payload))

    devices = power.list_bluetooth_radios(run=runner)

    assert len(devices) == 1
    assert devices[0].instance_id == "BTHENUM\\DEV_1"


def test_list_bluetooth_radios_returns_empty_list_for_blank_output() -> None:
    runner = _RecordingRunner(result=_FakeResult(stdout=""))

    assert power.list_bluetooth_radios(run=runner) == []


def test_set_bluetooth_enabled_passes_instance_id_via_environment_not_command_text() -> None:
    """The instance id must never be interpolated into the PowerShell command
    string -- it is read back at runtime via $env:JARVIS_PNP_INSTANCE_ID, so a
    payload-controlled id can never break out of its argument."""
    runner = _RecordingRunner()
    malicious_id = 'BTHENUM\\DEV_1"; Remove-Item C:\\ -Recurse -Force #'

    power.set_bluetooth_enabled(malicious_id, True, run=runner)

    call = runner.calls[0]
    command_text = call["args"][call["args"].index("-Command") + 1]
    assert malicious_id not in command_text
    assert call["kwargs"]["env"]["JARVIS_PNP_INSTANCE_ID"] == malicious_id
    assert call["kwargs"]["env"]["JARVIS_PNP_ACTION"] == "Enable"


def test_set_bluetooth_enabled_disable_sets_disable_action() -> None:
    runner = _RecordingRunner()

    power.set_bluetooth_enabled("BTHENUM\\DEV_1", False, run=runner)

    assert runner.calls[0]["kwargs"]["env"]["JARVIS_PNP_ACTION"] == "Disable"


# ---------------------------------------------------------------------------
# Display switching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,flag",
    [("internal", "/internal"), ("EXTERNAL", "/external"), ("clone", "/clone"), ("extend", "/extend")],
)
def test_switch_display_maps_mode_to_flag(mode: str, flag: str) -> None:
    runner = _RecordingRunner()

    power.switch_display(mode, run=runner)

    assert runner.calls[0]["args"] == ["DisplaySwitch.exe", flag]


def test_switch_display_rejects_unknown_mode_without_shelling_out() -> None:
    runner = _RecordingRunner()

    with pytest.raises(power.InvalidDisplayModeError):
        power.switch_display("mirror", run=runner)

    assert runner.calls == []
