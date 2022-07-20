from contextlib import contextmanager
from typing import Generator

import psycopg2
import spacy
from psycopg2.extensions import cursor

from logger import logger

DB_SOURCE = {
    "url": None,
    "dbname": "arck",
    "user": "postgres",
    "password": "one",
}
MAX_FETCHED_IDS = 1000
# MAX_LOGS >2 or it will log _bisect() messages recursively forever
MAX_LOGS = 10**5
NEW_POST_LIM = 10
RISING_POST_LIM = 10
MIN_COM_SCORE_FETCH = 100
MIN_POST_SCORE = 500
DRY_RUN = False
MAX_POST_TOKEN_LEN = 20
MAX_COM_CHAR_LEN = 1000
MATURING_TIME = 3  # hours
MIN_COM_SCORE_SELF = 20
SCORE_TARGET = 1000
SLEEP_TIME_LIST = [5, 10, 15]
CLEAN_SLATE = True

try:
        nlp = spacy.load("en_core_web_md")
except OSError as exception:
        logger.critical(str(exception), exc_info=True)
else:
        model_name = f"{nlp.meta['lang']}_{nlp.meta['name']}"
        logger.debug(f"Loaded spaCy model {model_name!r}")



@contextmanager
def load_db(**kwargs) -> Generator[cursor, None, None]:
    # TODO error handling
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
