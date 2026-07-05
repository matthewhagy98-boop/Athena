import logging

from evidence_engine.db.session import SessionLocal
from webapp.search_index import sync_search_index

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sync_search_index_script")


def main() -> None:
    session = SessionLocal()
    try:
        sync_search_index(session)
        session.commit()
        logger.info("Search index sync completed")
    except Exception:
        session.rollback()
        logger.exception("Search index sync failed")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
