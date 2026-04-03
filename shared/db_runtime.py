import sqlite3


def to_db_query(query, *, use_postgres):
    if use_postgres:
        return query.replace("?", "%s")
    return query


class DBCursor:
    def __init__(self, cursor, *, use_postgres):
        self._cursor = cursor
        self._use_postgres = use_postgres

    def execute(self, query, params=None):
        sql = to_db_query(query, use_postgres=self._use_postgres)
        if params is None:
            return self._cursor.execute(sql)
        return self._cursor.execute(sql, params)

    def executemany(self, query, seq_of_params):
        sql = to_db_query(query, use_postgres=self._use_postgres)
        return self._cursor.executemany(sql, seq_of_params)

    def __iter__(self):
        return iter(self._cursor)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class DBConnection:
    def __init__(self, conn, *, use_postgres):
        self._conn = conn
        self._use_postgres = use_postgres

    def cursor(self):
        return DBCursor(self._conn.cursor(), use_postgres=self._use_postgres)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_dict(rows):
    return [dict(row) for row in rows]


def get_db_connection(
    *,
    use_postgres,
    database_url,
    sqlite_db_path,
    psycopg2_module=None,
    dict_cursor=None,
    psycopg_module=None,
    dict_row=None,
):
    if use_postgres:
        if psycopg2_module is not None:
            return DBConnection(
                psycopg2_module.connect(database_url, cursor_factory=dict_cursor),
                use_postgres=True,
            )
        if psycopg_module is not None:
            return DBConnection(
                psycopg_module.connect(database_url, row_factory=dict_row),
                use_postgres=True,
            )
        raise RuntimeError("DATABASE_URL is set but neither psycopg2 nor psycopg is installed.")

    conn = sqlite3.connect(sqlite_db_path)
    conn.row_factory = sqlite3.Row
    return DBConnection(conn, use_postgres=False)
