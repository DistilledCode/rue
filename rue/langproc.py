from praw.models.reddit.comment import Comment

from rue import nlp
from rue.logger import logger
from rue.utils import sanitize


def calculate_similarity(asked_title: str, googled_title: str) -> float:
    asked_title = sanitize(asked_title)
    googled_title = sanitize(googled_title)
    nlp_asked = nlp(asked_title)
    nlp_googled = nlp(googled_title)
    logger.debug(f"Similarity: {(similarity := nlp_asked.similarity(nlp_googled))}")
    return similarity


def contains_datetime(comment: Comment) -> bool:
    return any(token.ent_type_ in ("DATE", "TIME") for token in nlp(comment.body))


def contains_first_person(comment: Comment) -> bool:
    fp = (
        "i",
        "me",
        "my",
        "mine",
        "we",
        "us",
        "our",
        "ours",
        "myself",
        "ourselves",
    )
    doc = nlp(comment.body)
    return any(token.lemma_.lower() in fp for token in doc if token.pos_ == "PRON")
