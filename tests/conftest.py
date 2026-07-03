import pytest
from sqlalchemy import text

from evidence_engine.db.session import engine


@pytest.fixture
def db_connection():
    with engine.connect() as conn:
        yield conn
