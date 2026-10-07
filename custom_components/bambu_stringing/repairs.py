"""Fix flow for the restart-required repair issue (version_check.py)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant


class RestartRequiredFixFlow(RepairsFlow):
    """Confirm and trigger a Home Assistant restart."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            # Not blocking: the flow must return before HA goes down.
            await self.hass.services.async_call(
                "homeassistant", "restart", blocking=False
            )
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow for the restart-required issue."""
    return RestartRequiredFixFlow()
