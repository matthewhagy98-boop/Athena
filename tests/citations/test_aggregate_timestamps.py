from datetime import datetime

from citations.aggregate import saved_search_velocity
from digest.profiles import create_user
from webapp.models import SavedSearch


def test_aggregate_computed_at_carries_an_explicit_utc_suffix(db_session):
    """The sibling of the read.py fix in b515b3a, which missed this call site.

    Naive timestamps have no offset, and JavaScript parses an offset-less date-time
    as LOCAL, shifting the value by the viewer's UTC offset. This endpoint's
    computed_at is rendered by the saved-search trend component, so without the
    suffix it would display a UTC instant as though it were local.
    """
    user = create_user(db_session, "aggts@example.com")
    saved = SavedSearch(user_id=user.id, name="Timestamp search", query_params={"q": "nothing"})
    db_session.add(saved)
    db_session.flush()

    result = saved_search_velocity(
        db_session, saved, weeks=12, now=datetime(2026, 8, 2, 5, 0, 0)
    )

    assert result["computed_at"] == "2026-08-02T05:00:00Z"


def test_aggregate_and_read_agree_on_timestamp_format(db_session):
    """Both modules serialize instants the same way.

    They drifted once: read.py was fixed and aggregate.py was not. This pins the
    invariant rather than the individual call site, so a future third module
    cannot quietly reintroduce the split.
    """
    from citations.read import iso_utc

    moment = datetime(2026, 8, 2, 5, 0, 0)
    user = create_user(db_session, "aggts2@example.com")
    saved = SavedSearch(user_id=user.id, name="Agreement search", query_params={"q": "nothing"})
    db_session.add(saved)
    db_session.flush()

    result = saved_search_velocity(db_session, saved, weeks=12, now=moment)

    assert result["computed_at"] == iso_utc(moment)
