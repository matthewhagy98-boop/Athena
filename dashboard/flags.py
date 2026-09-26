from evidence_engine.config import get_settings


def dashboard_enabled() -> bool:
    """Read at call time, not import time, so a test can monkeypatch the setting.

    Mirrors synthesis/service.py's _synthesis_enabled, the established pattern for a
    feature gate in this codebase.
    """
    return get_settings().dashboard_enabled
