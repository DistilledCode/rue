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
from rue.savedids import saved_ids
from rue.utils import age, sleepfor


def update_preferences(googled: Submission) -> None:
    googled.comment_sort = "top"
    googled.comment_limit = 50
    googled.comments.replace_more(limit=0)  # flattening the comment tree


def validate_comment(comment: Comment) -> bool:
    log_debug = partial(logger.debug, extra={"id": comment.id})
    if len(comment.body) > cfg.max_com_char_len:
        log_debug(f"validation: comment characters length > {cfg.max_com_char_len}")
        return False
    if not all(i in printable for i in comment.body):
        log_debug(f"validation: all characters are not printable")
        return False
    if comment.score < cfg.min_valid_com_score:
        log_debug(f"validation: comment score < {cfg.min_valid_com_score}")
        return False
    if comment.edited is not False:
        log_debug("validation: edited comment")
        return False
    if comment.stickied is True:
        log_debug(f"validation: stickied comment")
        return False
    if comment.author is None:
        log_debug("validation: deleted or removed comment (body unavailable)")
        return False
    if langproc.is_fpp(comment):
        log_debug(f"validation: comment contains first person perspective words")
        return False
    return True


def validate_post(post: Submission) -> bool:
    post.too_old = False
    log_info = partial(logger.info, extra={"id": post.id})
    if post.author is None:
        log_info("validation (core): deleted or removed post (attributes unavaialble)")
        return False
    if (post_age := age(post, unit="hour")) > cfg.max_post_age:
        post.too_old = True
        log_info(f"validation (core): post is too old ({round(post_age,3)} hours)")
        return False
    if post.num_comments > 200:
        log_info("validatio (core): too many comments, hard to get attention")
        return False
    if post.selftext:
        log_info("validation (core): post contain self text")
        return False
    if (post.id,) in saved_ids.ids:
        log_info("validation (core): duplicate post (saved earlier)")
        return False
    if len(nlp(post.title)) > cfg.max_post_token_len:
        log_info(f"validation (core): post token length > {cfg.max_post_token_len}")
        return False
    return True


def get_answers(question: Submission) -> list[Comment]:
    ans_candidates = google_query(question)
    answers: list[Comment] = []
    if not ans_candidates:
        return answers
    for comment in ans_candidates:
        if validate_comment(comment):
            logger.info("comment: valid as answer", extra={"id": comment.id})
            answers.append(comment)
        else:
            logger.debug("comment: invalid as answer", extra={"id": comment.id})
    answers.sort(key=lambda x: x.score, reverse=True)
    return answers


def google_query(question: Submission, sleep_time: int = 20) -> list[Comment]:
    query = f"site:www.reddit.com/r/{question.subreddit} {question.title}"
    pattern = r"comments\/([a-z0-9]{1,})\/"
    ans_candidates: list[Comment] = []
    try:
        for searched in search(query=query, num=5, stop=5, country="US"):
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
            similarity = langproc.calculate_similarity(question.title, googled.title)
            logger.debug(f"googled: score={googled.score}", extra={"id": googled.id})
            if similarity > 0.95 and googled.score > cfg.min_valid_post_score:
                logger.info(
                    "googled: post eligible for parsing comments",
                    extra={"id": googled.id},
                )
                ans_candidates.extend(comment for comment in googled.comments)
            else:
                logger.info(
                    "googled: post ineligible for parsing comments",
                    extra={"id": googled.id},
                )
    except HTTPError as exception:
        if exception.code == 429:
            logger.exception(f"googled: {exception.msg}", stack_info=True)
            logger.info(f"googled: rertying after {sleep_time} minutes")
            sleepfor(sleep_time * 60)
            # we might end up in an infinite loop
            return google_query(question, sleep_time + 5)
    return ans_candidates


def post_execution():
    user = reddit.user.me()
    del_poor_performers(user=user)
    check_shadowban(user=user)
    if cleanup(user=user):
        sys.exit()


def pre_execution():
    post_execution()
    user = reddit.user.me()
    comments = user.comments.new()
    try:
        latest = next(comments)
    except StopIteration:
        pass
    else:
        if age(latest, unit="minute") < (sl_time := min(cfg.sleep_time)):
            logger.info(f"Latest comment is too young. Sleeping for {sl_time} minutes")
            sleepfor(sl_time * 60)


def cleanup(user: Redditor) -> bool:
    total_karma = user.comment_karma + user.link_karma
    if cfg.acc_score_target is None or total_karma <= cfg.acc_score_target:
        return False
    if not cfg.clean_slate:
        logger.info(f"user: target reached. exiting. {total_karma=}")
        return True
    logger.info(f"user: target reached. removing content. {total_karma=}")

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

    cleanup_comments()
    logger.info("user: all content removed. exiting the program")
    return True


def check_ban(user: Redditor) -> bool:
    return user.is_suspended


def check_shadowban(user: Redditor) -> Optional[bool]:
    if check_ban(user):
        log_str = f"{str(user)!r} is banned. Exiting the program"
        logger.critical(log_str)
        sys.exit(log_str)
    for i in range(r := 30):
        # we get only 25 most recent comments, might use pushshift.io in future
        rsp = get(f"https://www.reddit.com/user/{str(user)}.json")
        if rsp.status_code != 200:
            if i % 5 == 0:  # logging every 5th failed attempt
                logger.debug(f"json: [{i}/{r} retries] {rsp.status_code} {rsp.reason}")
        else:
            logger.info(f"json: [{i}/{r} retries] {rsp.status_code} {rsp.reason}")
            break
    else:
        logger.warning("Retries exhuasted. Skipping shadowban check")
        return None
    req_comments = {
        child["data"]["id"]
        for child in rsp.json()["data"]["children"]
        if child["kind"] == "t1"
    }
    limit = min(len(req_comments), 100)
    praw_comments = {comment.id for comment in user.comments.new(limit=limit)}
    if diff := praw_comments.difference(req_comments):
        if diff == praw_comments:
            logger.critical(f"all {limit} comments are shadowbanned: {','.join(diff)}")
        elif len(diff) > 10:
            logger.warn(f"More than 10 comment are shadowbanned: {','.join(diff)}")
        else:
            for banned_id in diff:
                logger.warn(f"comment is shadowbanned", extra={"id": banned_id})
        return True
    else:
        logger.info(f"none of {len(praw_comments)} comments were shadowbanned")
        return False


def del_poor_performers(user: Redditor) -> None:
    all_comments = user.comments.new(limit=None)
    target_comments = (i for i in all_comments if i.score < cfg.min_self_com_score)
    for comment in target_comments:
        if (cma := age(comment, unit="hour")) > cfg.maturing_time or comment.score < 1:
            reddit.comment(comment.id).delete()
            logger.debug(
                f"deleted poor performing comment. ({comment.score}) ({cma} hrs old)",
                extra={"id": comment.id},
            )


def post_answer(question: Submission, answers: list[Comment]) -> bool:
    saved_ids.update(question.id)
    if not answers:
        logger.info("answer: no valid comments to post", extra={"id": question.id})
        return False
    answer = answers[0]
    run = "DRY_RUN" if cfg.dry_run else "LIVE_RUN"
    if cfg.dry_run:
        logger.info(
            f"answer:[{run}] [{answer.score}] {answer.body[:100]}...",
            extra={"id": "dummy_id"},
        )
        return True
    try:
        user = reddit.user.me()
        answered = question.reply(body=answer.body)
        logger.info(
            f"answer:[{run}] [{answer.score}] ({answer.id}) {answer.body[:100]}...",
            extra={"id": answered.id},
        )
        sleep_time = random.choice(cfg.sleep_time) * 60
        logger.info(f"answer: commented successfully. sleeping for {sleep_time}s")
        sleepfor(total_time=sleep_time)
        return True
    except prawcore.exceptions.Forbidden:
        logger.critical("answer: action forbidden. Checking acc ban.", exc_info=True)
        if check_ban(user=user):
            log_str = f"{user!r} is banned. Exiting the program."
            logger.critical(log_str, exc_info=True)
            sys.exit(log_str)
        else:
            logger.critical(f"{user!r} is not banned.")
            sleep_time = random.choice(cfg.sleep_time) * 60
            logger.info(f"asnwer: sleeping for {sleep_time} secs & retrying.")
            return post_answer(question=question, answers=answers)
    except RedditAPIException as exceptions:
        if sleep_time := reddit._handle_rate_limit(exceptions):
            logger.exception(f"answer: [RATELIMIT]: retrying after {sleep_time}s")
            sleepfor(total_time=sleep_time)
            return post_answer(question=question, answers=answers)
        for exception in exceptions.items:
            if exception.error_type == "BANNED_FROM_SUBREDDIT":
                log_str = f"answer: {user!r} banned from r/{question.subreddit}"
                logger.critical(log_str, exc_info=True)
                sys.exit(log_str)


def get_questions(stream: ListingGenerator) -> Generator[Submission, None, None]:
    validated_posts = 0
    _, sub, sort_by = stream.url.split("/")
    for question in stream:
        logger_info = partial(logger.info, extra={"id": question.id})
        logger_info(f"question #{stream.yielded}: {sub}[{sort_by}]: {question.title}")
        while len(saved_ids) > cfg.max_saved_ids:
            saved_ids.trim()
        is_valid = validate_post(question)
        saved_ids.update(question.id)
        if not is_valid:
            logger_info("validation (core): invalid. will be never answered")
            # if we sort by 'new' and encountered first post which is `too old`,
            # rest of the upcoming posts will also be `too old`
            if sort_by == "new" and question.too_old == True:
                logger_info(f"{sort_by=} post is 'too old'. Iteration will be futile")
                return
            continue
        logger_info("validation (core): valid")
        validated_posts += 1
        yield question
        if validated_posts > cfg.post_num_limit:
            return


def checkout_stream(stream: ListingGenerator) -> None:
    for question in get_questions(stream):
        answers: list[Comment] = get_answers(question)
        if post_answer(question, answers):
            return


if __name__ == "__main__":
    sub = "AskReddit"
    subreddit = reddit.subreddit(sub)
    pre_execution()
    while True:
        # TODO directly call ListingGenerator to generate stream
        streams = (subreddit.new(limit=None), subreddit.rising(limit=None))
        for stream in streams:
            checkout_stream(stream)
        post_execution()
