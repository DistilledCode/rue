from contextlib import contextmanager
from typing import Generator

import spacy
from psycopg2 import connect
from psycopg2.extensions import cursor

# from logger import logger

nlp = spacy.load("en_core_web_md")
# try:
# nlp = spacy.load("en_core_web_md")
# except OSError as exception:
# logger.critical(str(exception), exc_info=True)
# pass
# else:
# model_name = f"{nlp.meta['lang']}_{nlp.meta['name']}"
# logger.debug(f"Loaded spaCy model {model_name!r}")
# pass


@contextmanager
def load_db(**kwargs) -> Generator[cursor, None, None]:
    # TODO error handling
    if kwargs["url"] is not None:
        con = connect(kwargs["url"])
    else:
        con = connect(
            dbname=kwargs["dbname"],
            user=kwargs["user"],
            password=kwargs["password"],
        )
    cur = con.cursor()
    yield cur
    con.commit()
    cur.close()
    con.close()
