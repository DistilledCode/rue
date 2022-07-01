from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extensions import cursor

DB_SOURCE = {
    "url": None,
    "dbname": "arck",
    "user": "postgres",
    "password": "one",
}
MAX_FETCHED_IDS = 100
# MAX_LOGS >2 is must or it will log _bisect() messages recursively infinitely
MAX_LOGS = 10000
NEW_POST_LIMIT = 6
RISING_POST_LIMIT = 6
MIN_COMMENT_SCORE = 50
MIN_POST_SCORE = 100
DRY_RUN = True
MAX_TOKEN_LEN = 20


@contextmanager
def load_db(**kwargs) -> Generator[cursor, None, None]:
    if kwargs["url"] is not None:
        con = psycopg2.connect(kwargs["url"])
    else:
        con = psycopg2.connect(
            dbname=kwargs["dbname"],
            user=kwargs["user"],
            password=kwargs["password"],
        )
    cur = con.cursor()
    yield cur
    con.commit()
    cur.close()
    con.close()
