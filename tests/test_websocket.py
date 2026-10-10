"""Tests for the websocket commands, the viewport sensor and the repair flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.walldisplay_dashboards import entities, generator, repairs, websocket
from custom_components.walldisplay_dashboards.const import DOMAIN
from custom_components.walldisplay_dashboards.layout import compute_grid
from custom_components.walldisplay_dashboards.models import DisplayConfig, Profile

from .helpers_backend import (  # noqa: F401
    PACKAGE,
    entry_data,
    entry_options,
    make_entry,
    mock_frontend,
    mock_push,
)

SENSOR = "sensor.kitchen_measured_viewport"
ISSUE_ID = "viewport_mismatch_{}"

pytestmark = pytest.mark.usefixtures("mock_frontend", "mock_push")


def _display(hass: HomeAssistant, entry) -> DisplayConfig:
    """Stand-in for entities.display_config_from_entry (480x480 unless adopted)."""
    width = entry.data.get("width") or 480
    height = entry.data.get("height") or 480
    return DisplayConfig(
        entry_id=entry.entry_id,
        name="Kitchen",
        url_path="wall-kitchen",
        area_id="kitchen",
        profile=Profile("shelly_wall_display", 'Shelly Wall Display (4")', width, height),
        pages=(),
    )


@pytest.fixture
async def entry(hass: HomeAssistant):
    """A loaded wall display entry with a predictable profile."""
    entry = make_entry(hass)
    with patch(f"{PACKAGE}.entities.display_config_from_entry", side_effect=_display):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


async def test_generate(hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator) -> None:
    """generate wires entry -> display config -> input -> build_dashboard."""
    built = {"title": "Kitchen", "views": [{"path": "home", "type": "sections"}]}
    with (
        patch(f"{PACKAGE}.entities.collect_input", return_value="INPUT") as collect,
        patch(f"{PACKAGE}.generator.build_dashboard", return_value=built) as build,
    ):
        client = await hass_ws_client(hass)
        await client.send_json_auto_id({"type": f"{DOMAIN}/generate", "entry_id": entry.entry_id})
        msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"] == built
    assert collect.call_args.args[1].entry_id == entry.entry_id
    build.assert_called_once_with("INPUT")


async def test_generate_unknown_entry(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator
) -> None:
    """Unknown entry ids give not_found."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/generate", "entry_id": "nope"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"
    assert msg["error"]["translation_domain"] == DOMAIN
    assert msg["error"]["translation_key"] == "display_not_found"
    assert msg["error"]["translation_placeholders"] == {"entry_id": "nope"}


async def test_generate_error_is_translated(
    hass: HomeAssistant,
    entry,
    hass_ws_client: WebSocketGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing build is logged and answered with a translated error."""
    with patch(f"{PACKAGE}.generator.build_dashboard", side_effect=RuntimeError("boom")):
        client = await hass_ws_client(hass)
        await client.send_json_auto_id({"type": f"{DOMAIN}/generate", "entry_id": entry.entry_id})
        msg = await client.receive_json()
    assert not msg["success"]
    error = msg["error"]
    assert error["code"] == "home_assistant_error"
    assert error["message"] == (
        "Could not build the dashboard for Kitchen. Check the Home Assistant log for details"
    )
    assert error["translation_domain"] == DOMAIN
    assert error["translation_key"] == "generate_failed"
    assert error["translation_placeholders"] == {"name": "Kitchen"}
    assert "Could not build the dashboard of Kitchen" in caplog.text


async def test_generate_non_admin(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    """The panel user isn't an admin; generate must still work."""
    with patch(f"{PACKAGE}.generator.build_dashboard", return_value={"views": []}):
        client = await hass_ws_client(hass, hass_read_only_access_token)
        await client.send_json_auto_id({"type": f"{DOMAIN}/generate", "entry_id": entry.entry_id})
        msg = await client.receive_json()
    assert msg["success"], msg


async def test_list(hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator) -> None:
    """list returns every display with its frontend options."""
    second = make_entry(
        hass,
        entry_data(name="Hall", url_path="wall-hall"),
        entry_options(idle_seconds=0, kiosk="off"),
    )
    with patch(f"{PACKAGE}.generator.build_dashboard", return_value=_dashboard(footer=True)):
        displays = await _list(hass, hass_ws_client)
    rows = compute_grid(_display(hass, entry).profile, footer=True).rows
    assert displays[entry.entry_id] == {
        "entry_id": entry.entry_id,
        "url_path": "wall-kitchen",
        "idle_seconds": 60,
        "kiosk": "builtin",
        "home": "home",
        "rows": rows,
        "footer": True,
        "views": {"home": {"rows": rows, "footer": True}},
    }
    assert displays[second.entry_id]["idle_seconds"] == 0
    assert displays[second.entry_id]["kiosk"] == "off"
    assert displays[second.entry_id]["rows"] == rows


async def test_list_without_footer(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator
) -> None:
    """Home alone has no footer and gets the footer band as rows."""
    with patch(f"{PACKAGE}.generator.build_dashboard", return_value=_dashboard(footer=False)):
        displays = await _list(hass, hass_ws_client)
    profile = _display(hass, entry).profile
    assert displays[entry.entry_id]["footer"] is False
    assert displays[entry.entry_id]["rows"] == compute_grid(profile, footer=False).rows
    assert compute_grid(profile, footer=False).rows >= compute_grid(profile, footer=True).rows


async def test_list_per_view_budget(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator
) -> None:
    """The More view can have the pill while Home has none (entrance panel).

    The dashboard built for list is the one handed to dashboard_budget.
    """
    built = _dashboard(footer=False)
    built["views"].append(
        {"path": "more", "type": "sections", "footer": {"card": {}}, "sections": []}
    )
    real_budget = generator.dashboard_budget
    with (
        patch(f"{PACKAGE}.generator.build_dashboard", return_value=built) as build,
        patch(f"{PACKAGE}.generator.dashboard_budget", side_effect=real_budget) as budget,
    ):
        displays = await _list(hass, hass_ws_client)
    build.assert_called_once()
    assert budget.call_args.args[1] is built

    profile = _display(hass, entry).profile
    no_pill = compute_grid(profile, footer=False).rows
    pill = compute_grid(profile, footer=True).rows
    shown = displays[entry.entry_id]
    assert (shown["rows"], shown["footer"]) == (no_pill, False)
    assert shown["views"] == {
        "home": {"rows": no_pill, "footer": False},
        "more": {"rows": pill, "footer": True},
    }


async def test_list_generator_error(
    hass: HomeAssistant,
    entry,
    hass_ws_client: WebSocketGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If building fails, the footer is guessed from the pages option."""
    hass.config_entries.async_update_entry(entry, options=entry_options(pages=[]))
    await hass.async_block_till_done()
    with patch(f"{PACKAGE}.generator.build_dashboard", side_effect=RuntimeError("boom")):
        displays = await _list(hass, hass_ws_client)
    shown = displays[entry.entry_id]
    rows = compute_grid(_display(hass, entry).profile, footer=False).rows
    assert (shown["rows"], shown["footer"]) == (rows, False)
    assert shown["views"] == {"home": {"rows": rows, "footer": False}}
    assert "Could not build" in caplog.text


async def test_list_reuses_built_dashboards(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator
) -> None:
    """list serves the dashboard built last while it is fresh and the entry unchanged."""
    with patch(f"{PACKAGE}.generator.build_dashboard", return_value=_dashboard(footer=True)) as b:
        await _list(hass, hass_ws_client)
        await _list(hass, hass_ws_client)
    b.assert_called_once()

    # New options: built again.
    hass.config_entries.async_update_entry(entry, options=entry_options(idle_seconds=5))
    with patch(f"{PACKAGE}.generator.build_dashboard", return_value=_dashboard(footer=False)) as b:
        displays = await _list(hass, hass_ws_client)
    b.assert_called_once()
    assert displays[entry.entry_id]["footer"] is False

    # Too old: built again.
    with (
        patch(f"{PACKAGE}.websocket.CACHE_SECONDS", -1),
        patch(f"{PACKAGE}.generator.build_dashboard", return_value=_dashboard(footer=True)) as b,
    ):
        displays = await _list(hass, hass_ws_client)
    b.assert_called_once()
    assert displays[entry.entry_id]["footer"] is True


async def test_generate_always_builds(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator
) -> None:
    """generate never serves a cached dashboard; list then reuses what it built."""
    client = await hass_ws_client(hass)
    with patch(f"{PACKAGE}.generator.build_dashboard", return_value=_dashboard(footer=True)) as b:
        for _ in range(2):
            await client.send_json_auto_id(
                {"type": f"{DOMAIN}/generate", "entry_id": entry.entry_id}
            )
            assert (await client.receive_json())["success"]
        assert b.call_count == 2
        await _list(hass, hass_ws_client)
        assert b.call_count == 2


def test_dashboard_digest() -> None:
    """Equal content, equal digest, whatever the key order; any change, another digest."""
    one = {"title": "Kitchen", "views": [{"path": "home", "cards": [{"type": "tile"}]}]}
    two = {"views": [{"cards": [{"type": "tile"}], "path": "home"}], "title": "Kitchen"}
    assert websocket.dashboard_digest(one) == websocket.dashboard_digest(two)
    two["views"][0]["cards"][0]["name"] = "Ceiling"
    assert websocket.dashboard_digest(one) != websocket.dashboard_digest(two)


def _dashboard(footer: bool) -> dict:
    home = {"path": "home", "type": "sections", "sections": []}
    if footer:
        home["footer"] = {"card": {"type": "custom:wall-display-nav"}}
    return {"title": "Kitchen", "views": [home]}


async def _list(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> dict[str, dict]:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/list"})
    msg = await client.receive_json()
    assert msg["success"], msg
    return {d["entry_id"]: d for d in msg["result"]["displays"]}


async def _report(hass, hass_ws_client, entry_id: str, width: int, height: int, **extra):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/report_viewport",
            "entry_id": entry_id,
            "width": width,
            "height": height,
            "dpr": 1.5,
            "user_agent": "Mozilla/5.0 (Linux; Android 8.1) ShellyElevate",
            **extra,
        }
    )
    return await client.receive_json()


async def test_report_viewport_match(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator, issue_registry: ir.IssueRegistry
) -> None:
    """A matching report updates the sensor and raises no issue."""
    assert hass.states.get(SENSOR).state == "unknown"

    msg = await _report(hass, hass_ws_client, entry.entry_id, 480, 478, device="X1i")
    assert msg["success"], msg
    assert msg["result"] == {"profile_width": 480, "profile_height": 480, "matches": True}

    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == "480x478@1.5"
    assert state.attributes["device"] == "X1i"
    assert state.attributes["matches"] is True
    assert state.attributes["profile_width"] == 480
    assert entry.runtime_data.viewport["height"] == 478
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_ID.format(entry.entry_id)) is None


async def test_report_viewport_mismatch_and_repair(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator, issue_registry: ir.IssueRegistry
) -> None:
    """A mismatch raises a fixable issue whose flow adopts the measured size."""
    # repairs registers HTTP views, so it must be set up before the ws client starts the server.
    assert await async_setup_component(hass, "repairs", {})
    msg = await _report(hass, hass_ws_client, entry.entry_id, 600, 976)
    assert msg["result"] == {"profile_width": 480, "profile_height": 480, "matches": False}

    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ID.format(entry.entry_id))
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_key == "viewport_mismatch"
    assert issue.translation_placeholders["measured"] == "600×976"
    assert hass.states.get(SENSOR).attributes["matches"] is False

    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, context={"issue_id": issue.issue_id})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"

    result = await manager.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.data["width"] == 600
    assert entry.data["height"] == 976
    assert entry.data["profile"] == "shelly_wall_display"
    assert entry.state is ConfigEntryState.LOADED
    assert issue_registry.async_get_issue(DOMAIN, issue.issue_id) is None

    # The same size reported again now matches.
    msg = await _report(hass, hass_ws_client, entry.entry_id, 600, 976)
    assert msg["result"]["matches"] is True


async def test_report_viewport_match_clears_issue(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator, issue_registry: ir.IssueRegistry
) -> None:
    """A later matching report deletes the issue."""
    await _report(hass, hass_ws_client, entry.entry_id, 800, 1280)
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_ID.format(entry.entry_id))
    await _report(hass, hass_ws_client, entry.entry_id, 480, 480)
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_ID.format(entry.entry_id)) is None


async def test_report_viewport_unknown_entry(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator
) -> None:
    """Unknown entry ids give not_found."""
    msg = await _report(hass, hass_ws_client, "nope", 480, 480)
    assert msg["error"]["code"] == "not_found"


async def test_report_viewport_invalid(
    hass: HomeAssistant, entry, hass_ws_client: WebSocketGenerator
) -> None:
    """Bad payloads are rejected by the schema."""
    msg = await _report(hass, hass_ws_client, entry.entry_id, 0, 480)
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_format"
    # Any user may report, so sizes and strings are bounded.
    msg = await _report(hass, hass_ws_client, entry.entry_id, 480, 100_000)
    assert msg["error"]["code"] == "invalid_format"
    msg = await _report(hass, hass_ws_client, entry.entry_id, 480, 480, user_agent="x" * 5000)
    assert msg["error"]["code"] == "invalid_format"


async def test_generate_end_to_end(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    """With the real entities/generator modules, generate returns a dashboard."""
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/generate", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["success"], msg
    home = msg["result"]["views"][0]
    assert home["path"] == "home"

    # list reports what generate built.
    display = await _list(hass, hass_ws_client)
    footer = "footer" in home
    profile = entities.display_config_from_entry(hass, entry).profile
    assert display[entry.entry_id]["footer"] is footer
    assert display[entry.entry_id]["rows"] == compute_grid(profile, footer=footer).rows
    assert set(display[entry.entry_id]["views"]) == {v["path"] for v in msg["result"]["views"]}


async def test_repair_flow_entry_gone(hass: HomeAssistant, entry) -> None:
    """The repair flow of a display that was deleted meanwhile aborts."""
    assert await async_setup_component(hass, "repairs", {})
    issue_id = ISSUE_ID.format(entry.entry_id)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    # A report that raced the removal left the issue behind.
    repairs.async_create_viewport_issue(
        hass, entry.entry_id, name="Kitchen", profile="Shelly", width=600, height=976
    )
    result = await repairs_flow_manager(hass).async_init(DOMAIN, context={"issue_id": issue_id})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"
