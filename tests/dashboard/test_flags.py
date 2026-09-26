from dashboard import flags
from evidence_engine.config import Settings


class _FakeSettings:
    def __init__(self, enabled: bool):
        self.dashboard_enabled = enabled


def test_dashboard_enabled_is_read_at_call_time_not_import_time(monkeypatch):
    """A test must be able to flip this between calls, the way tests/synthesis/
    test_service.py's autouse fixture patches _synthesis_enabled per-test. If
    dashboard_enabled() cached the settings object (or the flag) at import time,
    patching get_settings after import would have no effect on a later call.
    """
    monkeypatch.setattr(flags, "get_settings", lambda: _FakeSettings(True))
    assert flags.dashboard_enabled() is True

    monkeypatch.setattr(flags, "get_settings", lambda: _FakeSettings(False))
    assert flags.dashboard_enabled() is False


def test_dashboard_enabled_reads_the_real_settings_field(monkeypatch):
    # Not a fake this time: proves dashboard_enabled() is wired to the actual
    # Settings.dashboard_enabled field (evidence_engine/config.py), not a typo'd
    # attribute name that a fake object would happily satisfy either way.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DASHBOARD_ENABLED", "true")
    monkeypatch.setattr(flags, "get_settings", lambda: Settings())

    assert flags.dashboard_enabled() is True


def test_dashboard_enabled_defaults_to_false(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("DASHBOARD_ENABLED", raising=False)
    monkeypatch.setattr(flags, "get_settings", lambda: Settings())

    assert flags.dashboard_enabled() is False
