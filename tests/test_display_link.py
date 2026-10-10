"""Tests for pushing the dashboard URL to the display."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.walldisplay_dashboards import display_link

from .helpers_backend import entry_data, make_entry

BASE = "http://192.168.1.10:8123"
DASHBOARD = f"{BASE}/wall-kitchen"
HOST = "192.168.1.50"


@pytest.fixture(autouse=True)
async def internal_url(hass: HomeAssistant) -> None:
    """Give Home Assistant a known internal URL."""
    await async_process_ha_core_config(hass, {"internal_url": BASE})


@pytest.fixture
def notify():
    """Capture persistent notifications."""
    with patch.object(display_link.persistent_notification, "async_create") as create:
        yield create


def _device(hass: HomeAssistant, domain: str) -> str:
    source = MockConfigEntry(domain=domain)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, "panel-1")}
    )
    return device.id


def _elevate_device(hass: HomeAssistant, *, with_text: bool = True) -> str:
    device_id = _device(hass, display_link.ELEVATE_DOMAIN)
    reg = er.async_get(hass)
    if with_text:
        reg.async_get_or_create(
            "text",
            display_link.ELEVATE_DOMAIN,
            f"{device_id}_dashboard_url",
            device_id=device_id,
            translation_key="dashboard_url",
            suggested_object_id="panel_dashboard_url",
        )
    reg.async_get_or_create(
        "button",
        display_link.ELEVATE_DOMAIN,
        f"{device_id}_reload_dashboard",
        device_id=device_id,
        translation_key="reload_dashboard",
        suggested_object_id="panel_reload_dashboard",
    )
    reg.async_get_or_create(
        "sensor",
        display_link.ELEVATE_DOMAIN,
        f"{device_id}_temperature",
        device_id=device_id,
        original_device_class="temperature",
        suggested_object_id="panel_temperature",
    )
    return device_id


def _mqtt_device(hass: HomeAssistant) -> str:
    device_id = _device(hass, "mqtt")
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "button",
        "mqtt",
        "shellyelevate-a3f2_refresh_webview",
        device_id=device_id,
        original_name="Refresh Webview",
        suggested_object_id="panel_refresh_webview",
    )
    reg.async_get_or_create(
        "button",
        "mqtt",
        "shellyelevate-a3f2_reboot",
        device_id=device_id,
        original_name="Reboot",
        suggested_object_id="panel_reboot",
    )
    for key, device_class in (
        ("temp", "temperature"),
        ("thermal_cpu", "temperature"),
        ("hum", "humidity"),
        ("lux", "illuminance"),
    ):
        reg.async_get_or_create(
            "sensor",
            "mqtt",
            f"shellyelevate-a3f2_{key}",
            device_id=device_id,
            original_device_class=device_class,
            suggested_object_id=f"panel_{key}",
        )
    return device_id


@pytest.mark.parametrize(
    ("host", "base"),
    [
        ("192.168.1.50", "http://192.168.1.50:8080"),
        ("panel.local:8081", "http://panel.local:8081"),
        ("fd00::50", "http://[fd00::50]:8080"),
        ("[fd00::50]:8081", "http://[fd00::50]:8081"),
    ],
)
def test_base_url(host: str, base: str) -> None:
    """The default port is added unless one is given; IPv6 literals get brackets."""
    assert display_link._base_url(host) == base


async def test_push_elevate_entity_timeout_falls_back(hass: HomeAssistant, notify) -> None:
    """A text entity that never answers doesn't block setup: the notification follows."""
    device_id = _elevate_device(hass)
    entry = make_entry(hass, entry_data(display_device_id=device_id))

    async def never_answers(call) -> None:
        await asyncio.sleep(60)

    hass.services.async_register("text", "set_value", never_answers)
    with patch.object(display_link, "SERVICE_TIMEOUT", 0.01):
        assert await display_link.async_push_url(hass, entry) == "notification"
    notify.assert_called_once()


async def test_dashboard_url(hass: HomeAssistant) -> None:
    """The full URL uses the internal URL."""
    entry = make_entry(hass)
    assert display_link.dashboard_url(hass, entry) == DASHBOARD


async def test_push_elevate_entity(hass: HomeAssistant, notify) -> None:
    """A ShellyElevate integration device gets its URL text entity set."""
    device_id = _elevate_device(hass)
    calls = async_mock_service(hass, "text", "set_value")
    entry = make_entry(hass, entry_data(display_device_id=device_id))

    assert await display_link.async_push_url(hass, entry) == "elevate_entity"
    assert len(calls) == 1
    assert calls[0].data == {"entity_id": "text.panel_dashboard_url", "value": DASHBOARD}
    notify.assert_not_called()


async def test_push_elevate_without_text_uses_host(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, notify
) -> None:
    """Without the text entity the HTTP API is used if a host is known."""
    device_id = _elevate_device(hass, with_text=False)
    aioclient_mock.post(f"http://{HOST}:8080/settings", json={"success": True})
    aioclient_mock.get(f"http://{HOST}:8080/webview/refresh", json={"success": True})
    entry = make_entry(hass, entry_data(display_device_id=device_id, display_host=HOST))

    assert await display_link.async_push_url(hass, entry) == "elevate_http"


async def test_push_mqtt_device_with_host(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, notify
) -> None:
    """MQTT can't set the URL, so the HTTP API is used."""
    device_id = _mqtt_device(hass)
    aioclient_mock.post(f"http://{HOST}:8080/settings", json={"success": True})
    aioclient_mock.get(f"http://{HOST}:8080/webview/refresh", json={"success": True})
    entry = make_entry(hass, entry_data(display_device_id=device_id, display_host=HOST))

    assert await display_link.async_push_url(hass, entry) == "elevate_http"
    method, url, data, _ = aioclient_mock.mock_calls[0]
    assert method == "POST"
    assert str(url) == f"http://{HOST}:8080/settings"
    assert data == {"webviewUrl": DASHBOARD}
    assert aioclient_mock.mock_calls[1][0] == "GET"
    notify.assert_not_called()


async def test_push_mqtt_device_without_host(hass: HomeAssistant, notify) -> None:
    """MQTT-only devices get a notification."""
    device_id = _mqtt_device(hass)
    entry = make_entry(hass, entry_data(display_device_id=device_id))
    assert await display_link.async_push_url(hass, entry) == "notification"
    assert DASHBOARD in notify.call_args.args[1]


@pytest.mark.parametrize(
    "exc", [aiohttp.ClientError("boom"), TimeoutError()], ids=["client_error", "timeout"]
)
async def test_push_http_error_falls_back(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, notify, exc: Exception
) -> None:
    """HTTP failures are logged and the user gets a notification instead."""
    aioclient_mock.post(f"http://{HOST}:8080/settings", exc=exc)
    entry = make_entry(hass, entry_data(display_host=HOST))
    assert await display_link.async_push_url(hass, entry) == "notification"
    notify.assert_called_once()


async def test_push_http_status_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, notify
) -> None:
    """An HTTP error status counts as failure."""
    aioclient_mock.post(f"http://{HOST}:8080/settings", status=500)
    entry = make_entry(hass, entry_data(display_host=HOST))
    assert await display_link.async_push_url(hass, entry) == "notification"


async def test_push_generic_display(hass: HomeAssistant, notify) -> None:
    """Stock firmware / tablets get a notification with the URL."""
    device_id = _device(hass, "shelly")
    entry = make_entry(hass, entry_data(display_device_id=device_id))
    assert await display_link.async_push_url(hass, entry) == "notification"
    message = notify.call_args.args[1]
    assert DASHBOARD in message
    notification_id = notify.call_args.kwargs["notification_id"]
    assert notification_id == f"walldisplay_dashboards_{entry.entry_id}_url"


async def test_push_never_raises(hass: HomeAssistant) -> None:
    """Unexpected errors are swallowed."""
    entry = make_entry(hass)
    with patch.object(display_link, "dashboard_url", side_effect=RuntimeError):
        assert await display_link.async_push_url(hass, entry) == "none"


async def test_refresh_elevate_button(hass: HomeAssistant) -> None:
    """The integration's reload button is pressed."""
    device_id = _elevate_device(hass)
    calls = async_mock_service(hass, "button", "press")
    entry = make_entry(hass, entry_data(display_device_id=device_id))
    assert await display_link.async_refresh_display(hass, entry) is True
    assert calls[0].data == {"entity_id": "button.panel_reload_dashboard"}


async def test_refresh_mqtt_button(hass: HomeAssistant) -> None:
    """The MQTT "Refresh Webview" button is pressed, not reboot."""
    device_id = _mqtt_device(hass)
    calls = async_mock_service(hass, "button", "press")
    entry = make_entry(hass, entry_data(display_device_id=device_id))
    assert await display_link.async_refresh_display(hass, entry) is True
    assert calls[0].data == {"entity_id": "button.panel_refresh_webview"}


async def test_refresh_http(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """With only a host, the HTTP refresh endpoint is called."""
    aioclient_mock.get(f"http://{HOST}:8080/webview/refresh", json={"success": True})
    entry = make_entry(hass, entry_data(display_host=HOST))
    assert await display_link.async_refresh_display(hass, entry) is True
    assert aioclient_mock.call_count == 1


async def test_refresh_http_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Refresh errors return False and don't raise."""
    aioclient_mock.get(f"http://{HOST}:8080/webview/refresh", exc=aiohttp.ClientError())
    entry = make_entry(hass, entry_data(display_host=HOST))
    assert await display_link.async_refresh_display(hass, entry) is False


async def test_refresh_nothing(hass: HomeAssistant) -> None:
    """Nothing to refresh returns False."""
    entry = make_entry(hass)
    assert await display_link.async_refresh_display(hass, entry) is False


async def test_find_display_sensors(hass: HomeAssistant) -> None:
    """Temperature and humidity are found by device class; thermal zones skipped."""
    device_id = _mqtt_device(hass)
    assert display_link.find_display_sensors(hass, device_id) == (
        "sensor.panel_temp",
        "sensor.panel_hum",
    )
    elevate = _elevate_device(hass)
    assert display_link.find_display_sensors(hass, elevate) == ("sensor.panel_temperature", None)
    assert display_link.find_display_sensors(hass, None) == (None, None)
