from sqlalchemy import text


def test_can_connect_to_database(db_connection):
    result = db_connection.execute(text("SELECT 1"))
    assert result.scalar() == 1
