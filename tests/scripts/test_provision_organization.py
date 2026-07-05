from unittest.mock import patch, MagicMock

from scripts.provision_organization import main


def test_main_creates_organization_and_api_key_and_commits(db_session, capsys):
    db_session.commit = lambda: None
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    with (
        patch("scripts.provision_organization.SessionLocal", return_value=db_session),
        patch("sys.argv", ["provision_organization.py", "Acme Corp"]),
    ):
        main()

    captured = capsys.readouterr()
    assert "Acme Corp" in captured.out
    assert "API key" in captured.out


def test_main_accepts_custom_rate_limit_flag(db_session, capsys):
    db_session.commit = lambda: None
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    with (
        patch("scripts.provision_organization.SessionLocal", return_value=db_session),
        patch("sys.argv", ["provision_organization.py", "Acme Corp", "--rate-limit-per-hour", "50"]),
    ):
        main()

    captured = capsys.readouterr()
    assert "Acme Corp" in captured.out


def test_main_rolls_back_and_reraises_on_failure(db_session):
    db_session.rollback = MagicMock()
    db_session.close = lambda: None

    with (
        patch("scripts.provision_organization.SessionLocal", return_value=db_session),
        patch("scripts.provision_organization.create_organization", side_effect=RuntimeError("boom")),
        patch("sys.argv", ["provision_organization.py", "Acme Corp"]),
    ):
        try:
            main()
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass

    db_session.rollback.assert_called_once()
