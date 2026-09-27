import argparse
import logging

from evidence_engine.db.session import SessionLocal
from webapp.search_index import rebuild_search_index, sync_search_index

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sync_search_index_script")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "Reindex every paper from the papers table instead of processing new change "
            "events. Use this when index rows have been lost -- the incremental sync "
            "cannot repair that, because no future event names those papers again."
        ),
    )
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        if args.rebuild:
            indexed = rebuild_search_index(session)
            session.commit()
            logger.info("Search index rebuilt from source: %d papers", indexed)
        else:
            sync_search_index(session)
            session.commit()
            logger.info("Search index sync completed")
    except Exception:
        session.rollback()
        logger.exception("Search index %s failed", "rebuild" if args.rebuild else "sync")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
