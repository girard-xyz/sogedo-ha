"""Tests for the Sogedo API helper logic."""

import importlib.util
import sys
import types
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "sogedo"


def _load_with_const(modname, filename, pkg_name):
    """Load a package submodule, stubbing its `const` relative import."""
    cc = types.ModuleType("custom_components")
    cc.__path__ = []
    sys.modules.setdefault("custom_components", cc)

    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = []
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg

    const = types.ModuleType(f"{pkg_name}.const")
    const.__package__ = pkg_name
    sys.modules[f"{pkg_name}.const"] = const

    spec = importlib.util.spec_from_file_location(f"{pkg_name}.{modname}", filename)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = pkg_name
    sys.modules[f"{pkg_name}.{modname}"] = module
    spec.loader.exec_module(module)
    return module


api = _load_with_const("sogedo_api", BASE / "sogedo_api.py", "sogedo_api_pkg")
select_latest = api.select_latest


def test_select_latest_skips_unavailable_and_zero_days():
    entries = [
        {"isIndexValueAvailable": True, "consumptionValue": 0.3, "indexDate": "2026-08-16"},
        {"isIndexValueAvailable": True, "consumptionValue": 0.0, "indexDate": "2026-08-17"},
        {"isIndexValueAvailable": False, "consumptionValue": 0.0, "indexDate": "2026-08-18"},
        {"isIndexValueAvailable": False, "consumptionValue": 0.0, "indexDate": "2026-08-19"},
    ]
    assert select_latest(entries)["indexDate"] == "2026-08-16"


def test_select_latest_falls_back_to_last_entry():
    entries = [
        {"isIndexValueAvailable": False, "consumptionValue": 0.0, "indexDate": "2026-08-01"},
        {"isIndexValueAvailable": False, "consumptionValue": 0.0, "indexDate": "2026-08-02"},
    ]
    assert select_latest(entries)["indexDate"] == "2026-08-02"


def test_select_latest_empty():
    assert select_latest([]) is None
