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
MAX_FETCHED_IDS = 1000
# MAX_LOGS >2 is must or it will log _bisect() messages recursively infinitely
MAX_LOGS = 10**5
NEW_POST_LIM = 10
RISING_POST_LIM = 10
MIN_COM_SCORE_FETCH = 100
MIN_POST_SCORE = 500
DRY_RUN = False
MAX_TOKEN_LEN = 20
MATURING_TIME = 3  # hours
MIN_COM_SCORE_SELF = 20
SCORE_TARGET = 1000
SLEEP_TIME_LIST = [5, 10, 15]


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
