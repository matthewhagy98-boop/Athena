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


def test_load_sjr_csv_skips_malformed_rows(db_session):
    count = load_sjr_csv(db_session, "tests/fixtures/sjr_sample_with_malformed_row.csv")
    db_session.flush()

    # Should load 2 valid rows and skip 1 malformed row
    assert count == 2
    assert db_session.query(JournalSJR).count() == 2

    # Verify the valid rows were loaded correctly
    lancet = db_session.query(JournalSJR).filter_by(issn="0140-6736").one()
    assert lancet.sjr_score == 10.5
    assert lancet.year == 2024

    jacc = db_session.query(JournalSJR).filter_by(issn="0735-1097").one()
    assert jacc.sjr_score == 8.2
    assert jacc.year == 2024
    assert jacc.journal_name == "Journal of the American College of Cardiology"
