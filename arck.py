import random
import re
import sys
import time
from configparser import NoSectionError
from functools import partial
from typing import Optional, Union
from urllib.error import HTTPError

import praw
import prawcore.exceptions
import requests
import spacy
from googlesearch import search
from praw.exceptions import RedditAPIException
from praw.models.listing.generator import ListingGenerator
from praw.models.reddit.comment import Comment
from praw.models.reddit.redditor import Redditor
from praw.models.reddit.submission import Submission

from fetched import FetchedIds
from logger import logger
from utils import *


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


def age(obj: Union[Submission, Comment], unit: str = "second") -> float:
    available_units = {
        "second": 1,
        "minute": 60,
        "hour": 60 * 60,
        "day": 60 * 60 * 24,
        "week": 60 * 60 * 24 * 7,
    }
    assert unit in available_units
    conversion = available_units[unit]
    return (time.time() - obj.created_utc) / conversion


def prp_ratio(comment: Comment) -> float:
    personal_pronouns = ("PRP", "PRP$")
    doc = nlp(comment.body)
    prp_count = sum(True for token in doc if token.tag_ in personal_pronouns)
    ratio = prp_count / len(doc)
    return ratio


def update_preferences(googled: Submission) -> None:
    googled.comment_sort = "top"
    googled.comment_limit = 20
    googled.comments.replace_more(limit=0)  # flattening the comment tree


def validate_comment(comment: Comment) -> bool:
    log_debug = partial(logger.debug, extra={"id": comment.id})
    if (score := comment.score) < MIN_COM_SCORE_FETCH:
        log_debug(
            f"validation: comment score < {MIN_COM_SCORE_FETCH} (is {score})"
        )
        return False
    else:
        log_debug(
            f"validation: comment score > {MIN_COM_SCORE_FETCH} (is {score})"
        )

    if comment.edited is not False:
        log_debug("validation: edited comment")
        return False
    else:
        log_debug("validation: unedited comment")

    if comment.stickied is True:
        log_debug(f"validation: stickied comment")
        return False
    else:
        log_debug(f"validation: non-stickied comment")

    if comment.author is None:
        log_debug("validation: deleted or removed comment (body unavailable)")
        return False
    else:
        log_debug("validation: body available")
    if prp_ratio(comment) > 0.1:
        log_debug(f"validation: comment personal pronoun ratio > 0.1")
        return False
    else:
        log_debug(f"validation: comment personal pronoun ratio < 0.1")
    return True


def validate_post(post: Submission, fetched_ids: FetchedIds) -> dict:
    log_debug = partial(logger.debug, extra={"id": post.id})
    validation = {"is_unique": True, "is_valid": True}
    if post.author is None:
        validation["is_valid"] = False
        log_debug("validation: deleted or removed post (title unavaialble)")
    else:
        log_debug("validation: post title avaialble")

    if (post.id,) in fetched_ids.ids:
        validation["is_unique"] = False
        log_debug("validation: duplicate post (fetched earlier)")
    else:
        log_debug("validation: unique post")
    # average token lenght of top 1000 posts is < 14
    if len(nlp(post.title)) > MAX_TOKEN_LEN:
        validation["is_valid"] = False
        log_debug(f"validation: post token length > {MAX_TOKEN_LEN}")
    else:
        log_debug(f"validation: post token length < {MAX_TOKEN_LEN}")
    return validation


def get_answers(question: str) -> list:
    candidates = google_query(question)
    answers = []
    if candidates:
        for comment in candidates:
            if validate_comment(comment):
                logger.debug(
                    "comment: valid as answer", extra={"id": comment.id}
                )
                answers.append(comment)
            else:
                logger.debug(
                    "comment: invalid as answer", extra={"id": comment.id}
                )
        answers.sort(key=lambda x: x.score, reverse=True)
    return answers


def google_query(question: str) -> list:
    query = f"site:www.reddit.com/r/askreddit {question}"
    pattern = r"comments\/([a-z0-9]{1,})\/"
    candidates: list = []
    try:
        for searched in search(query=query, num=3, stop=3, country="US"):
            if (match := re.search(pattern, searched)) is not None:
                googled = reddit.submission(match.group(1))
            else:
                logger.debug("googled: result not from r/askreddit")
                continue
            update_preferences(googled)
            logger.debug(f"googled: {googled.title}", extra={"id": googled.id})
            if age(googled, unit="day") < 14:  # 14 days
                logger.debug("googled: post younger than 14 days")
                continue
            similarity = calculate_similarity(question, googled.title)
            logger.debug(
                f"googled: post score={googled.score}", extra={"id": googled.id}
            )
            if similarity > 0.95 and googled.score > MIN_POST_SCORE:
                logger.debug(
                    "googled: post eligible for parsing comments",
                    extra={"id": googled.id},
                )
                candidates.extend(comment for comment in googled.comments)
            else:
                logger.debug(
                    "googled: post ineligible for parsing comments",
                    extra={"id": googled.id},
                )
    except HTTPError as exception:
        if exception.code == 429:
            logger.exception(f"googled: {exception.msg}", stack_info=True)
            logger.info("googled: sleeping for 10 minutes & then retrying")
            time.sleep(600)
            google_query(question)
        raise NotImplementedError
    return candidates


def check_ban(user: Redditor) -> bool:
    return user.is_suspended


def check_shadowban(user: Redditor) -> Optional[bool]:
    if check_ban(user):
        log_str = f"{str(user)!r} is banned. Exiting the program."
        logger.critical(log_str)
        sys.exit(log_str)
    response = requests.get(f"https://www.reddit.com/user/{str(user)}.json")
    if response.status_code == 200:
        req_comments = {
            child["data"]["id"]
            for child in response.json()["data"]["children"]
            if child["kind"] == "t1"
        }
    else:
        logger.warning(f"{response.status_code = }. skipping shadowban check")
        return None
    limit = min(response.json()["data"]["dist"], 100)
    praw_comments = {comment.id for comment in user.comments.new(limit=limit)}
    if diff := praw_comments.difference(req_comments):
        if diff == praw_comments:
            logger.critical(f"all latest {limit} comments are shadowbanned")
        for id in diff:
            logger.error(f"comment is shadowbanned", extra={"id": id})
        return True
    else:
        return False


def del_poor_performers():
    all_comments = reddit.user.me().comments.new(limit=None)
    target_comments = (i for i in all_comments if i.score < MIN_COM_SCORE_SELF)
    for comment in target_comments:
        if age(comment, unit="hour") > MATURING_TIME:
            reddit.comment(comment.id).delete()
            logger.debug(
                f"deleted comment for poor performance. ({comment.score})",
                extra={"id": comment.id},
            )


def post_answer(question: Submission, answers: list):
    if not answers:
        logger.info("answer: no valid comments found to post as answer")
        return

    answer = answers[0]
    run = "DRY_RUN" if DRY_RUN else "LIVE_RUN"
    if DRY_RUN:
        logger.info(
            f"answer:{run =} [{answer.score}] {answer.body[:100]}...",
            extra={"id": "dummy_id"},
        )
    else:
        try:
            answer_id = question.reply(body=answer)
            logger.info(
                f"answer:{run =} [{answer.score}] {answer.body[:100]}...",
                extra={"id": answer_id},
            )
            sleep_time = random.choice(SLEEP_TIME_LIST) * 60
            logger.info(
                f"answer: commented successfully. sleeping for {sleep_time}s"
            )
            time.sleep(sleep_time)
        except prawcore.exceptions.Forbidden:
            logger.critical(
                "answer: action forbidden. Checking account ban.",
                stack_info=True,
            )
            if check_ban(user := reddit.user.me()):
                log_str = f"{str(user)!r} is banned. Exiting the program."
                logger.critical(log_str, stack_info=True)
                sys.exit(log_str)
            else:
                logger.critical(f"{str(user)} is not banned.")
                sleep_time = random.choice(SLEEP_TIME_LIST) * 60
                logger.info(
                    f"asnwer: sleeping for {sleep_time} secs & retrying."
                )
                post_answer(question=question, answers=answers)
        except RedditAPIException as exceptions:
            if sleep_time := reddit._handle_rate_limit(exceptions):
                logger.exception(
                    f"answer: [RATELIMIT]: sleeping for {sleep_time} secs"
                )
                time.sleep(sleep_time)
                logger.info("answer: retrying replying")
                post_answer(question=question, answers=answers)
            for exception in exceptions.items:
                if exception.error_type == "BANNED_FROM_SUBREDDIT":
                    usrname = str(reddit.user.me())
                    log_str = f"answer: {usrname!r} banned from r/askreddit."
                    logger.critical(log_str, stack_info=True)
                    sys.exit(log_str)


def get_questions(stream: ListingGenerator):
    fetched_ids: FetchedIds = FetchedIds()
    for question in stream:
        logger_debug = partial(logger.debug, extra={"id": question.id})
        logger.info(f"question: {question.title}")
        post: dict = validate_post(question, fetched_ids)
        if post["is_unique"]:
            fetched_ids.update(question.id)
        while len(fetched_ids) > MAX_FETCHED_IDS:
            fetched_ids.bisect()
        if not post["is_unique"] or not post["is_valid"]:
            logger_debug("question: invalid for answering")
            continue
        else:
            logger_debug("question: valid for answering")

        yield question


def init_globals() -> None:
    global reddit, nlp
    try:
        reddit = praw.Reddit("arck")
    except NoSectionError:
        logger.critical("Failed `Reddit` initialization", stack_info=True)
    else:
        logger.debug(
            f"Initialized {reddit.__class__} {reddit.user.me().name!r}"
        )
    try:
        nlp = spacy.load("en_core_web_lg")
    except OSError as exception:
        logger.critical(str(exception), stack_info=True)
    else:
        model_name = f"{nlp.meta['lang']}_{nlp.meta['name']}"
        logger.debug(f"Loaded spaCy model {model_name!r}")


def main() -> None:
    init_globals()
    subreddit = reddit.subreddit("askreddit")
    streams = {
        "rising": subreddit.rising(limit=RISING_POST_LIM),
        "new": subreddit.new(limit=NEW_POST_LIM),
    }
    for sort_type in streams:
        for question in get_questions(streams[sort_type]):
            answers: list = get_answers(question.title)
            post_answer(question, answers)
    del_poor_performers()
    check_shadowban(reddit.user.me())


if __name__ == "__main__":
    main()

# TODO tesing
# TODO Check about `configparser`
# TODO job scheduling for checking bans
# TODO verbose
# TODO warning when `DB_MAX_ROWS` is set too low (minimum 100 is advised)
# TODO FEATURE: mutliple account instances
# TODO FEATURE: proxy server support
# TODO FEATURE: Shadowban checker
# TODO FEATURE: checking visibility of all (or all) comments after sometime

# * include other q/a based subreddits?
# * parse your comment replies and act accordingly?
# * -- seach for keywrods?
# * -- Check if comment contains a link leads to original post/comment?
