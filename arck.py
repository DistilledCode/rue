import re
import sqlite3
import time
from contextlib import contextmanager
from math import ceil
from typing import Generator

import praw
import spacy
from googlesearch import search
from praw.models.listing.generator import ListingGenerator
from praw.models.reddit.comment import Comment
from praw.models.reddit.submission import Submission

DB_SOURCE = "seen.db"
DB_MAX_ROWS = 30
NEW_POST_LIMIT = 10
RISING_POST_LIMIT = 10
MIN_COMMENT_SCORE = 50
MIN_POST_SCORE = 100


class FetchedIds:
    def __init__(self, source: str):
        self.source = source
        with self._load_db() as con:
            cur = con.cursor()
            cur.execute(
                """CREATE TABLE IF NOT EXISTS 
                        seen(
                            postid TEXT NOT NULL UNIQUE,
                            time_seen REAL NOT NULL
                            );
                        """
            )

    @contextmanager
    def _load_db(self) -> Generator[sqlite3.Connection, None, None]:
        con = sqlite3.connect(self.source)
        yield con
        con.commit()
        con.close()

    @property
    def ids(self):
        with self._load_db() as con:
            cur = con.cursor()
            cur.execute("SELECT postid FROM seen;")
            self._ids = set(cur.fetchall())
        return self._ids

    def update(self, postid: str):
        curr_time = time.time()
        with self._load_db() as con:
            cur = con.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO seen
                    VALUES (?,?);""",
                (postid, curr_time),
            )

    def __len__(self):
        return len(self.ids)

    def bisect(self):
        with self._load_db() as con:
            cur = con.cursor()
            cur.execute(
                """DELETE FROM seen 
                    WHERE postid IN (
                        SELECT postid
                        FROM seen 
                        ORDER BY time_seen 
                        LIMIT (
                            SELECT COUNT(*) 
                            FROM seen
                        )/2
                    );
                """
            )


def calculate_similarity(asked_title: str, googled_title: str) -> float:
    asked_title = sanitize(asked_title)
    googled_title = sanitize(googled_title)
    nlp_asked = nlp(asked_title)
    nlp_googled = nlp(googled_title)
    return nlp_asked.similarity(nlp_googled)


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
    if ratio > 0.1:
        print(f"\n[{ratio}] {comment.body}\n")
    return ratio


def validate_comment(comment: Comment) -> bool:
    if comment.score < MIN_COMMENT_SCORE:
        print("Low Karma!\n")
        return False
    if comment.edited is not False:
        print("edited!\n")
        return False
    if comment.stickied is True:
        print("Stickied!\n")
        return False
    if comment.author is None:
        print("deleted or removed\n")
        return False
    if prp_ratio(comment) > 0.1:
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
    validation = {"is_unique": True, "is_valid": True}
    if post.author is None:
        validation["is_valid"] = False
    if (post.id,) in fetchedids.ids:
        validation["is_unique"] = False
    # average token lenght of top 1000 posts is < 14
    if len(nlp(post.title)) > 20:
        validation["is_valid"] = False
    return validation


def get_answers(question: str) -> list:
    candidates = google_query(question)
    answers = []
    if candidates:
        for comment in candidates:
            if validate_comment(comment):
                answers.append(comment)
        answers.sort(key=lambda x: x.score, reverse=True)
    return answers


def google_query(question: str) -> list:
    query = f"site:www.reddit.com/r/askreddit {question}"
    pattern = r"comments\/([a-z0-9]{1,})\/"
    candidates = []
    for searched in search(query=query, num=3, stop=3, country="US"):
        print("************************************************\n")
        match = re.search(pattern=pattern, string=searched)
        googled = reddit.submission(match.group(1))
        update_preferences(googled)
        if post_age(googled) < 14:  # 14 days
            continue
        print(f"googled: {googled.title}\n")
        similarity = calculate_similarity(question, googled.title)
        print(f"score={googled.score}; similar={round(similarity,4)}\n")
        if similarity > 0.95 and googled.score > MIN_POST_SCORE:
            print("googled post eligible!\n")
            candidates.extend(comment for comment in googled.comments)
        else:
            print("googled post NOT eligible(similarity<0.95 or score<100)\n")
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
            answers = get_answers(question.title)
            post_answer(answers)


def post_answer(answers):
    if answers:
        for answer in answers:
            print("VALID ANSWER:\n")
            print(f"[{answer.score}] {answer.body}\n")
    else:
        print("**No valid answers found**\n")


def init_globals() -> None:
    global reddit, nlp
    reddit = praw.Reddit("arck")
    nlp = spacy.load("en_core_web_lg")


def get_questions(stream: ListingGenerator):
    fetchedids: FetchedIds = FetchedIds(DB_SOURCE)
    for question in stream:
        print("\n~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~\n")
        print(f"\nasked: {question.title}\n")
        post: dict = validate_post(question, fetchedids)
        if post["is_unique"]:
            print("Unique Post\n")
            fetchedids.update(question.id)
        if len(fetchedids) == DB_MAX_ROWS:
            fetchedids.bisect()
            print(f"{len(fetchedids)=}\n")
            assert len(fetchedids) == ceil(DB_MAX_ROWS / 2)
        if not post["is_unique"] or not post["is_valid"]:
            print("Invalid Post\n")
            continue
        yield question


if __name__ == "__main__":
    main()

# TODO tesing
# TODO logging
# TODO verbose
# TODO warning when `DB_MAX_ROWS` is set too low (minimum 100 is advised)
# TODO implement fethced_ids into a class. I have get, update. So it's better to make a class.
# TODO FEATURE: dry run
# TODO FEATURE: mutliple account instances
# TODO FEATURE: proxy server support
# TODO FEATURE: Shadowban checker
# TODO FEATURE: checking visibility of all (or all) comments after sometime

# * include other q/a based subreddits?
# * replace all cur = con.cursor() with only con?
# * parse your comment replies and act accordingly?
# * -- seach for keywrods?
# * -- Check if comment contains a link leads to original post/comment?
