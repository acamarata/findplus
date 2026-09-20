"""`findplus poll-now` — the --device-id filter and the pinned exit codes.

Purpose    : Confirm poll-now maps every poll outcome to the exit code pinned
             in specs/cli-reference.md § poll-now (0 ok, 1 generic failure,
             4 not authenticated, 5 nothing tracked), and that --device-id
             narrows the cycle instead of polling every tracked device.
Inputs     : CliRunner invocations of `findplus poll-now`, fake providers.
Outputs    : Assertions on exit_code and per-device output.
Constraints: Never touches the network or a real Find Hub account.
"""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli.main import main
from findplus.db.session import session_scope
from findplus.ingest import upsert_device
from findplus.providers.google_findhub.types import AuthRequiredError, FindHubError
from findplus.state import track_devices
from tests.conftest import make_observation
from tests.poller_fakes import FakeProvider, _UnauthedProvider


def test_poll_now_ok_exits_zero(selected, register_provider) -> None:
    register_provider("test-fake", FakeProvider([make_observation(minutes=0)]))
    result = CliRunner().invoke(main, ["poll-now"])
    assert result.exit_code == 0, result.output


def test_poll_now_generic_failure_exits_one(selected, register_provider) -> None:
    register_provider("test-fake", FakeProvider(error=FindHubError("nova rejected")))
    result = CliRunner().invoke(main, ["poll-now"])
    assert result.exit_code == 1, result.output


def test_poll_now_unauthenticated_provider_exits_four(tmp_db, register_provider) -> None:
    register_provider("test-unauthed", _UnauthedProvider())
    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2", provider="test-unauthed")
        track_devices(session, ["TAG-001"], exclusive=True)
    result = CliRunner().invoke(main, ["poll-now"])
    assert result.exit_code == 4, result.output


def test_poll_now_auth_required_error_exits_four(selected, register_provider) -> None:
    register_provider("test-fake", FakeProvider(error=AuthRequiredError("session expired")))
    result = CliRunner().invoke(main, ["poll-now"])
    assert result.exit_code == 4, result.output


def test_poll_now_nothing_tracked_exits_five(tmp_db) -> None:
    result = CliRunner().invoke(main, ["poll-now"])
    assert result.exit_code == 5, result.output


def test_poll_now_unknown_device_id_exits_one(selected, register_provider) -> None:
    register_provider("test-fake", FakeProvider([make_observation(minutes=0)]))
    result = CliRunner().invoke(main, ["poll-now", "--device-id", "NOT-A-DEVICE"])
    assert result.exit_code == 1, result.output
    assert "Not tracked or does not exist" in result.output


def test_poll_now_device_id_filters_to_that_device(tmp_db, register_provider) -> None:
    provider_a = FakeProvider([make_observation(device_id="TAG-001")])
    provider_b = FakeProvider([make_observation(device_id="TAG-002")])
    register_provider("test-fake-a", provider_a)
    register_provider("test-fake-b", provider_b)
    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2", provider="test-fake-a")
        upsert_device(session, "TAG-002", "Moto Tag 3", provider="test-fake-b")
        track_devices(session, ["TAG-001", "TAG-002"], exclusive=True)

    result = CliRunner().invoke(main, ["poll-now", "--device-id", "TAG-001"])

    assert result.exit_code == 0, result.output
    assert provider_a.calls == 1
    assert provider_b.calls == 0
    assert "Moto Tag 2" in result.output
    assert "Moto Tag 3" not in result.output


def test_poll_now_device_id_repeatable(tmp_db, register_provider) -> None:
    provider_a = FakeProvider([make_observation(device_id="TAG-001")])
    provider_b = FakeProvider([make_observation(device_id="TAG-002")])
    provider_c = FakeProvider([make_observation(device_id="TAG-003")])
    register_provider("test-fake-a", provider_a)
    register_provider("test-fake-b", provider_b)
    register_provider("test-fake-c", provider_c)
    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2", provider="test-fake-a")
        upsert_device(session, "TAG-002", "Moto Tag 3", provider="test-fake-b")
        upsert_device(session, "TAG-003", "Moto Tag 4", provider="test-fake-c")
        track_devices(session, ["TAG-001", "TAG-002", "TAG-003"], exclusive=True)

    result = CliRunner().invoke(
        main, ["poll-now", "--device-id", "TAG-001", "--device-id", "TAG-002"]
    )

    assert result.exit_code == 0, result.output
    assert provider_a.calls == 1
    assert provider_b.calls == 1
    assert provider_c.calls == 0


# ------------------------------------------- `devices` as a group (P2-E2-W2-S1-T5)
def test_devices_default_still_lists_with_no_subcommand(selected) -> None:
    """The group conversion is behaviourally transparent for the bare command."""
    result = CliRunner().invoke(main, ["devices", "--no-refresh"])
    assert result.exit_code == 0, result.output
    assert "TAG-001" in result.output


def test_devices_label_sets_all_three_fields(selected) -> None:
    result = CliRunner().invoke(
        main,
        [
            "devices",
            "label",
            "TAG-001",
            "--label",
            "Mom",
            "--icon",
            "lucide:user-round",
            "--color",
            "#37c67a",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Mom" in result.output
    assert "lucide:user-round" in result.output
    assert "#37c67a" in result.output


def test_devices_label_no_options_is_usage_error(selected) -> None:
    result = CliRunner().invoke(main, ["devices", "label", "TAG-001"])
    assert result.exit_code == 2, result.output


def test_devices_label_unknown_device(selected) -> None:
    result = CliRunner().invoke(main, ["devices", "label", "no-such-id", "--label", "X"])
    assert result.exit_code == 1, result.output


def test_devices_label_invalid_icon(selected) -> None:
    result = CliRunner().invoke(main, ["devices", "label", "TAG-001", "--icon", "bogus"])
    assert result.exit_code == 1, result.output
    assert "icon must match lucide:" in result.output


def test_devices_label_validates_before_writing_anything(selected) -> None:
    """A good --label with a bad --color leaves the label untouched."""
    from findplus.db.models import Device

    result = CliRunner().invoke(
        main, ["devices", "label", "TAG-001", "--label", "Mom", "--color", "#FFFFFF"]
    )
    assert result.exit_code == 1, result.output
    with session_scope() as session:
        assert session.get(Device, "TAG-001").label is None


def test_devices_icons_lists_48(selected) -> None:
    import json

    result = CliRunner().invoke(main, ["devices", "icons", "--json"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == 48
