from configparser import NoSectionError

from praw import Reddit
from spacy import load

from rue.config import secrets
from rue.logger import logger

try:
    nlp = load("en_core_web_md")
except OSError as exception:
    logger.critical(str(exception), exc_info=True)
else:
    _model_name = f"{nlp.meta['lang']}_{nlp.meta['name']}"
    logger.debug(f"Loaded spaCy model {_model_name!r}")
try:
    reddit = Reddit(
        client_id=secrets["reddit"]["client_id"],
        client_secret=secrets["reddit"]["client_secret"],
        password=secrets["reddit"]["password"],
        user_agent=secrets["reddit"]["user_agent"],
        username=secrets["reddit"]["username"],
    )
except NoSectionError:
    # TODO We are using yaml, this handling is obsolete
    logger.critical("Failed `Reddit` initialization", exc_info=True)
else:
    logger.debug(f"Initialized {reddit.__class__} {reddit.user.me().name!r}")
