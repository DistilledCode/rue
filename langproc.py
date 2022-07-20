from requests import codes, post

from utils import nlp


def _spinbot(sentence: str, ignore: str) -> str:
    # character limit of 10000
    assert len(sentence) < 10000
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
