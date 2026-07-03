import csv

from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import JournalSJR


def load_sjr_csv(session: Session, csv_path: str) -> int:
    count = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            issn = row["Issn"].strip()
            year = int(row["Year"])
            existing = session.execute(
                select(JournalSJR).where(JournalSJR.issn == issn, JournalSJR.year == year)
            ).scalar_one_or_none()

            if existing:
                existing.sjr_score = float(row["SJR"])
                existing.journal_name = row["Title"]
            else:
                session.add(
                    JournalSJR(
                        issn=issn,
                        journal_name=row["Title"],
                        sjr_score=float(row["SJR"]),
                        year=year,
                    )
                )
            count += 1
    return count
