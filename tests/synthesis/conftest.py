# Registers the `users` table with Base.metadata for this test package.
#
# `SynthesisGeneration.user_id` is a ForeignKey to `users.id`, but `users` is declared
# in digest/models.py. synthesis/models.py deliberately does not import digest -- a
# package declaring a cross-package FK does not import the defining package here
# (webapp/models.py:36 FKs users.id the same way). That leaves the table's registration
# to whatever loaded first, which is fine for the app (alembic/env.py imports every
# package) and fine for the full suite, but not for this package on its own: collect
# tests/synthesis/ alone and SQLAlchemy raises NoReferencedTableError while configuring
# the mapper.
#
# tests/webapp gets away without this only by accident -- its test_models.py imports
# digest.profiles.create_user because it needs the helper, and the registration comes
# along for free. There is no such incidental import here, so it is made explicit.
#
# Do not delete this as an unused import. Removing it fails
# test_generation_row_round_trip whenever this file is run outside the full suite.
import digest.models  # noqa: F401
