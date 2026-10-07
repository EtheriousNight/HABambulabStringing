"""Per-printer detection pipeline (frame grab -> gate -> Mistral -> decision).

One ``PrinterRuntime`` instance per config entry (spec section 5.0: multi
printer support with independent gate, streak state, cooldown and archive).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import slugify

from .const import (
    ATTR_API_CALLS,
    ATTR_API_FAILURES,
    ATTR_BED_ADHESION_FAILURE,
    ATTR_DISCARDED,
    ATTR_EVENTS,
    ATTR_GRAB_FAILURES,
    ATTR_LAST_CHECK,
    ATTR_LAST_ERROR,
    ATTR_LAYER_SHIFT_DETECTED,
    ATTR_LAYER_SHIFT_SCORE,
    ATTR_MUTED,
    ATTR_OBSERVATIONS,
    ATTR_OTHER_DEFECTS,
    ATTR_PRINT_FAILURE,
    ATTR_PRINT_ID,
    ATTR_PRINT_RUNNING,
    ATTR_SPAGHETTI_SCORE,
    ATTR_STRINGING_DETECTED,
    ATTR_STRINGING_SCORE,
    ATTR_WARPING_DETECTED,
    ATTR_WARPING_SCORE,
    CONF_API_KEY,
    CONF_AUTO_PAUSE,
    CONF_BAMBU_DEVICE_ID,
    CONF_CAMERA_ENTITY,
    CONF_CHECK_INTERVAL,
    CONF_COOLDOWN_MIN,
    CONF_DEEP_LINK,
    CONF_LAYER_SHIFT_THRESHOLD,
    CONF_MANUAL_CONTEXT,
    CONF_MJPEG_URL,
    CONF_MODEL,
    CONF_NAME,
    CONF_NOTIFY_SERVICES,
    CONF_PAUSE_SERVICE,
    CONF_PRINT_STATE_ENTITY,
    CONF_RESUME_SERVICE,
    CONF_RETENTION_DAYS,
    CONF_RUNNING_STATES,
    CONF_SPAGHETTI_THRESHOLD,
    CONF_STOP_SERVICE,
    CONF_STRINGING_STREAK,
    CONF_STRINGING_THRESHOLD,
    CONF_WARPING_THRESHOLD,
    DEFAULT_CHECK_INTERVAL,
    DEFAULT_COOLDOWN_MIN,
    DEFAULT_DEEP_LINK_TEMPLATE,
    DEFAULT_LAYER_SHIFT_THRESHOLD,
    DEFAULT_MODEL,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_PAUSE_SERVICE,
    DEFAULT_RESUME_SERVICE,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_RUNNING_STATES,
    DEFAULT_SPAGHETTI_THRESHOLD,
    DEFAULT_STOP_SERVICE,
    DEFAULT_STRINGING_STREAK,
    DEFAULT_STRINGING_THRESHOLD,
    DEFAULT_WARPING_THRESHOLD,
    DOMAIN,
    GATE_POLL_SECONDS,
    LOGGER,
)
from .core import archive as archive_mod
from .core import mistral as mistral_mod
from .core.decision import Decision, DecisionEngine, EngineConfig
from .core.mistral import AnalysisResult
from .core.mjpeg import MJPEGGrabError, grab_jpeg

PRUNE_INTERVAL_SEC = 3600.0


def get_value(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Merge options over initial config data."""
    if key in entry.options:
        return entry.options[key]
    if key in entry.data:
        return entry.data[key]
    return default


class PipelineCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Push-based coordinator: the runtime pushes new pipeline data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.data.get(CONF_NAME, entry.entry_id)}",
        )
        self.entry = entry
        self.data: dict[str, Any] = empty_pipeline_data()

    async def _async_update_data(self) -> dict[str, Any]:
        return self.data


def empty_pipeline_data() -> dict[str, Any]:
    return {
        ATTR_STRINGING_SCORE: None,
        ATTR_SPAGHETTI_SCORE: None,
        ATTR_WARPING_SCORE: None,
        ATTR_LAYER_SHIFT_SCORE: None,
        ATTR_OTHER_DEFECTS: (),
        ATTR_BED_ADHESION_FAILURE: None,
        ATTR_OBSERVATIONS: None,
        ATTR_STRINGING_DETECTED: False,
        ATTR_WARPING_DETECTED: False,
        ATTR_LAYER_SHIFT_DETECTED: False,
        ATTR_PRINT_FAILURE: False,
        ATTR_MUTED: False,
        ATTR_API_CALLS: 0,
        ATTR_API_FAILURES: 0,
        ATTR_DISCARDED: 0,
        ATTR_GRAB_FAILURES: 0,
        ATTR_EVENTS: 0,
        ATTR_LAST_CHECK: None,
        ATTR_PRINT_RUNNING: False,
        ATTR_PRINT_ID: None,
        ATTR_LAST_ERROR: None,
    }


class PrinterRuntime:
    """Owns the detection loop for exactly one printer."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = PipelineCoordinator(hass, entry)
        self.printer_name: str = entry.data.get(CONF_NAME, entry.entry_id)
        self.slug: str = slugify(self.printer_name)
        self.archive = archive_mod.SnapshotArchive(
            Path(hass.config.config_dir) / "www" / "snapshots" / self.slug,
            retention_days=int(get_value(entry, CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)),
        )
        self.engine = DecisionEngine(self._engine_config())
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._force_check = False
        self._last_check = 0.0
        self._print_id: str | None = None
        self._last_prune = 0.0
        self.via_device: tuple[str, str] | None = None
        self.api_calls = 0
        self.api_failures = 0
        self.discarded = 0
        self.grab_failures = 0
        self._last_result: AnalysisResult | None = None
        self._last_error: str | None = None
        self._logged_gate_off = False

    # -- config ---------------------------------------------------------------

    def opt(self, key: str, default: Any) -> Any:
        return get_value(self.entry, key, default)

    def _engine_config(self) -> EngineConfig:
        return EngineConfig(
            stringing_threshold=int(
                get_value(self.entry, CONF_STRINGING_THRESHOLD, DEFAULT_STRINGING_THRESHOLD)
            ),
            stringing_streak=int(
                get_value(self.entry, CONF_STRINGING_STREAK, DEFAULT_STRINGING_STREAK)
            ),
            spaghetti_threshold=int(
                get_value(self.entry, CONF_SPAGHETTI_THRESHOLD, DEFAULT_SPAGHETTI_THRESHOLD)
            ),
            warping_threshold=int(
                get_value(self.entry, CONF_WARPING_THRESHOLD, DEFAULT_WARPING_THRESHOLD)
            ),
            layer_shift_threshold=int(
                get_value(
                    self.entry,
                    CONF_LAYER_SHIFT_THRESHOLD,
                    DEFAULT_LAYER_SHIFT_THRESHOLD,
                )
            ),
            stringing_cooldown_sec=int(
                get_value(self.entry, CONF_COOLDOWN_MIN, DEFAULT_COOLDOWN_MIN)
            )
            * 60,
        )

    @property
    def deep_link(self) -> str:
        return self.opt(
            CONF_DEEP_LINK, DEFAULT_DEEP_LINK_TEMPLATE.format(slug=self.slug)
        )

    @property
    def image_path(self) -> str:
        return f"/local/snapshots/{self.slug}/latest.jpg"

    # -- lifecycle ------------------------------------------------------------

    async def async_start(self) -> None:
        """Start the background loop and resolve the ha-bambulab link."""
        registry = dr.async_get(self.hass)
        bambu_device_id = self.opt(CONF_BAMBU_DEVICE_ID, None)
        if bambu_device_id:
            try:
                device = registry.async_get(bambu_device_id)
            except TypeError:  # older HA without async_get(device_id)
                device = registry.devices.get(bambu_device_id)
            if device is not None and device.identifiers:
                self.via_device = next(iter(device.identifiers))
        self._validate_gate_entity()
        self._task = self.hass.async_create_task(self._run())
        LOGGER.info(
            "Stringing-Detection für '%s' gestartet (Intervall %s s)",
            self.printer_name,
            self.opt(CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL),
        )

    def _validate_gate_entity(self) -> None:
        """Log warnings for a misconfigured print-state entity at startup."""
        entity_id = self.opt(CONF_PRINT_STATE_ENTITY, "")
        if not entity_id:
            LOGGER.error(
                "'%s': Kein Druckstatus-Entity konfiguriert – Gate ist "
                "fail-closed, es werden keine Bilder analysiert. Bitte in den "
                "Integration-Optionen ein sensor.* Entity hinterlegen "
                "(z.B. sensor.<drucker>_print_status von ha-bambulab).",
                self.printer_name,
            )
            return
        if not entity_id.startswith("sensor."):
            LOGGER.warning(
                "'%s': Druckstatus-Entity '%s' ist kein sensor.* – "
                "erwartet wird z.B. sensor.<drucker>_print_status.",
                self.printer_name,
                entity_id,
            )
        state = self.hass.states.get(entity_id)
        if state is None:
            LOGGER.warning(
                "'%s': Druckstatus-Entity '%s' existiert noch nicht – "
                "Gate bleibt geschlossen bis das Entity verfügbar ist.",
                self.printer_name,
                entity_id,
            )
            return
        running_states = [
            s.strip().upper()
            for s in str(self.opt(CONF_RUNNING_STATES, DEFAULT_RUNNING_STATES)).split(",")
            if s.strip()
        ]
        current = str(state.state).upper()
        gcode_state = state.attributes.get("gcode_state")
        effective = str(gcode_state).upper() if gcode_state is not None else current
        if effective not in running_states:
            LOGGER.info(
                "'%s': Gate-Entity '%s' ist bereit (aktueller State: '%s', "
                "gcode_state: %s, laufende States: %s).",
                self.printer_name,
                entity_id,
                state.state,
                gcode_state,
                running_states,
            )

    async def async_stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    # -- external triggers ------------------------------------------------------

    @callback
    def async_request_check_now(self) -> None:
        """Analyze one frame immediately, regardless of the interval."""
        self._force_check = True
        self._wake.set()

    @callback
    def async_mute_for_print(self) -> None:
        """Toggle mute for the current print (notification 'Ignorieren')."""
        self.set_muted(not self.engine.muted)

    @callback
    def reset_detection(self) -> None:
        """Manually reset detection state (streaks, flags, notification latches).

        Mute and the current print id are untouched; this clears a stuck
        ``print_failure`` / notification latch without waiting for a new print.
        """
        self.engine.reset()
        self._push()
        LOGGER.info(
            "Detection-Status für '%s' zurückgesetzt (Streaks, Flags, "
            "Benachrichtigungs-Arretierung)",
            self.printer_name,
        )

    @callback
    def set_muted(self, muted: bool) -> None:
        self.engine.mute_current_print(muted)
        self._push()
        LOGGER.info(
            "Benachrichtigungen für '%s' %s",
            self.printer_name,
            "stummgeschaltet" if muted else "reaktiviert",
        )

    async def async_pause_print(self) -> None:
        await self._call_printer_service(
            self.opt(CONF_PAUSE_SERVICE, DEFAULT_PAUSE_SERVICE), "Pause"
        )

    async def async_resume_print(self) -> None:
        await self._call_printer_service(
            self.opt(CONF_RESUME_SERVICE, DEFAULT_RESUME_SERVICE), "Resume"
        )

    async def async_stop_print(self) -> None:
        await self._call_printer_service(
            self.opt(CONF_STOP_SERVICE, DEFAULT_STOP_SERVICE), "Stop"
        )

    async def _call_printer_service(self, service: str, action: str) -> None:
        domain, _, name = service.partition(".")
        if not domain or not name:
            raise HomeAssistantError(f"Ungültiger Service '{service}'")
        if not self.hass.services.has_service(domain, name):
            raise HomeAssistantError(
                f"Service '{service}' nicht verfügbar (ha-bambulab installiert?)"
            )
        target = None
        device_id = self.opt(CONF_BAMBU_DEVICE_ID, None)
        if device_id:
            target = {"device_id": [device_id]}
        try:
            await self.hass.services.async_call(
                domain, name, {}, blocking=True, target=target
            )
            LOGGER.info("'%s': %s über %s ausgeführt", self.printer_name, action, service)
        except HomeAssistantError as err:
            LOGGER.error("'%s': %s fehlgeschlagen: %s", self.printer_name, action, err)
            raise

    # -- gate -------------------------------------------------------------------

    def _print_running(self) -> bool:
        entity_id = self.opt(CONF_PRINT_STATE_ENTITY, "")
        if not entity_id:
            if not self._logged_gate_off:
                LOGGER.error(
                    "Druckstatus-Gate für '%s' nicht konfiguriert – Analyse "
                    "deaktiviert (fail-closed). Bitte Status-Entity in den "
                    "Optionen hinterlegen.",
                    self.printer_name,
                )
                self._logged_gate_off = True
            return False
        state = self.hass.states.get(entity_id)
        if state is None:
            LOGGER.debug("'%s': Status-Entity %s unbekannt", self.printer_name, entity_id)
            return False
        gcode_state = state.attributes.get("gcode_state")
        current = str(gcode_state if gcode_state is not None else state.state)
        running_states = [
            s.strip().upper()
            for s in str(self.opt(CONF_RUNNING_STATES, DEFAULT_RUNNING_STATES)).split(",")
            if s.strip()
        ]
        is_running = current.upper() in running_states
        LOGGER.debug(
            "'%s': Gate-Check entity=%s state=%s gcode_state=%s running_states=%s -> %s",
            self.printer_name,
            entity_id,
            state.state,
            gcode_state,
            running_states,
            is_running,
        )
        return is_running

    def _build_context(self) -> str:
        parts: list[str] = []
        manual = str(self.opt(CONF_MANUAL_CONTEXT, "") or "").strip()
        if manual:
            parts.append(manual)
        entity_id = self.opt(CONF_PRINT_STATE_ENTITY, "")
        if entity_id and (state := self.hass.states.get(entity_id)) is not None:
            for attr, label in (
                ("filament_type", "Filament"),
                ("layer_height", "Schichthöhe"),
            ):
                value = state.attributes.get(attr)
                if value not in (None, "", "unknown", "unavailable"):
                    parts.append(f"{label}: {value}")
        return "; ".join(parts)

    # -- main loop ---------------------------------------------------------------

    async def _sleep(self, seconds: float) -> None:
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=max(0.1, seconds))
        except TimeoutError:
            pass

    async def _run(self) -> None:
        self._last_prune = 0.0
        while True:
            try:
                now = asyncio.get_running_loop().time()
                if now - self._last_prune >= PRUNE_INTERVAL_SEC:
                    self._last_prune = now
                    await asyncio.to_thread(self.archive.prune)

                running = self._print_running()
                if running and self._print_id is None:
                    self._start_print()
                elif not running and self._print_id is not None:
                    self._end_print()

                if not running:
                    await self._sleep(GATE_POLL_SECONDS)
                    continue

                interval = float(
                    self.opt(CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL)
                )
                elapsed = now - self._last_check
                if not self._force_check and elapsed < interval:
                    await self._sleep(min(interval - elapsed, GATE_POLL_SECONDS))
                    continue

                self._force_check = False
                self._last_check = now
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - loop must survive
                LOGGER.exception("Pipeline-Fehler bei '%s': %s", self.printer_name, err)
                self._last_error = str(err)
                self._push()
                await self._sleep(GATE_POLL_SECONDS)

    def _start_print(self) -> None:
        self._print_id = archive_mod.utc_timestamp()
        self.engine.start_print()
        self._last_error = None
        LOGGER.info("'%s': Neuer Druck erkannt (ID %s)", self.printer_name, self._print_id)
        self._push()

    def _end_print(self) -> None:
        LOGGER.info("'%s': Druck beendet", self.printer_name)
        self._print_id = None
        self.engine.start_print()
        self._push()

    async def _cycle(self) -> None:
        frame = await self._grab_frame()
        if frame is None:
            self.grab_failures += 1
            self._push()
            return

        await asyncio.to_thread(self.archive.save_frame, frame)
        context = self._build_context()
        api_key = str(self.opt(CONF_API_KEY, "") or self.entry.data.get(CONF_API_KEY, ""))
        model = str(self.opt(CONF_MODEL, DEFAULT_MODEL))
        self.api_calls += 1
        try:
            result = await mistral_mod.analyze_frame(
                self._post_json,
                api_key=api_key,
                model=model,
                frame=frame,
                context=context,
            )
        except mistral_mod.AnalysisError as err:
            self._last_error = f"[{err.kind}] {err}"
            if err.kind == mistral_mod.KIND_API:
                self.api_failures += 1
            else:
                self.discarded += 1
                self.engine.stats.discarded_frames += 1
            LOGGER.warning("'%s': Frame verworfen (%s: %s)", self.printer_name, err.kind, err)
            self._push()
            return

        self._last_result = result
        self._last_error = None
        decision = self.engine.process(result)
        await asyncio.to_thread(
            self.archive.append_score,
            self._print_id or "noid",
            {
                "stringing_score": result.stringing_score,
                "spaghetti_score": result.spaghetti_score,
                "warping_score": result.warping_score,
                "layer_shift_score": result.layer_shift_score,
                "bed_adhesion_failure": result.bed_adhesion_failure,
                "observations": result.observations,
                "other_defects": list(result.other_defects),
            },
        )
        self._push(decision)

        if decision.spaghetti_event:
            await self._notify_critical(result)
            if bool(self.opt(CONF_AUTO_PAUSE, False)) and not decision.muted:
                try:
                    await self.async_pause_print()
                except HomeAssistantError:
                    pass
        elif decision.layer_shift_event:
            await self._notify_layer_shift(result)
            if bool(self.opt(CONF_AUTO_PAUSE, False)) and not decision.muted:
                try:
                    await self.async_pause_print()
                except HomeAssistantError:
                    pass
        elif decision.warping_event:
            await self._notify_warping(result)
        elif decision.stringing_event:
            await self._notify_stringing(result)

    # -- frame sources ------------------------------------------------------------

    async def _grab_frame(self) -> bytes | None:
        camera_entity = self.opt(CONF_CAMERA_ENTITY, "")
        if camera_entity:
            try:
                from homeassistant.components.camera import async_get_image
            except ImportError as err:
                self._last_error = f"Kamera-Integration nicht verfügbar: {err}"
                LOGGER.error("'%s': %s", self.printer_name, self._last_error)
                return None
            try:
                image = await async_get_image(self.hass, camera_entity, timeout=10)
            except (HomeAssistantError, asyncio.TimeoutError) as err:
                self._last_error = f"Kamera-Snapshot fehlgeschlagen: {err}"
                LOGGER.warning("'%s': %s", self.printer_name, self._last_error)
                return None
            return image.content

        mjpeg_url = self.opt(CONF_MJPEG_URL, "")
        if mjpeg_url:
            session = async_get_clientsession(self.hass)
            try:
                return await grab_jpeg(session, mjpeg_url, timeout=10)
            except (MJPEGGrabError, asyncio.TimeoutError) as err:
                self._last_error = f"MJPEG-Grab fehlgeschlagen: {err}"
                LOGGER.warning("'%s': %s", self.printer_name, self._last_error)
                return None

        self._last_error = "Keine Bildquelle konfiguriert"
        LOGGER.error("'%s': keine Bildquelle (Kamera-Entity oder MJPEG-URL) konfiguriert", self.printer_name)
        return None

    async def _post_json(self, url: str, *, headers: dict, payload: dict) -> dict:
        session = async_get_clientsession(self.hass)
        # Reasoning models (mistral-large-4) can exceed 60s on a cold start.
        timeout = aiohttp.ClientTimeout(total=120)
        async with session.post(url, headers=headers, json=payload, timeout=timeout) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200:
                raise HomeAssistantError(
                    f"Mistral API HTTP {resp.status}: {data}"
                )
            return data

    # -- notifications ------------------------------------------------------------

    def _notify_services(self) -> list[tuple[str, str]]:
        """Resolve notify targets; empty/auto means all companion apps."""
        raw = str(self.opt(CONF_NOTIFY_SERVICES, DEFAULT_NOTIFY_SERVICES) or "").strip()
        services: list[tuple[str, str]] = []

        if not raw or raw.lower() == "auto":
            # Auto-detect all registered Companion App devices.
            notify = self.hass.services.async_services().get("notify", {})
            for name in sorted(notify):
                if name.startswith("mobile_app_"):
                    services.append(("notify", name))
            if not services:
                LOGGER.warning(
                    "'%s': kein notify.mobile_app_* Service gefunden - "
                    "Companion App verbunden? Ziel manuell in den Optionen setzen.",
                    self.printer_name,
                )
            return services

        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            domain, _, service = part.partition(".")
            if domain and service and self.hass.services.has_service(domain, service):
                services.append((domain, service))
            else:
                LOGGER.warning(
                    "'%s': Notify-Service '%s' nicht verfügbar", self.printer_name, part
                )
        return services

    async def _notify(self, *, title: str, message: str, data: dict[str, Any]) -> None:
        for domain, service in self._notify_services():
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {"title": title, "message": message, "data": data},
                    blocking=True,
                )
            except HomeAssistantError as err:
                LOGGER.error(
                    "'%s': Benachrichtigung über %s.%s fehlgeschlagen: %s",
                    self.printer_name, domain, service, err,
                )

    def _defects_line(self, result: AnalysisResult) -> str:
        """Append the other_defects list to a notification message if present."""
        if not result.other_defects:
            return ""
        return " Weitere Defekte: " + "; ".join(result.other_defects) + "."

    async def _notify_stringing(self, result: AnalysisResult) -> None:
        await self._notify(
            title=f"{self.printer_name}: Stringing erkannt (Score {result.stringing_score})",
            message=(
                f"Stringing-Score {result.stringing_score}. {result.observations}"
                f"{self._defects_line(result)}"
            ),
            data=self._base_notify_data(
                tag=f"{DOMAIN}_{self.entry.entry_id}_stringing",
                actions=[("ignore", "Ignorieren")],
            ),
        )

    async def _notify_warping(self, result: AnalysisResult) -> None:
        await self._notify(
            title=f"{self.printer_name}: Warping erkannt (Score {result.warping_score})",
            message=(
                f"Warping-Score {result.warping_score}. {result.observations}"
                f"{self._defects_line(result)}"
            ),
            data=self._base_notify_data(
                tag=f"{DOMAIN}_{self.entry.entry_id}_warping",
                actions=[("ignore", "Ignorieren")],
            ),
        )

    async def _notify_layer_shift(self, result: AnalysisResult) -> None:
        message = (
            f"Layer-Shift erkannt (Score {result.layer_shift_score})."
            f" {result.observations}{self._defects_line(result)}"
        )
        data = self._base_notify_data(
            tag=f"{DOMAIN}_{self.entry.entry_id}_layer_shift",
            actions=[("pause", "Pause"), ("ignore", "Ignorieren")],
        )
        data.update(
            {
                "channel": "alarm_stream",
                "ttl": 0,
                "priority": "high",
            }
        )
        await self._notify(
            title=f"{self.printer_name}: KRITISCH – Layer-Shift",
            message=message,
            data=data,
        )

    async def _notify_critical(self, result: AnalysisResult) -> None:
        message = (
            f"Spaghetti erkannt (Score {result.spaghetti_score}"
            + (", Teile vom Bett gelöst" if result.bed_adhesion_failure else "")
            + f"). {result.observations}{self._defects_line(result)}"
        )
        data = self._base_notify_data(
            tag=f"{DOMAIN}_{self.entry.entry_id}_critical",
            actions=[("pause", "Pause"), ("ignore", "Ignorieren")],
        )
        data.update(
            {
                "channel": "alarm_stream",
                "ttl": 0,
                "priority": "high",
            }
        )
        await self._notify(
            title=f"{self.printer_name}: KRITISCH – Druckfehler",
            message=message,
            data=data,
        )

    def _base_notify_data(self, *, tag: str, actions: list[tuple[str, str]]) -> dict[str, Any]:
        return {
            "tag": tag,
            "image": self.image_path,
            "actions": [
                {
                    "action": f"{DOMAIN}_{self.entry.entry_id}_{suffix}",
                    "title": title,
                }
                for suffix, title in actions
            ],
            "clickAction": "URI",
            "uri": self.deep_link,
        }

    # -- state push ----------------------------------------------------------------

    def _push(self, decision: Decision | None = None) -> None:
        data = self.coordinator.data
        result = self._last_result
        data[ATTR_STRINGING_SCORE] = result.stringing_score if result else None
        data[ATTR_SPAGHETTI_SCORE] = result.spaghetti_score if result else None
        data[ATTR_WARPING_SCORE] = result.warping_score if result else None
        data[ATTR_LAYER_SHIFT_SCORE] = result.layer_shift_score if result else None
        data[ATTR_OTHER_DEFECTS] = tuple(result.other_defects) if result else ()
        data[ATTR_BED_ADHESION_FAILURE] = (
            result.bed_adhesion_failure if result else None
        )
        data[ATTR_OBSERVATIONS] = result.observations if result else None
        data[ATTR_STRINGING_DETECTED] = (
            decision.stringing_detected
            if decision
            else self.engine.stringing_detected
        )
        data[ATTR_WARPING_DETECTED] = (
            decision.warping_detected
            if decision
            else self.engine.warping_detected
        )
        data[ATTR_LAYER_SHIFT_DETECTED] = (
            decision.layer_shift_detected
            if decision
            else self.engine.layer_shift_detected
        )
        data[ATTR_PRINT_FAILURE] = (
            decision.print_failure if decision else self.engine.print_failure
        )
        data[ATTR_MUTED] = self.engine.muted
        data[ATTR_API_CALLS] = self.api_calls
        data[ATTR_API_FAILURES] = self.api_failures
        data[ATTR_DISCARDED] = self.discarded
        data[ATTR_GRAB_FAILURES] = self.grab_failures
        data[ATTR_EVENTS] = (
            self.engine.stats.stringing_events
            + self.engine.stats.spaghetti_events
            + self.engine.stats.warping_events
            + self.engine.stats.layer_shift_events
        )
        data[ATTR_LAST_CHECK] = (
            datetime.now(timezone.utc).isoformat() if self._last_result else None
        )
        data[ATTR_PRINT_RUNNING] = self._print_id is not None
        data[ATTR_PRINT_ID] = self._print_id
        data[ATTR_LAST_ERROR] = self._last_error
        self.coordinator.async_set_updated_data(data)


PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
]
