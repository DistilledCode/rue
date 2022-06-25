import re
import sqlite3
import time
from contextlib import contextmanager
from math import ceil
from typing import Generator

import praw
import spacy
from googlesearch import search
from praw.models.reddit.comment import Comment
from praw.models.reddit.submission import Submission

DB_SOURCE = "seen.db"
DB_MAX_ROWS = 21

pattern = r"comments\/([a-z0-9]{1,})\/"
nlp = spacy.load("en_core_web_lg")
reddit = praw.Reddit("arck")
print(reddit.user.me())
subreddit = reddit.subreddit("askreddit")


@contextmanager
def load_db(source: str) -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(source)
    yield con
    con.commit()
    con.close()


def update_fetched_ids(fetched_ids: set, postid: str):
    curr_time = time.time()
    with load_db(DB_SOURCE) as con:
        cur = con.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO seen
                VALUES (?,?);""",
            (postid, curr_time),
        )
    fetched_ids.add((postid, curr_time))
    return fetched_ids


def bisect_db() -> int:
    with load_db(DB_SOURCE) as con:
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
    return get_fetched_ids()


def get_fetched_ids() -> set:
    with load_db(DB_SOURCE) as con:
        cur = con.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS 
                    seen(
                        postid TEXT NOT NULL UNIQUE,
                        time_seen REAL NOT NULL
                        );
                    """
        )
        cur.execute("SELECT postid FROM seen;")
        return set(cur.fetchall())


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


def post_age(post) -> float:
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
    if comment.score < 50:
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


def validate_post(post, fetched_ids) -> dict[bool]:
    validation = {"is_unique": True, "is_valid": True}

    if (post.id,) in fetched_ids:
        validation["is_unique"] = False

    # average token lenght of top 1000 posts is < 14
    if len(nlp(post.title)) > 20:
        validation["is_valid"] = False
    return validation


print("\n@@@\nSTARTING NEW SESSION\n@@@")

fetched_ids: set = get_fetched_ids()
for asked in subreddit.new(limit=DB_MAX_ROWS):
    print("\n~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~\n")
    print(f"\nasked: {asked.title}")
    post: dict = validate_post(asked, fetched_ids)
    if post["is_unique"]:
        print(" \nUnique Post")
        fetched_ids = update_fetched_ids(fetched_ids, asked.id)
    if len(fetched_ids) == DB_MAX_ROWS:
        fetched_ids = bisect_db()
        print(f"\n{len(fetched_ids)=}")
        assert len(fetched_ids) == ceil(DB_MAX_ROWS / 2)
    if not post["is_unique"] or not post["is_valid"]:
        print(" \nInvalid Post")
        continue

    query = f"site:www.reddit.com/r/askreddit {asked.title}"
    candidates = []
    for searched in search(query=query, num=3, stop=3, country="US"):
        match = re.search(pattern=pattern, string=searched)
        googled = reddit.submission(match.group(1))
        update_preferences(googled)
        if post_age(googled) < 14:
            continue
        print(f"googled: {googled.title}\n")
        similarity = calculate_similarity(asked.title, googled.title)
        print(f"score={googled.score}; similar={round(similarity,4)}\n")
        if similarity > 0.95 and googled.score > 100:
            print("GOT ONE!\n")
            candidates.extend(comment for comment in googled.comments)
        else:
            print("Googled post didnt met criteria\n")
        print("************************************************\n")

    if candidates:
        valid_comments = []
        for comment in candidates:
            if validate_comment(comment):
                valid_comments.append(comment)

        valid_comments.sort(key=lambda x: x.score, reverse=True)
        for top_comment in valid_comments:
            print("@@@@@@@@@@@@@@@@\n")
            print(f"[{top_comment.score}] {top_comment.body}\n")
            print("@@@@@@@@@@@@@@@@\n")
    else:
        print("No googled post had >100 score or >0.95 similarity\n")


# TODO periodically look at 'rising' posts also as bot will sleep after commenting, missing out on a lot
# TODO warning when `DB_MAX_ROWS` is set too low (minimum 100 is advised)

# * replace all cur = con.cursor() with only con?
