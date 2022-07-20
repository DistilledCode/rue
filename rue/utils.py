from contextlib import contextmanager
from time import sleep, time
from typing import Generator, Union

from alive_progress import alive_bar
from praw.models.reddit.comment import Comment
from praw.models.reddit.submission import Submission
from psycopg2 import connect
from psycopg2.extensions import cursor


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


def sleepfor(total_time: int) -> None:
    sleep_per_loop = 1
    total = int(total_time / sleep_per_loop)
    bar = alive_bar(
        length=50,
        total=total,
        bar="classic2",
        spinner="classic",
        monitor=False,
        elapsed=False,
        stats_end=False,
        stats="waking up in {eta} (approx)",
    )
    with bar as bar:
        for _ in range(total):
            sleep(sleep_per_loop)
            bar()


def sanitize(title: str) -> str:
    title = title.lower()
    targets = (
        "[serious]",
        "[nsfw]",
        "(serious)",
        "(nsfw)",
        "reddit,",
        "redditors,",
        "reddit:",
    )
    for target in targets:
        title = title.removeprefix(target)
        title = title.removesuffix(target)
    return title.strip()


def age(obj: Union[Submission, Comment], unit: str = "second") -> float:
    conversion = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "week": 604800,
    }.get(unit, "second")
    return (time() - obj.created_utc) / conversion
