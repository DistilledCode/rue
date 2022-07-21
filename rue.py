import random
import re
import sys
from functools import partial
from string import printable
from typing import Generator, Optional
from urllib.error import HTTPError

import prawcore.exceptions
from googlesearch import search
from praw.exceptions import RedditAPIException
from praw.models.listing.generator import ListingGenerator
from praw.models.reddit.comment import Comment
from praw.models.reddit.redditor import Redditor
from praw.models.reddit.submission import Submission
from requests import get

from rue import langproc, nlp, reddit
from rue.config import cfg
from rue.logger import logger
from rue.savedids import SavedIds
from rue.utils import age, sleepfor


def update_preferences(googled: Submission) -> None:
    googled.comment_sort = "top"
    googled.comment_limit = 50
    googled.comments.replace_more(limit=0)  # flattening the comment tree


def validate_comment(comment: Comment) -> bool:
    log_debug = partial(logger.debug, extra={"id": comment.id})

    if len(comment.body) > cfg["max_com_char_len"]:
        log_debug(f'validation: comment characters length > {cfg["max_com_char_len"]}')
        return False
    else:
        log_debug(f'validation: comment characters length < {cfg["max_com_char_len"]}')

    if not all(i in printable for i in comment.body):
        return False

    if (score := comment.score) < cfg["min_valid_com_score"]:
        log_debug(
            f"validation: comment score < {cfg['min_valid_com_score']} (is {score})"
        )
        return False
    else:
        log_debug(
            f"validation: comment score > {cfg['min_valid_com_score']} (is {score})"
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
    if langproc.prp_ratio(comment) > 0.1:
        log_debug(f"validation: comment personal pronoun ratio > 0.1")
        return False
    else:
        log_debug(f"validation: comment personal pronoun ratio < 0.1")
    return True


def validate_post(post: Submission, saved_ids: SavedIds) -> dict:
    log_debug = partial(logger.debug, extra={"id": post.id})
    validation = {"is_unique": True, "is_valid": True}
    if post.author is None:
        validation["is_valid"] = False
        log_debug("validation: deleted or removed post (attrs unavaialble)")
    else:
        log_debug("validation: post attributes avaialble")

    if (post.id,) in saved_ids.ids:
        validation["is_unique"] = False
        log_debug("validation: duplicate post (saved earlier)")
    else:
        log_debug("validation: unique post")
    # average token lenght of top 1000 posts is < 14
    if len(nlp(post.title)) > cfg["max_post_token_len"]:
        validation["is_valid"] = False
        log_debug(f"validation: post token length > {cfg['max_post_token_len']}")
    else:
        log_debug(f"validation: post token length < {cfg['max_post_token_len']}")
    return validation


def get_answers(question: str) -> list:
    candidates = google_query(question)
    answers = []
    if candidates:
        for comment in candidates:
            if validate_comment(comment):
                logger.debug("comment: valid as answer", extra={"id": comment.id})
                answers.append(comment)
            else:
                logger.debug("comment: invalid as answer", extra={"id": comment.id})
        answers.sort(key=lambda x: x.score, reverse=True)
    return answers


def google_query(question: str) -> list[Comment]:
    query = f"site:www.reddit.com/r/askreddit {question}"
    pattern = r"comments\/([a-z0-9]{1,})\/"
    candidates: list[Comment] = []
    try:
        for searched in search(query=query, num=3, stop=3, country="US"):
            if (match := re.search(pattern, searched)) is not None:
                googled = reddit.submission(match.group(1))
            else:
                logger.debug("googled: result not from r/askreddit")
                continue
            update_preferences(googled)
            logger.debug(f"googled: {googled.title}", extra={"id": googled.id})
            if age(googled, unit="day") < 14:
                logger.debug("googled: post younger than 14 days")
                continue
            similarity = langproc.calculate_similarity(question, googled.title)
            logger.debug(
                f"googled: post score={googled.score}", extra={"id": googled.id}
            )
            if similarity > 0.95 and googled.score > cfg["min_valid_post_score"]:
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
            sleepfor(total_time=600)
            google_query(question)
    return candidates


def cleanup(user: Redditor) -> bool:
    if (tot_karma := user.comment_karma + user.link_karma) <= cfg["acc_score_target"]:
        return False
    if not cfg["clean_slate"]:
        logger.info(f"user: target reached. exiting. {tot_karma = }")
        return True

    logger.info(f"user: target reached. removing content. {tot_karma=}")

    def cleanup_comments():
        comments = user.comments.new(limit=None)
        for comment in comments:
            reddit.comment(comment.id).delete()
            logger.debug("user: comment deleted", extra={"id": comment.id})

        # `_exhausted` attr of ListingGenerator is True when it runs out
        #  of any more ids to return. But as it's a lazy object, we have
        #  to fetch any of it's attr first to get the real value.
        if comments._exhausted is True:
            return
        else:
            cleanup_comments()

    logger.info("user: all content removed. exiting the program")
    return True


def check_ban(user: Redditor) -> bool:
    return user.is_suspended


def check_shadowban(user: Redditor) -> Optional[bool]:
    if check_ban(user):
        log_str = f"{str(user)!r} is banned. Exiting the program."
        logger.critical(log_str)
        sys.exit(log_str)
    for i in range(1, retries := 31):
        resp = get(f"https://www.reddit.com/user/{str(user)}.json")
        if resp.status_code != 200:
            if i % 5 == 0:  # logging every 5th failed attempt
                logger.debug(f"[{i}/{retries}] {resp.status_code=} {resp.reason=}")
        else:
            logger.info(f"[{i}/{retries}] {resp.status_code=} {resp.reason=}")
            break
    else:
        logger.warn("Retries exhuasted. Skipping shadowban check.")
        return None
    req_comments = {
        child["data"]["id"]
        for child in resp.json()["data"]["children"]
        if child["kind"] == "t1"
    }
    limit = min(len(req_comments), 100)
    praw_comments = {comment.id for comment in user.comments.new(limit=limit)}
    if diff := praw_comments.difference(req_comments):
        if diff == praw_comments:
            logger.critical(f"all latest {limit} comments are shadowbanned")
        for id in diff:
            logger.error(f"comment is shadowbanned", extra={"id": id})
        return True
    else:
        return False


def del_poor_performers() -> None:
    all_comments = reddit.user.me().comments.new(limit=None)
    target_comments = (i for i in all_comments if i.score < cfg["min_self_com_score"])
    for comment in target_comments:
        if age(comment, unit="hour") > cfg["maturing_time"]:
            reddit.comment(comment.id).delete()
            logger.debug(
                f"deleted poor performing comment. ({comment.score})",
                extra={"id": comment.id},
            )


def post_answer(question: Submission, answers: list[Comment]) -> None:
    if not answers:
        logger.info("answer: no valid comments found to post as answer")
        return
    answer = answers[0]
    answer.body = langproc.paraphrase(answer.body)
    run = "DRY_RUN" if cfg["dry_run"] else "LIVE_RUN"
    if cfg["dry_run"]:
        logger.info(
            f"answer:{run =} [{answer.score}] {answer.body[:100]}...",
            extra={"id": "dummy_id"},
        )
        return
    try:
        answer_id = question.reply(body=answer.body)
        logger.info(
            f"answer:{run =} [{answer.score}] {answer.body[:100]}...",
            extra={"id": answer_id},
        )
        sleep_time = random.choice(cfg["sleep_time"]) * 60
        logger.info(f"answer: commented successfully. sleeping for {sleep_time}s")
        sleepfor(total_time=sleep_time)
    except prawcore.exceptions.Forbidden:
        logger.critical(
            "answer: action forbidden. Checking account ban.",
            exc_info=True,
        )
        if check_ban(user := reddit.user.me()):
            log_str = f"{str(user)!r} is banned. Exiting the program."
            logger.critical(log_str, exc_info=True)
            sys.exit(log_str)
        else:
            logger.critical(f"{str(user)} is not banned.")
            sleep_time = random.choice(cfg["sleep_time"]) * 60
            logger.info(f"asnwer: sleeping for {sleep_time} secs & retrying.")
            post_answer(question=question, answers=answers)
    except RedditAPIException as exceptions:
        if sleep_time := reddit._handle_rate_limit(exceptions):
            logger.exception(
                f"answer: [RATELIMIT]: sleeping for {sleep_time}s & retrying."
            )
            sleepfor(total_time=sleep_time)
            post_answer(question=question, answers=answers)
        for exception in exceptions.items:
            if exception.error_type == "BANNED_FROM_SUBREDDIT":
                usrname = str(reddit.user.me())
                log_str = f"answer: {usrname!r} banned from r/askreddit."
                logger.critical(log_str, exc_info=True)
                sys.exit(log_str)


def get_questions(stream: ListingGenerator) -> Generator[Submission, None, None]:
    saved_ids: SavedIds = SavedIds()
    for question in stream:
        logger_debug = partial(logger.debug, extra={"id": question.id})
        logger.info(f"question: {question.title}")
        post: dict = validate_post(question, saved_ids)
        if post["is_unique"]:
            saved_ids.update(question.id)
        while len(saved_ids) > cfg["max_saved_ids"]:
            saved_ids.bisect()
        if not post["is_unique"] or not post["is_valid"]:
            logger_debug("question: invalid for answering")
            continue
        else:
            logger_debug("question: valid for answering")

        yield question


def main() -> None:
    user = reddit.user.me()
    subreddit = reddit.subreddit("askreddit")
    streams = {
        "rising": subreddit.rising(limit=cfg["rising_post_lim"]),
        "new": subreddit.new(limit=cfg["new_post_lim"]),
    }
    for sort_type in streams:
        for question in get_questions(streams[sort_type]):
            answers: list[Comment] = get_answers(question.title)
            post_answer(question, answers)
    del_poor_performers()
    check_shadowban(user=user)
    if cleanup(user=user):
        sys.exit()


if __name__ == "__main__":
    main()
