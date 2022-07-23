from praw.models.reddit.comment import Comment
from requests import codes, post

from rue import nlp
from rue.logger import logger
from rue.utils import sanitize


def _spinbot(sentence: str, ignore: str) -> str:
    url = "https://spinbot-back.azurewebsites.net/spin/rewrite-text"
    if ignore:
        json = {"text": sentence, "x_spin_cap_words": True, "x_words_to_skip": ignore}
    else:
        json = {"text": sentence, "x_spin_cap_words": False}
    response = post(url=url, json=json)
    if response.status_code == codes.OK:
        return response.json()
    else:
        return sentence


def paraphrase(sentence: str) -> str:
    ignore = ",".join(
        token.text for token in nlp(sentence) if token.pos_ in ("NOUN", "PROPN")
    )
    return _spinbot(sentence, ignore)


def calculate_similarity(asked_title: str, googled_title: str) -> float:
    asked_title = sanitize(asked_title)
    googled_title = sanitize(googled_title)
    nlp_asked = nlp(asked_title)
    nlp_googled = nlp(googled_title)
    logger.debug(f"Similarity: {(similarity := nlp_asked.similarity(nlp_googled))}")
    return similarity


def prp_ratio(comment: Comment) -> float:
    personal_pronouns = ("PRP", "PRP$")
    doc = nlp(comment.body)
    prp_count = sum(True for token in doc if token.tag_ in personal_pronouns)
    return prp_count / len(doc)
