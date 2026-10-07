"""Load the HA-free core package under an alias so tests run without Home Assistant."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = ROOT / "custom_components" / "bambu_stringing" / "core"


def _load_core():
    if "bs_core" in sys.modules:
        return sys.modules["bs_core"]
    spec = importlib.util.spec_from_file_location(
        "bs_core", CORE_DIR / "__init__.py", submodule_search_locations=[str(CORE_DIR)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bs_core"] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_core()
