import datetime
from dataclasses import asdict

from rue.config import secrets
from rue.logger import logger
from rue.utils import load_db


class SavedIds:
    def __init__(self):
        with load_db(**asdict(secrets.postgres)) as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS
                        seen(
                            postid TEXT NOT NULL UNIQUE,
                            time_seen TIMESTAMP NOT NULL
                            );
                        """
            )
            cur.execute("SET TIME ZONE 'UTC';")
            cur.close()
        logger.debug(f"Successfully initialized {self.__class__}")

    @property
    def ids(self):
        with load_db(**asdict(secrets.postgres)) as cur:
            cur.execute("SELECT postid FROM seen;")
            self._ids = set(cur.fetchall())
        return self._ids

    def update(self, postid: str):
        curr_time = datetime.datetime.now(tz=datetime.timezone.utc)
        with load_db(**asdict(secrets.postgres)) as cur:
            cur.execute(
                """INSERT INTO seen
                    VALUES (%s,%s)
                    ON CONFLICT (postid)
                    DO UPDATE
                    SET time_seen = excluded.time_seen;
                """,
                (postid, curr_time),
            )
            cur.close()

    def bisect(self):
        with load_db(**asdict(secrets.postgres)) as cur:
            cur.execute(
                """DELETE FROM seen
                    WHERE postid IN (
                        SELECT postid
                        FROM seen
                        LIMIT (
                            SELECT COUNT(*)
                            FROM seen
                        )/2
                    );
                """
            )
            cur.close()
        logger.debug(f"Bisected {self.__class__} to lenght {self.__len__()}")

    def __len__(self):
        return len(self.ids)
