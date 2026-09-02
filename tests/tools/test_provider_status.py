"""The generated provider lists: what they say, and what they must never say.

Two properties matter more than the formatting. First, a rung that is
configured and cannot serve a request must appear in the second list **with a
reason** — that is the artefact whose absence let `groq`, `cerebras` and
`gemini` sit at the front of every request unserved. Second, an environment
value must never reach the output, because the output is committed.

Every test drives an explicit environment and an explicit snapshot, so none of
them can be coloured by whatever is in the real `.env`.
"""

from __future__ import annotations

import json

import pytest

from tools import provider_status


MANIFEST = {
    "providers": [
        {
            "name": "freerung",
            "endpoint": "https://free.example/v1",
            "key_env": "FREE_KEY",
            "priority": 1,
            "cost_class": "free",
            "default_model": "free-model",
            "task_profiles": ["batch"],
        },
        {
            "name": "nomodel",
            "endpoint": "https://nomodel.example/v1",
            "key_env": "NOMODEL_KEY",
            "priority": 2,
            "cost_class": "free",
            "default_model": "${NOMODEL_DEFAULT_MODEL}",
            "task_profiles": ["batch"],
        },
        {
            "name": "nokey",
            "endpoint": "https://nokey.example/v1",
            "key_env": "NOKEY_KEY",
            "priority": 3,
            "cost_class": "trial",
            "default_model": "nokey-model",
            "task_profiles": ["batch"],
        },
        {
            "name": "notarget",
            "endpoint": None,
            "key_env": None,
            "priority": 4,
            "cost_class": "paid",
            "default_model": None,
            "task_profiles": ["reasoning"],
            "not_a_router_target": True,
        },
    ]
}


@pytest.fixture
def manifest(tmp_path):
    path = tmp_path / "providers.yaml"
    path.write_text(json.dumps(MANIFEST), encoding="utf-8")
    return path


ENVIRON = {"FREE_KEY": "secret-value-must-not-appear", "NOMODEL_KEY": "another-secret"}


def test_a_rung_that_cannot_serve_a_request_is_listed_with_a_reason(manifest):
    """The artefact whose absence hid three dead rungs for days."""
    _routable, blocked = provider_status.rows(environ=ENVIRON, manifest_path=manifest)

    by_name = {b["name"]: b["reason"] for b in blocked}

    assert by_name["nomodel"] == "no model: its default_model placeholder is unset in .env"
    assert by_name["nokey"] == "no API key in NOKEY_KEY"
    assert by_name["notarget"] == "not a router target"
    assert "freerung" not in by_name


def test_a_routable_rung_carries_its_cost_class_and_its_live_state(manifest):
    routable, _blocked = provider_status.rows(
        environ=ENVIRON,
        snapshot={
            "freerung": {
                "reported": True,
                "last_status": 200,
                "cooldown_seconds_remaining": 0,
            }
        },
        manifest_path=manifest,
    )

    assert routable == [
        {"name": "freerung", "cost_class": "free", "state": "verified, last call HTTP 200"}
    ]


def test_never_verified_is_its_own_state_and_not_silence(manifest):
    """A rung with a key, a model and no cooldown looks exactly like a working one.

    Blueprint 3.3 asks for that distinction by name, and it is the state every
    rung is in right after a restart.
    """
    routable, _blocked = provider_status.rows(environ=ENVIRON, manifest_path=manifest)

    assert routable[0]["state"].startswith("never verified")


def test_a_cooling_rung_stays_routable_and_says_how_long(manifest):
    """A cooldown is resting, not broken, so it belongs in the first list."""
    routable, blocked = provider_status.rows(
        environ=ENVIRON,
        snapshot={
            "freerung": {
                "reported": True,
                "last_status": 429,
                "cooldown_seconds_remaining": 42.4,
            }
        },
        manifest_path=manifest,
    )

    assert routable[0]["state"] == "in cooldown, 42s left after HTTP 429"
    assert "freerung" not in {b["name"] for b in blocked}


def test_an_eligible_rung_whose_last_call_failed_says_so(manifest):
    routable, _blocked = provider_status.rows(
        environ=ENVIRON,
        snapshot={
            "freerung": {"reported": True, "last_status": 500, "cooldown_seconds_remaining": 0}
        },
        manifest_path=manifest,
    )

    assert routable[0]["state"] == "eligible, last call HTTP 500"


def test_no_environment_value_ever_reaches_the_output(manifest):
    """The output is committed, so this is a hard boundary rather than a habit."""
    block = provider_status.render(environ=ENVIRON, manifest_path=manifest)

    for value in ENVIRON.values():
        assert value not in block
    # The variable *names* are the whole point of the reason, and must survive.
    assert "NOKEY_KEY" in block


def test_the_rendered_block_carries_both_lists_and_a_date(manifest):
    block = provider_status.render(environ=ENVIRON, manifest_path=manifest, today="2026-09-02")

    assert block.startswith(provider_status.BEGIN)
    assert block.rstrip().endswith(provider_status.END)
    assert "_Generated by `tools/provider_status.py` on 2026-09-02._" in block
    assert "**Routable**" in block
    assert "**Configured but not routable**" in block
    assert "| `nokey` | trial | no API key in NOKEY_KEY | 2026-09-02 |" in block


def test_an_all_blocked_manifest_says_so_rather_than_rendering_an_empty_table(manifest):
    block = provider_status.render(environ={}, manifest_path=manifest)

    assert "_None. Every rung in the manifest is blocked; see below._" in block


def test_splice_replaces_the_block_and_leaves_the_rest_alone(manifest):
    block = provider_status.render(environ=ENVIRON, manifest_path=manifest, today="2026-09-02")
    document = (
        "before\n"
        f"{provider_status.BEGIN}\nstale content\n{provider_status.END}\n"
        "after\n"
    )

    spliced = provider_status.splice(document, block)

    assert spliced.startswith("before\n")
    assert spliced.endswith("\nafter\n")
    assert "stale content" not in spliced
    assert "**Routable**" in spliced


def test_splice_refuses_a_document_with_no_markers():
    with pytest.raises(SystemExit):
        provider_status.splice("no markers here", "block")


def test_check_passes_a_generated_block_and_fails_a_hand_edited_one(manifest):
    block = provider_status.render(environ=ENVIRON, manifest_path=manifest)

    assert provider_status.check(f"x\n{block}\ny") == 0
    assert provider_status.check("no markers at all") == 1

    gutted = f"{provider_status.BEGIN}\nsomeone typed this by hand\n{provider_status.END}"
    assert provider_status.check(gutted) == 1


def test_the_committed_state_md_block_is_present_and_machine_written():
    """The one test that looks at the real document, and only at its shape.

    Not a byte comparison against a fresh render: the state column reads a live
    health snapshot that changes between requests, so equality would fail
    constantly and teach everyone to ignore it.
    """
    text = provider_status.STATE_PATH.read_text(encoding="utf-8")

    assert provider_status.check(text) == 0


def test_no_hand_written_rung_table_survives_outside_the_markers():
    """The Done-when: "no hand-written provider list remains"."""
    text = provider_status.STATE_PATH.read_text(encoding="utf-8")
    before, rest = text.split(provider_status.BEGIN, 1)
    after = rest.split(provider_status.END, 1)[1]

    section = before.split("## Provider rungs", 1)[1]
    outside = section + after.split("## Open blockers", 1)[0]

    assert "| Rung | State |" not in outside
    assert "|---|---|" not in outside, "a table outside the markers is a hand-written list"
