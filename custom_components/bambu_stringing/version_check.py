"""Detect integration file updates while Home Assistant is running.

Custom integrations are deployed by copying files; Home Assistant keeps
running the previously loaded code until a restart. The check compares the
version of the loaded integration (cached by the loader at HA start) with
the manifest.json currently on disk. On mismatch a fixable repair issue is
raised; its fix flow (repairs.py) restarts Home Assistant. When both
versions match again (after the restart) the issue is deleted.

Everything is defensive: a failing check must never break the setup.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

ISSUE_RESTART_REQUIRED = "restart_required"
CHECK_INTERVAL = timedelta(hours=1)


async def async_setup_version_check(hass: HomeAssistant) -> None:
    """Run the check once at setup, then hourly while HA is running."""
    await async_check_version(hass)
    try:
        from homeassistant.helpers.event import async_track_time_interval
    except ImportError:
        LOGGER.debug("Versionsprüfung: async_track_time_interval nicht verfügbar")
        return
    hass.data.setdefault(DOMAIN, {}).setdefault("unsub", {})[
        "version_check"
    ] = async_track_time_interval(
        hass,
        lambda _now: async_check_version(hass),
        CHECK_INTERVAL,
    )


async def async_check_version(hass: HomeAssistant) -> None:
    """Compare loaded vs on-disk version; raise or delete the repair issue."""
    try:
        from homeassistant.issues import (
            IssueSeverity,
            async_create_issue,
            async_delete_issue,
        )
        from homeassistant.loader import async_get_integration
    except ImportError:
        LOGGER.debug("Versionsprüfung übersprungen: HA-Module nicht verfügbar")
        return
    try:
        loaded = str(async_get_integration(hass, DOMAIN).version)
        manifest = Path(hass.config.path("custom_components", DOMAIN, "manifest.json"))
        disk = str(
            json.loads(await hass.async_add_executor_job(manifest.read_text)).get(
                "version", ""
            )
        )
    except Exception as err:  # noqa: BLE001 - never break setup over this
        LOGGER.debug("Versionsprüfung übersprungen: %s", err)
        return
    if loaded == disk:
        async_delete_issue(hass, DOMAIN, ISSUE_RESTART_REQUIRED)
        return
    LOGGER.info(
        "Update erkannt: geladen %s, auf dem Datenträger %s – Neustart empfohlen",
        loaded,
        disk,
    )
    async_create_issue(
        hass,
        DOMAIN,
        ISSUE_RESTART_REQUIRED,
        is_fixable=True,
        is_persistent=True,
        severity=IssueSeverity.WARNING,
        translation_key=ISSUE_RESTART_REQUIRED,
        translation_placeholders={"loaded_version": loaded, "disk_version": disk},
    )
