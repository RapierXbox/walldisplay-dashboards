"""Point the physical display at its dashboard and reload it.

Supported targets, in order of preference:

(a) a ShellyElevate device set up through the ``shellyelevateintegration``
    custom integration: its ``text`` entity for the dashboard URL
    (unique_id ``<device>_dashboard_url``) and its "reload dashboard" button;
(b) a ShellyElevate device discovered over MQTT: it has a "Refresh Webview"
    button but no way to set the URL, so URL pushes fall through to (c)/(d);
(c) ``display_host`` set: the ShellyElevate HTTP API on port 8080;
(d) anything else (stock Shelly firmware, generic tablets): a persistent
    notification telling the user which URL to enter.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.components import persistent_notification
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    CONF_DISPLAY_DEVICE_ID,
    CONF_DISPLAY_HOST,
    CONF_NAME,
    CONF_URL_PATH,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

ELEVATE_DOMAIN = "shellyelevateintegration"
ELEVATE_PORT = 8080
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=5)
# Service calls into other integrations are awaited during setup; don't hang on them.
SERVICE_TIMEOUT = 10

METHOD_ELEVATE_ENTITY = "elevate_entity"
METHOD_ELEVATE_HTTP = "elevate_http"
METHOD_NOTIFICATION = "notification"
METHOD_NONE = "none"


def dashboard_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Full URL of the entry's dashboard (relative path if HA has no URL)."""
    path = f"/{entry.data[CONF_URL_PATH]}"
    try:
        return get_url(hass, prefer_external=False).rstrip("/") + path
    except NoURLAvailableError:
        return path


def _display_host(entry: ConfigEntry) -> str | None:
    host = str(entry.data.get(CONF_DISPLAY_HOST) or "").strip()
    if not host:
        return None
    for prefix in ("http://", "https://"):
        host = host.removeprefix(prefix)
    return host.split("/", 1)[0] or None  # host[:port], never a path


def _device_entries(hass: HomeAssistant, device_id: str | None) -> list[er.RegistryEntry]:
    if not device_id:
        return []
    registry = er.async_get(hass)
    return [
        reg for reg in er.async_entries_for_device(registry, device_id) if reg.disabled_by is None
    ]


def _haystack(reg: er.RegistryEntry) -> str:
    parts = (
        reg.unique_id,
        reg.translation_key,
        reg.original_name,
        reg.name,
        reg.entity_id,
    )
    return " ".join(str(p) for p in parts if p).lower()


def find_elevate_url_entity(hass: HomeAssistant, device_id: str | None) -> str | None:
    """Text entity holding the ShellyElevate dashboard URL, if any."""
    candidates = [
        reg
        for reg in _device_entries(hass, device_id)
        if reg.platform == ELEVATE_DOMAIN and reg.domain == Platform.TEXT
    ]
    for reg in candidates:
        if reg.translation_key == "dashboard_url" or str(reg.unique_id).endswith("_dashboard_url"):
            return reg.entity_id
    for reg in candidates:
        if "url" in str(reg.unique_id).lower() or "url" in str(reg.translation_key).lower():
            return reg.entity_id
    return None


def find_refresh_button(hass: HomeAssistant, device_id: str | None) -> str | None:
    """Button that reloads the WebView (integration or MQTT discovery)."""
    buttons = [reg for reg in _device_entries(hass, device_id) if reg.domain == Platform.BUTTON]
    for reg in buttons:
        if reg.platform == ELEVATE_DOMAIN and (
            reg.translation_key == "reload_dashboard"
            or str(reg.unique_id).endswith("_reload_dashboard")
        ):
            return reg.entity_id
    for reg in buttons:
        text = _haystack(reg)
        if reg.platform in (ELEVATE_DOMAIN, "mqtt") and ("refresh" in text or "reload" in text):
            return reg.entity_id
    return None


def _is_elevate_device(hass: HomeAssistant, device_id: str | None) -> bool:
    return any(reg.platform == ELEVATE_DOMAIN for reg in _device_entries(hass, device_id))


def find_display_sensors(
    hass: HomeAssistant, device_id: str | None
) -> tuple[str | None, str | None]:
    """Return (temperature, humidity) sensor entity ids of the display device."""
    found: dict[str, list[str]] = {"temperature": [], "humidity": []}
    for reg in _device_entries(hass, device_id):
        if reg.domain != Platform.SENSOR:
            continue
        device_class = reg.device_class or reg.original_device_class
        if device_class is None and (state := hass.states.get(reg.entity_id)) is not None:
            device_class = state.attributes.get("device_class")
        if device_class not in found:
            continue
        # ShellyElevate can publish SoC thermal zones; those aren't room temperature.
        if "thermal" in _haystack(reg):
            continue
        found[str(device_class)].append(reg.entity_id)
    temperature = sorted(found["temperature"])
    humidity = sorted(found["humidity"])
    return (temperature[0] if temperature else None, humidity[0] if humidity else None)


async def _call_service(
    hass: HomeAssistant, domain: str, service: str, data: dict[str, Any]
) -> bool:
    """Call a service of another integration; False (logged) if it fails or hangs."""
    try:
        async with asyncio.timeout(SERVICE_TIMEOUT):
            await hass.services.async_call(domain, service, data, blocking=True)
    except TimeoutError:
        _LOGGER.warning("%s.%s timed out", domain, service)
    except HomeAssistantError as err:
        _LOGGER.warning("%s.%s failed: %s", domain, service, err)
    else:
        return True
    return False


def _base_url(host: str) -> str:
    """http://host:8080, keeping an explicit port and bracketing bare IPv6 addresses."""
    if host.count(":") > 1 and not host.startswith("["):
        host = f"[{host}]"  # bare IPv6 literal
    if host.endswith("]") or ":" not in host:
        return f"http://{host}:{ELEVATE_PORT}"
    return f"http://{host}"


async def _http(
    hass: HomeAssistant, method: str, url: str, payload: dict[str, Any] | None = None
) -> bool:
    session = async_get_clientsession(hass)
    try:
        # No redirects: only ever talk to the host the user configured.
        async with session.request(
            method, url, json=payload, timeout=HTTP_TIMEOUT, allow_redirects=False
        ) as resp:
            if resp.status >= 300:  # a redirect is not an answer either
                _LOGGER.warning("%s %s returned HTTP %s", method, url, resp.status)
                return False
            return True
    except TimeoutError:
        _LOGGER.warning("%s %s timed out", method, url)
    except aiohttp.ClientError as err:
        _LOGGER.warning("%s %s failed: %s", method, url, err)
    return False


async def _http_push(hass: HomeAssistant, host: str, url: str) -> bool:
    base = _base_url(host)
    if not await _http(hass, "POST", f"{base}/settings", {"webviewUrl": url}):
        return False
    await _http(hass, "GET", f"{base}/webview/refresh")
    return True


async def _http_refresh(hass: HomeAssistant, host: str) -> bool:
    return await _http(hass, "GET", f"{_base_url(host)}/webview/refresh")


def _notify(hass: HomeAssistant, entry: ConfigEntry, url: str) -> None:
    name = entry.data.get(CONF_NAME) or entry.title
    persistent_notification.async_create(
        hass,
        (
            f"Open this address in the browser or kiosk app of the **{name}** display:\n\n"
            f"`{url}`\n\n"
            "Set it as the start page so the display returns to it after a restart."
        ),
        title=f"Wall display dashboard for {name}",
        notification_id=f"{DOMAIN}_{entry.entry_id}_url",
    )


async def async_push_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Tell the display which URL to show. Returns the method used."""
    try:
        url = dashboard_url(hass, entry)
        absolute = url.startswith("http")
        device_id = entry.data.get(CONF_DISPLAY_DEVICE_ID)

        if (
            absolute
            and (text_entity := find_elevate_url_entity(hass, device_id))
            and await _call_service(
                hass, "text", "set_value", {"entity_id": text_entity, "value": url}
            )
        ):
            return METHOD_ELEVATE_ENTITY

        if absolute and (host := _display_host(entry)) and await _http_push(hass, host, url):
            return METHOD_ELEVATE_HTTP

        _notify(hass, entry, url)
    except Exception:
        _LOGGER.exception("Could not push the dashboard URL for %s", entry.title)
        return METHOD_NONE
    return METHOD_NOTIFICATION


async def async_refresh_display(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Reload the page on the display. Returns True if a reload was triggered."""
    device_id = entry.data.get(CONF_DISPLAY_DEVICE_ID)
    try:
        if (button := find_refresh_button(hass, device_id)) and await _call_service(
            hass, "button", "press", {"entity_id": button}
        ):
            return True

        if (
            device_id
            and _is_elevate_device(hass, device_id)
            and hass.services.has_service(ELEVATE_DOMAIN, "navigate")
            and await _call_service(
                hass,
                ELEVATE_DOMAIN,
                "navigate",
                {"device_id": [device_id], "path": f"/{entry.data[CONF_URL_PATH]}"},
            )
        ):
            return True

        if host := _display_host(entry):
            return await _http_refresh(hass, host)
    except Exception:
        _LOGGER.exception("Could not refresh display for %s", entry.title)
    return False
