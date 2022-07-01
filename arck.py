import re
import time
from functools import partial

import praw
import spacy
from googlesearch import search
from praw.models.listing.generator import ListingGenerator
from praw.models.reddit.comment import Comment
from praw.models.reddit.submission import Submission
from prawcore.exceptions import Forbidden

from fetchedids import FetchedIds
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


def post_age(post: Submission) -> float:
    return (time.time() - post.created_utc) / (24 * 60 * 60)


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
    if comment.score < MIN_COMMENT_SCORE:
        log_debug(f"validation: comment score < {MIN_COMMENT_SCORE}")
        return False
    if comment.edited is not False:
        log_debug("validation: edited comment")
        return False
    if comment.stickied is True:
        log_debug(f"validation: stickied comment")
        return False
    if comment.author is None:
        log_debug("validation: deleted or removed comment")
        return False
    if prp_ratio(comment) > 0.1:
        log_debug(f"validation: comment personal pronoun ratio > 0.1")
        return False
    return True


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
            logger.debug("googled: result not from r/askreddit")
            continue
        update_preferences(googled)
        logger.info(f"googled: {googled.title}", extra={"id": googled.id})
        if post_age(googled) < 14:  # 14 days
            logger.debug("googled: post younger than 14 days")
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


# question
# googled
# comment
# answer
# validation
