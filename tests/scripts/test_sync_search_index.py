from unittest.mock import patch

import pytest

from scripts.sync_search_index import main


def test_main_commits_on_success(db_session):
    db_session.commit = lambda: None
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    with (
        patch("scripts.sync_search_index.SessionLocal", return_value=db_session),
        patch("scripts.sync_search_index.sync_search_index") as mock_sync,
    ):
        main([])

    mock_sync.assert_called_once_with(db_session)


def test_main_rolls_back_and_reraises_on_failure(db_session):
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    with (
        patch("scripts.sync_search_index.SessionLocal", return_value=db_session),
        patch("scripts.sync_search_index.sync_search_index", side_effect=RuntimeError("boom")),
    ):
        try:
            main([])
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass


def test_rebuild_flag_runs_a_full_rebuild_and_not_the_incremental_sync(db_session):
    """The two paths are mutually exclusive on purpose.

    Running the incremental sync as well would advance the watermark past the rebuild's
    scan-start, which is the one thing the rebuild is careful not to do.
    """
    db_session.commit = lambda: None
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    with (
        patch("scripts.sync_search_index.SessionLocal", return_value=db_session),
        patch("scripts.sync_search_index.rebuild_search_index", return_value=7) as mock_rebuild,
        patch("scripts.sync_search_index.sync_search_index") as mock_sync,
    ):
        main(["--rebuild"])

    mock_rebuild.assert_called_once_with(db_session)
    mock_sync.assert_not_called()


def test_without_the_flag_the_default_stays_the_incremental_sync(db_session):
    """A rebuild is O(corpus) and this script runs on a schedule; it must stay opt-in."""
    db_session.commit = lambda: None
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    with (
        patch("scripts.sync_search_index.SessionLocal", return_value=db_session),
        patch("scripts.sync_search_index.rebuild_search_index") as mock_rebuild,
        patch("scripts.sync_search_index.sync_search_index") as mock_sync,
    ):
        main([])

    mock_sync.assert_called_once_with(db_session)
    mock_rebuild.assert_not_called()


def test_a_failed_rebuild_rolls_back_rather_than_leaving_a_partial_index(db_session):
    """`rebuild_search_index` raises on partial failure specifically so a caller can undo
    the partial write. The script has to actually take that option."""
    rolled_back = []
    db_session.rollback = lambda: rolled_back.append(True)
    db_session.close = lambda: None

    with (
        patch("scripts.sync_search_index.SessionLocal", return_value=db_session),
        patch(
            "scripts.sync_search_index.rebuild_search_index",
            side_effect=RuntimeError("Rebuild failed for 3 of 10 papers"),
        ),
    ):
        with pytest.raises(RuntimeError, match="Rebuild failed for 3 of 10"):
            main(["--rebuild"])

    assert rolled_back == [True]
