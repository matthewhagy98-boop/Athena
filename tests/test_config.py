import os

from evidence_engine.config import Settings


def test_settings_loads_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://u:p@localhost:5432/db"
    assert settings.anthropic_model == "claude-sonnet-4-6"
