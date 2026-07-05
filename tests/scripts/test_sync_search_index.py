from unittest.mock import patch

from scripts.sync_search_index import main


def test_main_commits_on_success(db_session):
    db_session.commit = lambda: None
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    with (
        patch("scripts.sync_search_index.SessionLocal", return_value=db_session),
        patch("scripts.sync_search_index.sync_search_index") as mock_sync,
    ):
        main()

    mock_sync.assert_called_once_with(db_session)


def test_main_rolls_back_and_reraises_on_failure(db_session):
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    with (
        patch("scripts.sync_search_index.SessionLocal", return_value=db_session),
        patch("scripts.sync_search_index.sync_search_index", side_effect=RuntimeError("boom")),
    ):
        try:
            main()
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass
