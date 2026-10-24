"""Config flow (one printer per run) and options flow (spec 5.0/5.4/6)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_API_KEY,
    CONF_AUTO_PAUSE,
    CONF_BAMBU_DEVICE_ID,
    CONF_BED_TEMP,
    CONF_CAMERA_ENTITY,
    CONF_CHECK_INTERVAL,
    CONF_COOLDOWN_MIN,
    CONF_CRITICAL_ENSEMBLE_ENABLED,
    CONF_DEEP_LINK,
    CONF_ENSEMBLE_ENABLED,
    CONF_FILAMENT_TYPE,
    CONF_LAYER_SHIFT_THRESHOLD,
    CONF_MANUAL_CONTEXT,
    CONF_MJPEG_URL,
    CONF_MIN_CONFIDENCE,
    CONF_MODEL,
    CONF_NOTIFY_SERVICES,
    CONF_NOZZLE_TEMP,
    CONF_PAUSE_SERVICE,
    CONF_PLAUSIBILITY_RULES_ENABLED,
    CONF_PREPROCESS_ENABLED,
    CONF_PRINT_STATE_ENTITY,
    CONF_RESUME_SERVICE,
    CONF_RETENTION_DAYS,
    CONF_RUNNING_STATES,
    CONF_SMOOTHING_ALPHA,
    CONF_SMOOTHING_ENABLED,
    CONF_SPAGHETTI_THRESHOLD,
    CONF_STOP_SERVICE,
    CONF_STRINGING_STREAK,
    CONF_STRINGING_THRESHOLD,
    CONF_WARPING_THRESHOLD,
    NOTIFY_TARGET_AUTO,
    DEFAULT_AUTO_PAUSE,
    DEFAULT_BED_TEMP,
    DEFAULT_CHECK_INTERVAL,
    DEFAULT_COOLDOWN_MIN,
    DEFAULT_CRITICAL_ENSEMBLE_ENABLED,
    DEFAULT_DEEP_LINK_TEMPLATE,
    DEFAULT_ENSEMBLE_ENABLED,
    DEFAULT_FILAMENT_TYPE,
    DEFAULT_MODEL,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_NOZZLE_TEMP,
    DEFAULT_PAUSE_SERVICE,
    DEFAULT_PLAUSIBILITY_RULES_ENABLED,
    DEFAULT_PREPROCESS_ENABLED,
    DEFAULT_RESUME_SERVICE,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_RUNNING_STATES,
    DEFAULT_SMOOTHING_ENABLED,
    DEFAULT_STOP_SERVICE,
    DOMAIN,
    FILAMENT_TYPES,
    MAX_CHECK_INTERVAL,
    MAX_CONFIDENCE,
    MAX_COOLDOWN_MIN,
    MAX_LAYER_SHIFT_THRESHOLD,
    MAX_RETENTION_DAYS,
    MAX_SMOOTHING_ALPHA,
    MAX_SPAGHETTI_THRESHOLD,
    MAX_STRINGING_STREAK,
    MAX_STRINGING_THRESHOLD,
    MAX_WARPING_THRESHOLD,
    MIN_CHECK_INTERVAL,
    MIN_CONFIDENCE,
    MIN_COOLDOWN_MIN,
    MIN_LAYER_SHIFT_THRESHOLD,
    MIN_RETENTION_DAYS,
    MIN_SMOOTHING_ALPHA,
    MIN_SPAGHETTI_THRESHOLD,
    MIN_STRINGING_STREAK,
    MIN_STRINGING_THRESHOLD,
    MIN_WARPING_THRESHOLD,
)
from .runtime import benchmark_defaults, get_value


def _int_range(low: int, high: int) -> vol.All:
    return vol.All(vol.Coerce(int), vol.Range(min=low, max=high))


def _default(entry, key: str, fallback: Any, **fmt: str) -> Any:
    value = get_value(entry, key, fallback)
    if isinstance(value, str):
        return value.format(**fmt) if fmt else value
    return value


def _notify_selector(hass) -> selector.SelectSelector:
    """Dropdown: auto-detect (default) or one of the existing notify services."""
    options: list[dict[str, str]] = [
        {
            "value": NOTIFY_TARGET_AUTO,
            "label": "Automatisch (alle Companion-Apps)",
        }
    ]
    if hass is not None:
        services = hass.services.async_services().get("notify", {})
        for name, description in sorted(services.items()):
            label = f"notify.{name}"
            if isinstance(description, dict) and description.get("name"):
                label = f"{label} ({description['name']})"
            elif getattr(description, "name", None):
                label = f"{label} ({description.name})"
            options.append({"value": f"notify.{name}", "label": label})
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, mode="dropdown")
    )


class BambuStringingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: exactly one printer per flow run."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_CAMERA_ENTITY) and not user_input.get(
                CONF_MJPEG_URL
            ):
                errors["base"] = "no_frame_source"
            else:
                await self.async_set_unique_id(user_input[CONF_NAME].lower())
                self._abort_if_unique_id_configured()
                data = {
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_API_KEY: user_input[CONF_API_KEY],
                    CONF_MODEL: user_input.get(CONF_MODEL, DEFAULT_MODEL),
                    CONF_CAMERA_ENTITY: user_input.get(CONF_CAMERA_ENTITY, ""),
                    CONF_MJPEG_URL: user_input.get(CONF_MJPEG_URL, ""),
                    CONF_PRINT_STATE_ENTITY: user_input.get(
                        CONF_PRINT_STATE_ENTITY, ""
                    ),
                    CONF_NOTIFY_SERVICES: user_input.get(
                        CONF_NOTIFY_SERVICES, DEFAULT_NOTIFY_SERVICES
                    ),
                    CONF_BAMBU_DEVICE_ID: user_input.get(CONF_BAMBU_DEVICE_ID, ""),
                    CONF_MANUAL_CONTEXT: user_input.get(CONF_MANUAL_CONTEXT, ""),
                }
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=data
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="P1S"): str,
                vol.Required(CONF_API_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_MODEL, default=DEFAULT_MODEL): str,
                vol.Optional(CONF_CAMERA_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="camera")
                ),
                vol.Optional(CONF_MJPEG_URL, default=""): str,
                vol.Required(CONF_PRINT_STATE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_NOTIFY_SERVICES, default=NOTIFY_TARGET_AUTO
                ): _notify_selector(self.hass),
                vol.Optional(CONF_BAMBU_DEVICE_ID): selector.DeviceSelector(
                    selector.DeviceSelectorConfig(integration="bambu_lab")
                ),
                vol.Optional(CONF_MANUAL_CONTEXT, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> BambuStringingOptionsFlow:
        return BambuStringingOptionsFlow()


class BambuStringingOptionsFlow(OptionsFlow):
    """Adjustable detection parameters (spec section 6), applied without restart."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        slug = slugify(entry.data.get(CONF_NAME, entry.entry_id))
        # Benchmark-Schwellenwerte des konfigurierten Modells als Fallback —
        # explizit gesetzte Optionen gewinnen weiterhin (get_value prüft
        # options vor data vor Fallback).
        bench = benchmark_defaults(str(get_value(entry, CONF_MODEL, DEFAULT_MODEL)))
        if user_input is not None:
            # Leerer API-Key bedeutet "bestehenden Key behalten" – nicht als
            # leeren Options-Wert speichern, damit get_value auf entry.data
            # zurückfällt.
            if not user_input.get(CONF_API_KEY):
                user_input.pop(CONF_API_KEY, None)
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CHECK_INTERVAL,
                    default=_int_range(
                        MIN_CHECK_INTERVAL, MAX_CHECK_INTERVAL
                    )(get_value(entry, CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL)),
                ): _int_range(MIN_CHECK_INTERVAL, MAX_CHECK_INTERVAL),
                vol.Required(
                    CONF_STRINGING_THRESHOLD,
                    default=_int_range(
                        MIN_STRINGING_THRESHOLD, MAX_STRINGING_THRESHOLD
                    )(
                        get_value(
                            entry, CONF_STRINGING_THRESHOLD,
                            bench[CONF_STRINGING_THRESHOLD],
                        )
                    ),
                ): _int_range(
                    MIN_STRINGING_THRESHOLD, MAX_STRINGING_THRESHOLD
                ),
                vol.Required(
                    CONF_STRINGING_STREAK,
                    default=_int_range(MIN_STRINGING_STREAK, MAX_STRINGING_STREAK)(
                        get_value(
                            entry, CONF_STRINGING_STREAK, bench[CONF_STRINGING_STREAK]
                        )
                    ),
                ): _int_range(MIN_STRINGING_STREAK, MAX_STRINGING_STREAK),
                vol.Required(
                    CONF_SPAGHETTI_THRESHOLD,
                    default=_int_range(
                        MIN_SPAGHETTI_THRESHOLD, MAX_SPAGHETTI_THRESHOLD
                    )(
                        get_value(
                            entry, CONF_SPAGHETTI_THRESHOLD,
                            bench[CONF_SPAGHETTI_THRESHOLD],
                        )
                    ),
                ): _int_range(
                    MIN_SPAGHETTI_THRESHOLD, MAX_SPAGHETTI_THRESHOLD
                ),
                vol.Required(
                    CONF_WARPING_THRESHOLD,
                    default=_int_range(
                        MIN_WARPING_THRESHOLD, MAX_WARPING_THRESHOLD
                    )(
                        get_value(
                            entry,
                            CONF_WARPING_THRESHOLD,
                            bench[CONF_WARPING_THRESHOLD],
                        )
                    ),
                ): _int_range(MIN_WARPING_THRESHOLD, MAX_WARPING_THRESHOLD),
                vol.Required(
                    CONF_LAYER_SHIFT_THRESHOLD,
                    default=_int_range(
                        MIN_LAYER_SHIFT_THRESHOLD, MAX_LAYER_SHIFT_THRESHOLD
                    )(
                        get_value(
                            entry,
                            CONF_LAYER_SHIFT_THRESHOLD,
                            bench[CONF_LAYER_SHIFT_THRESHOLD],
                        )
                    ),
                ): _int_range(
                    MIN_LAYER_SHIFT_THRESHOLD, MAX_LAYER_SHIFT_THRESHOLD
                ),
                vol.Required(
                    CONF_COOLDOWN_MIN,
                    default=_int_range(MIN_COOLDOWN_MIN, MAX_COOLDOWN_MIN)(
                        get_value(entry, CONF_COOLDOWN_MIN, DEFAULT_COOLDOWN_MIN)
                    ),
                ): _int_range(MIN_COOLDOWN_MIN, MAX_COOLDOWN_MIN),
                vol.Required(
                    CONF_AUTO_PAUSE,
                    default=bool(
                        get_value(entry, CONF_AUTO_PAUSE, DEFAULT_AUTO_PAUSE)
                    ),
                ): bool,
                vol.Optional(
                    CONF_API_KEY,
                    description={
                        "suggested_value": ""
                    },
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(
                    CONF_MODEL,
                    default=str(get_value(entry, CONF_MODEL, DEFAULT_MODEL)),
                ): str,
                vol.Required(
                    CONF_RETENTION_DAYS,
                    default=_int_range(MIN_RETENTION_DAYS, MAX_RETENTION_DAYS)(
                        get_value(entry, CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)
                    ),
                ): _int_range(MIN_RETENTION_DAYS, MAX_RETENTION_DAYS),
                vol.Required(
                    CONF_RUNNING_STATES,
                    default=str(
                        get_value(entry, CONF_RUNNING_STATES, DEFAULT_RUNNING_STATES)
                    ),
                ): str,
                vol.Optional(
                    CONF_NOTIFY_SERVICES,
                    description={
                        "suggested_value": str(
                            get_value(entry, CONF_NOTIFY_SERVICES, "")
                            or NOTIFY_TARGET_AUTO
                        )
                    },
                ): _notify_selector(self.hass),
                vol.Required(
                    CONF_DEEP_LINK,
                    default=_default(
                        entry,
                        CONF_DEEP_LINK,
                        DEFAULT_DEEP_LINK_TEMPLATE,
                        slug=slug,
                    ),
                ): str,
                vol.Required(
                    CONF_PAUSE_SERVICE,
                    default=str(
                        get_value(entry, CONF_PAUSE_SERVICE, DEFAULT_PAUSE_SERVICE)
                    ),
                ): str,
                vol.Required(
                    CONF_RESUME_SERVICE,
                    default=str(
                        get_value(entry, CONF_RESUME_SERVICE, DEFAULT_RESUME_SERVICE)
                    ),
                ): str,
                vol.Required(
                    CONF_STOP_SERVICE,
                    default=str(
                        get_value(entry, CONF_STOP_SERVICE, DEFAULT_STOP_SERVICE)
                    ),
                ): str,
                vol.Optional(
                    CONF_MANUAL_CONTEXT,
                    default=str(get_value(entry, CONF_MANUAL_CONTEXT, "")),
                ): str,
                # Prompt v3.0: Preprocessing & Kontext-Features
                vol.Required(
                    CONF_PREPROCESS_ENABLED,
                    default=bool(
                        get_value(entry, CONF_PREPROCESS_ENABLED, DEFAULT_PREPROCESS_ENABLED)
                    ),
                ): bool,
                vol.Optional(
                    CONF_FILAMENT_TYPE,
                    default=str(
                        get_value(entry, CONF_FILAMENT_TYPE, DEFAULT_FILAMENT_TYPE)
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=FILAMENT_TYPES,
                        mode="dropdown",
                    )
                ),
                vol.Optional(
                    CONF_NOZZLE_TEMP,
                    default=int(
                        get_value(entry, CONF_NOZZLE_TEMP, DEFAULT_NOZZLE_TEMP)
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=350)),
                vol.Optional(
                    CONF_BED_TEMP,
                    default=int(
                        get_value(entry, CONF_BED_TEMP, DEFAULT_BED_TEMP)
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
                # Decision Engine v3.0: Confidence & Smoothing
                vol.Required(
                    CONF_MIN_CONFIDENCE,
                    default=float(
                        get_value(entry, CONF_MIN_CONFIDENCE, bench[CONF_MIN_CONFIDENCE])
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=MIN_CONFIDENCE, max=MAX_CONFIDENCE)),
                vol.Required(
                    CONF_SMOOTHING_ENABLED,
                    default=bool(
                        get_value(entry, CONF_SMOOTHING_ENABLED, DEFAULT_SMOOTHING_ENABLED)
                    ),
                ): bool,
                vol.Required(
                    CONF_SMOOTHING_ALPHA,
                    default=float(
                        get_value(entry, CONF_SMOOTHING_ALPHA, bench[CONF_SMOOTHING_ALPHA])
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=MIN_SMOOTHING_ALPHA, max=MAX_SMOOTHING_ALPHA)),
                # Ensemble method (zweistufige Analyse)
                vol.Required(
                    CONF_ENSEMBLE_ENABLED,
                    default=bool(
                        get_value(entry, CONF_ENSEMBLE_ENABLED, DEFAULT_ENSEMBLE_ENABLED)
                    ),
                ): bool,
                # Critical Ensemble (Benchmark-optimiert, v3.1)
                vol.Required(
                    CONF_CRITICAL_ENSEMBLE_ENABLED,
                    default=bool(
                        get_value(entry, CONF_CRITICAL_ENSEMBLE_ENABLED, DEFAULT_CRITICAL_ENSEMBLE_ENABLED)
                    ),
                ): bool,
                # Plausibility Rules (v3.2) — AUS per default, da sie Accuracy
                # verschlechtern können (Benchmark: glm 77.9% → 64.3%)
                vol.Required(
                    CONF_PLAUSIBILITY_RULES_ENABLED,
                    default=bool(
                        get_value(entry, CONF_PLAUSIBILITY_RULES_ENABLED, DEFAULT_PLAUSIBILITY_RULES_ENABLED)
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
