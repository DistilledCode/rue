import datetime
import logging
import re
import time
from contextlib import contextmanager
from functools import partial
from typing import Generator

import praw
import psycopg2
import spacy
from googlesearch import search
from praw.models.listing.generator import ListingGenerator
from praw.models.reddit.comment import Comment
from praw.models.reddit.submission import Submission
from psycopg2.extensions import cursor

DB_SOURCE = {
    "url": None,
    "dbname": "arck",
    "user": "postgres",
    "password": "one",
}
MAX_FETCHED_IDS = 5
# MAX_LOGS >2 is must or it will log _bisect() messages recursively infinitely
MAX_LOGS = 3
NEW_POST_LIMIT = 4
RISING_POST_LIMIT = 4
MIN_COMMENT_SCORE = 50
MIN_POST_SCORE = 100
DRY_RUN = True
MAX_TOKEN_LEN = 20


def get_logger() -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    frmt = "{asctime} {levelname:^10} {filename}:{lineno}  {message}"
    formatter = logging.Formatter(frmt, style="{")
    db_handler = DBLogHandler()
    db_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.addHandler(db_handler)
    return logger


class DBLogHandler(logging.Handler):
    def __init__(self) -> None:
        logging.Handler.__init__(self)
        with load_db(**DB_SOURCE) as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS 
                        log(
                            timestamp TIMESTAMP NOT NULL,
                            level TEXT NOT NULL,
                            filename TEXT NOT NULL,
                            funcname TEXT NOT NULL,
                            id TEXT,
                            message TEXT NOT NULL,
                            isexception BOOL NOT NULL,
                            traceback TEXT,
                            stackinfo TEXT
                            );
                        """
            )
        self._update_record_num()

    def handleError(self, record: logging.LogRecord) -> None:
        return super().handleError(record)

    def emit(self, record: logging.LogRecord) -> None:
        self.format(record=record)
        if record.exc_info is not None:
            isexception = True
            exc_traceback = "".join(i for i in record.exc_text)
        else:
            isexception = False
            exc_traceback = None

        id = getattr(record, "id", None)
        try:
            time_stamp = datetime.datetime.fromtimestamp(record.created)
            record_vals = (
                time_stamp,
                record.levelname,
                record.funcName,
                f"{record.filename}:{record.lineno}",
                record.funcName,
                id,
                record.message,
                isexception,
                exc_traceback,
                record.stack_info,
            )
        except Exception:
            self.handleError(record)
        with load_db(**DB_SOURCE) as cur:
            cur.execute(
                """INSERT INTO log
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s);
                """,
                record_vals,
            )
        self.record_num += 1
        while self.record_num > MAX_LOGS:
            self._bisect()

    def _update_record_num(self):
        with load_db(**DB_SOURCE) as cur:
            cur.execute("SELECT COUNT(*) FROM log;")
            self.record_num = cur.fetchall()[0][0]

    def _bisect(self):
        with load_db(**DB_SOURCE) as cur:
            cur.execute(
                """DELETE FROM log
                    WHERE timestamp IN (
                        SELECT timestamp
                        FROM log
                        ORDER BY timestamp
                        LIMIT (
                            SELECT COUNT(*)
                            FROM log
                        )/2
                    );
                """
            )
        self._update_record_num()
        # + 1 for this very record itself
        log_str = f"Bisected {self.__class__} to lenght {self.record_num + 1}"
        logger.debug(log_str)


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


class FetchedIds:
    def __init__(self):
        with load_db(**DB_SOURCE) as cur:
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
        logger.debug(f"Succesively initialized {self.__class__}")

    @property
    def ids(self):
        with load_db(**DB_SOURCE) as cur:
            cur.execute("SELECT postid FROM seen;")
            self._ids = set(cur.fetchall())
        return self._ids

    def update(self, postid: str):
        curr_time = datetime.datetime.now(tz=datetime.timezone.utc)
        with load_db(**DB_SOURCE) as cur:
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
        logger.debug(f"Added ({postid!r},{curr_time}) to {self.__class__}")

    def bisect(self):
        with load_db(**DB_SOURCE) as cur:
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


def calculate_similarity(asked_title: str, googled_title: str) -> float:
    asked_title = sanitize(asked_title)
    googled_title = sanitize(googled_title)
    nlp_asked = nlp(asked_title)
    nlp_googled = nlp(googled_title)
    logger.debug(f"Similarity: {(sim := nlp_asked.similarity(nlp_googled))}")
    return sim


def sanitize(title: str) -> str:
    title = title.lower()
    prefix_targets = ("reddit,", "redditors,", "reddit:")
    targets = ("[serious]", "[nsfw]", "(serious)", "(nsfw)")
    for prefix_target in prefix_targets:
        title = title.removeprefix(prefix_target)
    for target in targets:
        title = title.removeprefix(target)
        title = title.removesuffix(target)
    return title.strip()


def post_age(post: Submission) -> float:
    return (time.time() - post.created_utc) / (24 * 60 * 60)


def prp_ratio(comment: Comment) -> float:
    personal_pronouns = ("PRP", "PRP$")
    doc = nlp(comment.body)
    prp_count = sum(True for token in doc if token.tag_ in personal_pronouns)
    ratio = prp_count / len(doc)
    return ratio


def validate_comment(comment: Comment) -> bool:
    log_debug = partial(logger.debug, extra={"id": comment.id})
    if comment.score < MIN_COMMENT_SCORE:
        log_debug(f"validation: comment score < {MIN_COMMENT_SCORE}")
        return False
    else:
        logger.debug(f"Comment: score > {MIN_COMMENT_SCORE}")
    if comment.edited is not False:
        log_debug("validation: edited comment")
        return False
    else:
        logger.debug("Comment: unedited")
    if comment.stickied is True:
        log_debug(f"validation: stickied comment")
        return False
    else:
        logger.debug(f"Comment: not stickied")
    if comment.author is None:
        log_debug("validation: deleted or removed comment")
        return False
    if prp_ratio(comment) > 0.1:
        log_debug(f"validation: comment personal pronoun ratio > 0.1")
        return False
    return True


def update_preferences(googled: Submission) -> None:
    googled.comment_sort = "top"
    googled.comment_limit = 20
    googled.comments.replace_more(limit=0)  # flattening the comment tree


def print(text) -> None:
    with open("log.txt", "a", encoding="utf-8") as f:
        f.write(text)


def validate_post(post: Submission, fetchedids: FetchedIds) -> dict[bool]:
    log_debug = partial(logger.debug, extra={"id": post.id})
    validation = {"is_unique": True, "is_valid": True}
    if post.author is None:
        validation["is_valid"] = False
        log_debug("validation: deleted or removed post")
    if (post.id,) in fetchedids.ids:
        validation["is_unique"] = False
        log_debug("validation: duplicate post (fetched earlier)")
    else:
        log_debug("validation: unique post")
    # average token lenght of top 1000 posts is < 14
    if len(nlp(post.title)) > MAX_TOKEN_LEN:
        validation["is_valid"] = False
        log_debug(f"validation: post token length > {MAX_TOKEN_LEN}")
    return validation


def get_answers(question: str) -> list:
    candidates = google_query(question)
    answers = []
    if candidates:
        for comment in candidates:
            if validate_comment(comment):
                logger.info("comment: valid", extra={"id": comment.id})
                answers.append(comment)
            else:
                logger.info("comment: invalid", extra={"id": comment.id})
        answers.sort(key=lambda x: x.score, reverse=True)
    return answers


def google_query(question: str) -> list:
    query = f"site:www.reddit.com/r/askreddit {question}"
    pattern = r"comments\/([a-z0-9]{1,})\/"
    candidates = []
    for searched in search(query=query, num=3, stop=3, country="US"):
        if (match := re.search(pattern=pattern, string=searched)) is not None:
            googled = reddit.submission(match.group(1))
        else:
            logger.debug("Googled: result not from r/askreddit")
            continue
        update_preferences(googled)
        logger.info(f"googled: {googled.title}", extra={"id": googled.id})
        if post_age(googled) < 14:  # 14 days
            logger.debug("Googled: younger than 14 days")
            continue
        similarity = calculate_similarity(question, googled.title)
        logger.debug(
            f"googled: post score={googled.score}", extra={"id": googled.id}
        )
        if similarity > 0.95 and googled.score > MIN_POST_SCORE:
            logger.info(
                "googled: post eligible for parsing comments",
                extra={"id": googled.id},
            )
            candidates.extend(comment for comment in googled.comments)
        else:
            logger.info(
                "googled: post ineligible for parsing comments",
                extra={"id": googled.id},
            )
    return candidates


print("\n@@@\nSTARTING NEW SESSION\n@@@")


def main() -> None:
    init_globals()
    subreddit = reddit.subreddit("askreddit")
    streams = {
        "new": subreddit.new(limit=NEW_POST_LIMIT),
        "rising": subreddit.rising(limit=RISING_POST_LIMIT),
    }
    for sort_type in streams:
        for question in get_questions(streams[sort_type]):
            answers: list = get_answers(question.title)
            post_answer(question, answers)


def post_answer(question: Submission, answers: list):
    if answers:
        if DRY_RUN:
            for answer in answers:
                logger.info(
                    f"answer: [{answer.score}] {answer.body[:100]}...",
                    extra={"id": answer.id},
                )
        else:
            answer = answers[0]
            logger.info(
                f"answer: [{answer.score}] {answer.body[:100]}...",
                extra={"id": answer.id},
            )
            question.reply(answer)
    else:
        logger.info(
            "answer: no valid comments to post as answer",
            extra={"type": "answer"},
        )


def init_globals() -> None:
    global reddit, nlp, logger
    logger = get_logger()
    try:
        reddit = praw.Reddit("arck")
    except Exception:
        logger.critical("Failed `.Reddit` initialization", stack_info=True)
    else:
        username = reddit.user.me().name
        log_str = f"Successfully initialized {reddit.__class__} {username=}"
        logger.debug(log_str)
    try:
        nlp = spacy.load("en_core_web_lg")
    except Exception:
        logger.critical("Failed loading spaCy model", stack_info=True)
    else:
        log_var = f"{nlp.meta['lang']}_{nlp.meta['name']}"
        logger.debug(f"Successfully loaded spaCy model {log_var!r}")


def get_questions(stream: ListingGenerator):
    fetchedids: FetchedIds = FetchedIds()
    for question in stream:
        logger_info = partial(logger.info, extra={"id": question.id})
        logger_info(f"question: {question.title}")
        post: dict = validate_post(question, fetchedids)
        if post["is_unique"]:
            fetchedids.update(question.id)
        while len(fetchedids) > MAX_FETCHED_IDS:
            fetchedids.bisect()
        if not post["is_unique"] or not post["is_valid"]:
            logger_info("question: is invalid")
            continue
        else:
            logger_info("question: is valid")

        yield question


if __name__ == "__main__":
    main()

# TODO tesing
# TODO logging (partially done)
# TODO verbose
# TODO warning when `DB_MAX_ROWS` is set too low (minimum 100 is advised)
# TODO FEATURE: dry run
# TODO FEATURE: mutliple account instances
# TODO FEATURE: proxy server support
# TODO FEATURE: Shadowban checker
# TODO FEATURE: checking visibility of all (or all) comments after sometime

# * include other q/a based subreddits?
# * parse your comment replies and act accordingly?
# * -- seach for keywrods?
# * -- Check if comment contains a link leads to original post/comment?
