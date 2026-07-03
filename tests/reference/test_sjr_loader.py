from evidence_engine.db.models import JournalSJR
from evidence_engine.reference.sjr_loader import load_sjr_csv


def test_load_sjr_csv_upserts_rows(db_session):
    count = load_sjr_csv(db_session, "tests/fixtures/sjr_sample.csv")
    db_session.flush()

    assert count == 2
    lancet = db_session.query(JournalSJR).filter_by(issn="0140-6736").one()
    assert lancet.sjr_score == 10.5
    assert lancet.year == 2024


def test_load_sjr_csv_is_idempotent(db_session):
    load_sjr_csv(db_session, "tests/fixtures/sjr_sample.csv")
    db_session.flush()
    count = load_sjr_csv(db_session, "tests/fixtures/sjr_sample.csv")
    db_session.flush()

    assert count == 2
    assert db_session.query(JournalSJR).count() == 2
