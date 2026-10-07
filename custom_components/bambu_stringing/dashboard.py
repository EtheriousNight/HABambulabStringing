"""Auto-managed Lovelace dashboard "3D-Druck" in the sidebar.

Home Assistant has no stable public API for creating dashboards
programmatically; this module uses the internal Lovelace storage
collections (verified against HA 2026.2.3). Everything is wrapped
defensively: if the internal schema changes in a future version, the
integration logs a clear message and continues without the dashboard.

The dashboard is owned by the integration and fully regenerated on
every (re)load; manual edits to it will be overwritten. Own views in
other dashboards are not touched.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_BAMBU_DEVICE_ID,
    CONF_CAMERA_ENTITY,
    DOMAIN,
    LOGGER,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .runtime import PrinterRuntime

DASHBOARD_URL_PATH = "bambu-stringing"
DASHBOARD_TITLE = "3D-Druck"
DASHBOARD_ICON = "mdi:printer-3d"
LOVELACE_STORAGE_MODE = "storage"
LOVELACE_WAIT_TIMEOUT = 30.0
LOVELACE_WAIT_INTERVAL = 1.0

# Keyword groups for ha-bambulab printer stats (matched against entity id
# and original name; missing entities are skipped silently).
_PRINTER_STATS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("progress", "fortschritt"), "Druckfortschritt", "mdi:progress-clock"),
    (("remaining", "restzeit", "time_left"), "Restzeit", "mdi:timer-sand"),
    (("nozzle", "duese", "düse"), "Düsentemperatur", "mdi:thermometer"),
    (("bed", "bett"), "Betttemperatur", "mdi:radiator"),
    (("chamber", "kammer"), "Kammertemperatur", "mdi:coolant-temperature"),
    (("fan", "luefter", "lüfter"), "Lüfter", "mdi:fan"),
)


# -- public API ------------------------------------------------------------------


async def async_setup_printer_view(hass: HomeAssistant, runtime: PrinterRuntime) -> None:
    """Create the "3D-Druck" dashboard (once) and write one view per printer."""
    lovelace_data = await _wait_for_lovelace(hass)
    if lovelace_data is None:
        LOGGER.info(
            "Lovelace ist noch nicht bereit – Dashboard '3D-Druck' wird "
            "beim nächsten Neuladen erneut versucht."
        )
        return
    if not _is_storage_mode(lovelace_data):
        LOGGER.info(
            "Lovelace läuft nicht im Storage-Modus – das Dashboard '3D-Druck' "
            "wird nicht automatisch angelegt (YAML-Modus: eigene View in "
            "ui-lovelace.yaml pflegen)."
        )
        return
    try:
        item, created = await _ensure_dashboard(hass)
        dash = _ensure_lovelace_storage(hass, lovelace_data, item)
        if created:
            _register_sidebar_panel(hass, item, update=False)
    except Exception as err:  # noqa: BLE001 - internal HA API, stay defensive
        LOGGER.warning(
            "Dashboard '3D-Druck' konnte nicht angelegt werden (interne "
            "Lovelace-API): %s",
            err,
        )
        return
    try:
        views = [_build_printer_view(hass, rt) for rt in _sorted_runtimes(hass)]
        await dash.async_save({"views": views})
        LOGGER.info(
            "Dashboard '3D-Druck' aktualisiert (%d Drucker-View%s)",
            len(views),
            "s" if len(views) != 1 else "",
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.warning(
            "Views des Dashboards '3D-Druck' konnten nicht gespeichert werden: %s",
            err,
        )


async def async_remove_printer_view(hass: HomeAssistant, entry_id: str) -> None:
    """Remove one printer view; delete the dashboard if no printers remain."""
    lovelace_data = _lovelace_data(hass)
    if lovelace_data is None:
        return
    runtimes = hass.data.get(DOMAIN, {}).get("runtimes", {})
    try:
        if runtimes:
            dash = lovelace_data.dashboards.get(DASHBOARD_URL_PATH)
            if dash is not None:
                views = [_build_printer_view(hass, rt) for rt in _sorted_runtimes(hass)]
                await dash.async_save({"views": views})
            return

        # Last printer removed -> delete the whole dashboard.
        from homeassistant.components.lovelace.dashboard import DashboardsCollection

        collection = DashboardsCollection(hass)
        await collection.async_load()
        for item in collection.async_items():
            if item.get("url_path") == DASHBOARD_URL_PATH:
                await collection.async_delete_item(item["id"])
                break
        dash = lovelace_data.dashboards.pop(DASHBOARD_URL_PATH, None)
        if dash is not None:
            await dash.async_delete()
        try:
            from homeassistant.components import frontend

            frontend.async_remove_panel(hass, DASHBOARD_URL_PATH)
        except Exception:  # noqa: BLE001 - panel may not exist
            pass
        LOGGER.info("Dashboard '3D-Druck' entfernt (kein Drucker mehr konfiguriert)")
    except Exception as err:  # noqa: BLE001
        LOGGER.warning(
            "Dashboard '3D-Druck' konnte nicht bereinigt werden: %s", err
        )


# -- lovelace helpers ---------------------------------------------------------------


def _lovelace_data(hass: HomeAssistant) -> Any | None:
    data = hass.data.get("lovelace")
    if data is None or not hasattr(data, "dashboards"):
        return None
    return data


async def _wait_for_lovelace(hass: HomeAssistant) -> Any | None:
    """Wait for the lovelace component to finish setup at HA boot."""
    waited = 0.0
    while waited < LOVELACE_WAIT_TIMEOUT:
        data = _lovelace_data(hass)
        if data is not None:
            return data
        await asyncio.sleep(LOVELACE_WAIT_INTERVAL)
        waited += LOVELACE_WAIT_INTERVAL
    return _lovelace_data(hass)


def _is_storage_mode(lovelace_data: Any) -> bool:
    default_dashboard = lovelace_data.dashboards.get(None)
    return getattr(default_dashboard, "mode", None) == LOVELACE_STORAGE_MODE


async def _ensure_dashboard(hass: HomeAssistant) -> tuple[dict, bool]:
    """Load the dashboards collection and create our entry if missing.

    Returns the dashboard item and whether it was newly created.
    """
    from homeassistant.components.lovelace.dashboard import DashboardsCollection

    collection = DashboardsCollection(hass)
    await collection.async_load()
    for item in collection.async_items():
        if item.get("url_path") == DASHBOARD_URL_PATH:
            return item, False
    item = await collection.async_create_item(
        {
            "url_path": DASHBOARD_URL_PATH,
            "title": DASHBOARD_TITLE,
            "icon": DASHBOARD_ICON,
            "show_in_sidebar": True,
            "require_admin": False,
        }
    )
    LOGGER.info("Dashboard '3D-Druck' in der Seitenleiste angelegt")
    return item, True


def _ensure_lovelace_storage(hass: HomeAssistant, lovelace_data: Any, item: dict) -> Any:
    """Return the LovelaceStorage for our dashboard, creating it if needed.

    When the dashboard entry came from a previous boot, lovelace itself
    already created the storage instance and registered the panel. For a
    freshly created entry we register the panel ourselves (see caller).
    """
    from homeassistant.components.lovelace.dashboard import LovelaceStorage

    dashboards = lovelace_data.dashboards
    dash = dashboards.get(DASHBOARD_URL_PATH)
    if dash is None:
        dash = LovelaceStorage(hass, item)
        dashboards[DASHBOARD_URL_PATH] = dash
    return dash


def _register_sidebar_panel(hass: HomeAssistant, item: dict, *, update: bool) -> None:
    """Register the sidebar panel for a freshly created dashboard."""
    from homeassistant.components import frontend

    try:
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            frontend_url_path=DASHBOARD_URL_PATH,
            sidebar_title=item["title"],
            sidebar_icon=item.get("icon", DASHBOARD_ICON),
            config={"mode": LOVELACE_STORAGE_MODE},
            require_admin=bool(item.get("require_admin", False)),
            update=update,
        )
    except ValueError:
        # Panel already registered -> update it in place.
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            frontend_url_path=DASHBOARD_URL_PATH,
            sidebar_title=item["title"],
            sidebar_icon=item.get("icon", DASHBOARD_ICON),
            config={"mode": LOVELACE_STORAGE_MODE},
            require_admin=bool(item.get("require_admin", False)),
            update=True,
        )


def _sorted_runtimes(hass: HomeAssistant) -> list[PrinterRuntime]:
    runtimes: dict = hass.data.get(DOMAIN, {}).get("runtimes", {})
    return sorted(runtimes.values(), key=lambda rt: rt.printer_name)


# -- view building --------------------------------------------------------------------


def _registry_entity(hass: HomeAssistant, runtime: PrinterRuntime, domain: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{runtime.entry.entry_id}_{key}"
    )


def _build_printer_view(hass: HomeAssistant, runtime: PrinterRuntime) -> dict[str, Any]:
    """Build one sections view for one printer (fully regenerated).

    Layout: printer stats as small badges in the view header, then one
    section each for camera, score history, information tiles and action
    buttons.
    """
    sections: list[dict[str, Any]] = []
    camera_cards = _camera_cards(hass, runtime)
    if camera_cards:
        sections.append({"type": "grid", "cards": camera_cards})

    history_cards = _history_cards(hass, runtime)
    if history_cards:
        sections.append(
            {"type": "grid", "cards": [_heading("Score-Verlauf"), *history_cards]}
        )

    info_cards = _information_cards(hass, runtime)
    if info_cards:
        sections.append(
            {"type": "grid", "cards": [_heading("Informationen"), *info_cards]}
        )

    action_cards = _action_cards(hass, runtime)
    if action_cards:
        sections.append(
            {"type": "grid", "cards": [_heading("Aktionen"), *action_cards]}
        )

    # Grid system: fixed row heights, sections form a clean 2x2 Z-grid
    # (camera | history on top, information | actions below).
    view: dict[str, Any] = {
        "title": runtime.printer_name,
        "path": _view_path(hass, runtime),
        "icon": "mdi:printer-3d",
        "type": "sections",
        "max_columns": 2,
        "sections": sections,
    }
    badges = _view_badges(hass, runtime)
    if badges:
        view["badges"] = badges
    return view


def _view_badges(hass: HomeAssistant, runtime: PrinterRuntime) -> list[dict[str, Any]]:
    """Header badges: failure alarm first, then printer stats."""
    badges: list[dict[str, Any]] = []
    failure_id = _registry_entity(hass, runtime, "binary_sensor", "print_failure")
    if failure_id:
        badges.append(
            {
                "type": "entity",
                "entity": failure_id,
                "name": "Druckfehler",
                "icon": "mdi:alert-octagon",
            }
        )
    badges.extend(_printer_stat_badges(hass, runtime))
    return badges


def _view_path(hass: HomeAssistant, runtime: PrinterRuntime) -> str:
    paths = {
        rt.slug
        for rt in _sorted_runtimes(hass)
        if rt.entry.entry_id != runtime.entry.entry_id
    }
    path = runtime.slug or runtime.entry.entry_id
    if path in paths:
        path = f"{path}-{runtime.entry.entry_id[:8]}"
    return path


def _heading(text: str) -> dict[str, Any]:
    return {"type": "heading", "heading": text, "heading_style": "title"}


def _cover_image_entity(hass: HomeAssistant, runtime: PrinterRuntime) -> str | None:
    """ha-bambulab cover image entity (3MF thumbnail of the current print)."""
    bambu_device_id = str(runtime.opt(CONF_BAMBU_DEVICE_ID, "") or "")
    if not bambu_device_id:
        return None
    try:
        entries = er.async_entries_for_device(er.async_get(hass), bambu_device_id)
    except TypeError:
        return None
    for reg_entry in entries:
        entity_id = reg_entry.entity_id or ""
        if entity_id.startswith("image.") and "cover" in entity_id:
            return entity_id
    return None


def _camera_cards(hass: HomeAssistant, runtime: PrinterRuntime) -> list[dict[str, Any]]:
    camera_entity = str(runtime.opt(CONF_CAMERA_ENTITY, "") or "")
    cover_entity = _cover_image_entity(hass, runtime)
    # Fixed row height so camera and history graph form equal-height
    # sections on the same Z-grid row. With a cover image the camera
    # shrinks to 8 columns and the model preview takes the other 4.
    camera_grid: dict[str, Any] = (
        {"columns": 8, "rows": 6} if cover_entity else {"columns": "full", "rows": 6}
    )
    cards: list[dict[str, Any]] = [_heading("Kamera")]
    if camera_entity:
        # picture-entity instead of the (frontend-removed) camera card;
        # camera_view live shows the stream instead of a still image.
        cards.append(
            {
                "type": "picture-entity",
                "entity": camera_entity,
                "camera_image": camera_entity,
                "camera_view": "live",
                "grid_options": camera_grid,
            }
        )
    else:
        # Fallback: latest archived snapshot served from /local
        cards.append(
            {
                "type": "picture",
                "image_path": runtime.image_path,
                "name": runtime.printer_name,
                "grid_options": camera_grid,
            }
        )
    if cover_entity:
        cards.append(
            {
                "type": "picture-entity",
                "entity": cover_entity,
                "name": "Modell",
                "grid_options": {"columns": 4, "rows": 6},
            }
        )
    return cards


def _printer_stat_badges(hass: HomeAssistant, runtime: PrinterRuntime) -> list[dict[str, Any]]:
    """Auto-discover printer stats on the linked ha-bambulab device as header badges."""
    bambu_device_id = str(runtime.opt(CONF_BAMBU_DEVICE_ID, "") or "")
    if not bambu_device_id:
        return []
    try:
        entries = er.async_entries_for_device(er.async_get(hass), bambu_device_id)
    except TypeError:
        return []
    badges: list[dict[str, Any]] = []
    for keywords, name, icon in _PRINTER_STATS:
        for reg_entry in entries:
            haystack = f"{reg_entry.entity_id} {reg_entry.original_name or ''}".lower()
            if any(keyword in haystack for keyword in keywords):
                badges.append(
                    {
                        "type": "entity",
                        "entity": reg_entry.entity_id,
                        "name": name,
                        "icon": icon,
                    }
                )
                break
    return badges


def _score_entities(hass: HomeAssistant, runtime: PrinterRuntime) -> list[str]:
    entities = []
    for key in ("stringing_score", "spaghetti_score", "warping_score", "layer_shift_score"):
        entity_id = _registry_entity(hass, runtime, "sensor", key)
        if entity_id:
            entities.append(entity_id)
    return entities


def _binary_entities(hass: HomeAssistant, runtime: PrinterRuntime) -> list[str]:
    """All binary sensors (information tiles)."""
    entities = []
    for key in ("print_failure", "stringing_detected", "warping_detected", "layer_shift_detected"):
        entity_id = _registry_entity(hass, runtime, "binary_sensor", key)
        if entity_id:
            entities.append(entity_id)
    return entities


def _detection_entities(hass: HomeAssistant, runtime: PrinterRuntime) -> list[str]:
    """Detection binary sensors (history graph, without the aggregate)."""
    entities = []
    for key in ("stringing_detected", "warping_detected", "layer_shift_detected"):
        entity_id = _registry_entity(hass, runtime, "binary_sensor", key)
        if entity_id:
            entities.append(entity_id)
    return entities


def _history_cards(hass: HomeAssistant, runtime: PrinterRuntime) -> list[dict[str, Any]]:
    """12 h history graph plus glanceable score tiles, own section."""
    score_entities = _score_entities(hass, runtime)
    graph_entities = score_entities + _detection_entities(hass, runtime)
    if not graph_entities:
        return []
    cards: list[dict[str, Any]] = [
        {
            "type": "history-graph",
            "hours_to_show": 12,
            "entities": graph_entities,
            "grid_options": {"columns": "full", "rows": 6},
        }
    ]
    # Current values at a glance; more-info shows observations/other defects.
    cards.extend({"type": "tile", "entity": entity} for entity in score_entities)
    return cards


def _information_cards(hass: HomeAssistant, runtime: PrinterRuntime) -> list[dict[str, Any]]:
    """Detection state tiles: binary sensors and diagnostics counters."""
    cards: list[dict[str, Any]] = []
    for entity_id in _binary_entities(hass, runtime):
        cards.append({"type": "tile", "entity": entity_id})
    for key, name, icon in (
        ("api_calls", "API-Aufrufe", "mdi:api"),
        ("events", "Ereignisse", "mdi:alert-decagram"),
        ("last_check", "Letzte Prüfung", "mdi:clock-outline"),
    ):
        entity_id = _registry_entity(hass, runtime, "sensor", key)
        if entity_id:
            cards.append(
                {"type": "tile", "entity": entity_id, "name": name, "icon": icon}
            )
    return cards


def _action_cards(hass: HomeAssistant, runtime: PrinterRuntime) -> list[dict[str, Any]]:
    """Buttons (pause/resume/stop/check/reset) and the mute switch."""
    cards: list[dict[str, Any]] = []
    for key, name, icon in (
        ("pause", "Pause", "mdi:pause"),
        ("resume", "Resume", "mdi:play"),
        ("stop", "Stop", "mdi:stop"),
        ("check_now", "Jetzt prüfen", "mdi:eye-check"),
        ("reset", "Zurücksetzen", "mdi:restart"),
    ):
        entity_id = _registry_entity(hass, runtime, "button", key)
        if entity_id:
            cards.append(
                {"type": "button", "entity": entity_id, "name": name, "icon": icon}
            )
    mute_id = _registry_entity(hass, runtime, "switch", "mute")
    if mute_id:
        cards.append(
            {
                "type": "tile",
                "entity": mute_id,
                "name": "Stumm",
                "icon": "mdi:bell-off",
                "features": [{"type": "toggle"}],
            }
        )
    return cards
