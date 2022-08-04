import sys

from praw import Reddit
from prawcore import ResponseException
from spacy import load

from rue.config import secrets
from rue.logger import logger

try:
    nlp = load("en_core_web_md")
except OSError as exception:
    logger.critical(str(exception), exc_info=True)
    sys.exit()
else:
    _model_name = f"{nlp.meta['lang']}_{nlp.meta['name']}"
    logger.debug(f"Loaded spaCy model {_model_name!r}")
try:
    reddit = Reddit(
        client_id=secrets.reddit.client_id,
        client_secret=secrets.reddit.client_secret,
        password=secrets.reddit.password,
        user_agent=secrets.reddit.user_agent,
        username=secrets.reddit.username,
    )
    user = reddit.user.me()
except ResponseException as e:
    logger.critical(f"Failed `Reddit` initialization. {e.response}", exc_info=True)
    sys.exit()
else:
    logger.debug(f"Initialized {reddit.__class__} {user.name!r}")
