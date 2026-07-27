"""Reset de sequences do ETL ignora IDs textuais sem sequence."""

from scripts.etl_sqlite_to_postgres import _reset_postgres_id_sequences


class _Cursor:
    def __init__(self):
        self.calls = []
        self.sequence = None

    def execute(self, query, params=None):
        self.calls.append((str(query), params))
        if str(query).startswith("SELECT pg_get_serial_sequence"):
            self.sequence = (
                "numeric_id_seq" if params == ('"numeric"',) else None
            )

    def fetchone(self):
        return (self.sequence,)


class _Postgres:
    def __init__(self):
        self.test_cursor = _Cursor()

    def cursor(self):
        return self.test_cursor


def test_reset_sequences_skips_text_ids_without_sequence():
    pg = _Postgres()
    _reset_postgres_id_sequences(
        pg,
        ["numeric", "textual"],
        {"numeric": ["id"], "textual": ["id"]},
    )

    assert len(pg.test_cursor.calls) == 3
    assert any(
        params == ("numeric_id_seq",)
        for _, params in pg.test_cursor.calls
    )
    assert not any(
        params == ("textual_id_seq",)
        for _, params in pg.test_cursor.calls
    )
