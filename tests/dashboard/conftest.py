# Registers the tables this package's foreign keys point at.
#
# TopicActivitySnapshot.topic_id references topics.id from evidence_engine, and the
# personal-summary tests touch users/interest_profiles from digest. dashboard/models.py
# deliberately does not import digest -- a package declaring a cross-package FK does not
# import the defining package here (webapp/models.py:36 FKs users.id the same way). That
# leaves registration to whatever imported first, which is fine for the app
# (alembic/env.py imports every package) and for the full suite, but not for this package
# alone: collect tests/dashboard/ by itself and SQLAlchemy raises NoReferencedTableError.
#
# Do not delete these as unused imports.
import digest.models  # noqa: F401
import evidence_engine.db.models  # noqa: F401
