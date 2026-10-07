"""Constants for the Bambu Lab stringing detection integration."""
from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "bambu_stringing"
LOGGER = logging.getLogger(__package__)

# Config entry data (set in config flow)
CONF_API_KEY: Final = "api_key"
CONF_MODEL: Final = "mistral_model"
CONF_CAMERA_ENTITY: Final = "camera_entity"
CONF_MJPEG_URL: Final = "mjpeg_url"
CONF_PRINT_STATE_ENTITY: Final = "print_state_entity"
CONF_NOTIFY_SERVICES: Final = "notify_services"
CONF_BAMBU_DEVICE_ID: Final = "bambu_device_id"
CONF_MANUAL_CONTEXT: Final = "manual_context"
CONF_NAME: Final = "name"

# Options (section 6 of the spec)
CONF_CHECK_INTERVAL: Final = "check_interval_sec"
CONF_STRINGING_THRESHOLD: Final = "stringing_threshold"
CONF_STRINGING_STREAK: Final = "stringing_streak"
CONF_SPAGHETTI_THRESHOLD: Final = "spaghetti_threshold"
CONF_WARPING_THRESHOLD: Final = "warping_threshold"
CONF_LAYER_SHIFT_THRESHOLD: Final = "layer_shift_threshold"
CONF_COOLDOWN_MIN: Final = "stringing_cooldown_min"
CONF_AUTO_PAUSE: Final = "auto_pause"
CONF_RETENTION_DAYS: Final = "snapshot_retention_days"
CONF_RUNNING_STATES: Final = "running_states"
CONF_DEEP_LINK: Final = "deep_link"
CONF_PAUSE_SERVICE: Final = "pause_service"
CONF_RESUME_SERVICE: Final = "resume_service"
CONF_STOP_SERVICE: Final = "stop_service"

DEFAULT_MODEL: Final = "mistral-medium-latest"
DEFAULT_CHECK_INTERVAL: Final = 45
DEFAULT_STRINGING_THRESHOLD: Final = 55
DEFAULT_STRINGING_STREAK: Final = 3
DEFAULT_SPAGHETTI_THRESHOLD: Final = 70
DEFAULT_WARPING_THRESHOLD: Final = 60
DEFAULT_LAYER_SHIFT_THRESHOLD: Final = 70
DEFAULT_COOLDOWN_MIN: Final = 15
DEFAULT_AUTO_PAUSE: Final = False
DEFAULT_RETENTION_DAYS: Final = 14
DEFAULT_RUNNING_STATES: Final = "RUNNING,PAUSE"
DEFAULT_NOTIFY_SERVICES: Final = ""  # empty = auto-detect all companion apps
NOTIFY_TARGET_AUTO: Final = "auto"
DEFAULT_PAUSE_SERVICE: Final = "bambu_lab.pause_print"
DEFAULT_RESUME_SERVICE: Final = "bambu_lab.resume_print"
DEFAULT_STOP_SERVICE: Final = "bambu_lab.stop_print"
DEFAULT_DEEP_LINK_TEMPLATE: Final = "homeassistant://more-info/binary_sensor.{slug}_print_failure"

MIN_CHECK_INTERVAL: Final = 20
MAX_CHECK_INTERVAL: Final = 300
MIN_STRINGING_THRESHOLD: Final = 40
MAX_STRINGING_THRESHOLD: Final = 80
MIN_STRINGING_STREAK: Final = 1
MAX_STRINGING_STREAK: Final = 5
MIN_SPAGHETTI_THRESHOLD: Final = 50
MAX_SPAGHETTI_THRESHOLD: Final = 90
MIN_WARPING_THRESHOLD: Final = 40
MAX_WARPING_THRESHOLD: Final = 80
MIN_LAYER_SHIFT_THRESHOLD: Final = 50
MAX_LAYER_SHIFT_THRESHOLD: Final = 90
MIN_COOLDOWN_MIN: Final = 5
MAX_COOLDOWN_MIN: Final = 60
MIN_RETENTION_DAYS: Final = 1
MAX_RETENTION_DAYS: Final = 90

GATE_POLL_SECONDS: Final = 5.0

# Coordinator data keys
ATTR_STRINGING_SCORE: Final = "stringing_score"
ATTR_SPAGHETTI_SCORE: Final = "spaghetti_score"
ATTR_WARPING_SCORE: Final = "warping_score"
ATTR_LAYER_SHIFT_SCORE: Final = "layer_shift_score"
ATTR_OTHER_DEFECTS: Final = "other_defects"
ATTR_BED_ADHESION_FAILURE: Final = "bed_adhesion_failure"
ATTR_OBSERVATIONS: Final = "observations"
ATTR_STRINGING_DETECTED: Final = "stringing_detected"
ATTR_WARPING_DETECTED: Final = "warping_detected"
ATTR_LAYER_SHIFT_DETECTED: Final = "layer_shift_detected"
ATTR_PRINT_FAILURE: Final = "print_failure"
ATTR_MUTED: Final = "muted"
ATTR_API_CALLS: Final = "api_calls"
ATTR_API_FAILURES: Final = "api_failures"
ATTR_DISCARDED: Final = "discarded"
ATTR_GRAB_FAILURES: Final = "grab_failures"
ATTR_EVENTS: Final = "events"
ATTR_LAST_CHECK: Final = "last_check"
ATTR_PRINT_RUNNING: Final = "print_running"
ATTR_PRINT_ID: Final = "print_id"
ATTR_LAST_ERROR: Final = "last_error"

# Services
SERVICE_CHECK_NOW: Final = "check_now"
SERVICE_MUTE_FOR_PRINT: Final = "mute_for_print"
SERVICE_RESET_DETECTION: Final = "reset_detection"

# Notification action identifiers (f"{ACTION_PREFIX}{entry_id}_{suffix}")
ACTION_PREFIX: Final = "bambu_stringing_"
ACTION_SUFFIX_PAUSE: Final = "pause"
ACTION_SUFFIX_IGNORE: Final = "ignore"
