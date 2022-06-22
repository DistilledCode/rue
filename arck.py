import re
import time

import praw
import spacy
from googlesearch import search
from praw.models.reddit.comment import Comment
from praw.models.reddit.submission import Submission

pattern = r"comments\/([a-z0-9]{1,})\/"
nlp = spacy.load("en_core_web_lg")
reddit = praw.Reddit("arck")
print(reddit.user.me())
subreddit = reddit.subreddit("askreddit")


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
        print(f"\n\n[{ratio}] {comment.body}\n\n")
    return ratio


def validate_comment(comment: Comment) -> bool:
    if comment.score < 50:
        print("Low Karma!\n\n")
        return False
    if comment.edited is not False:
        print("edited!\n\n")
        return False
    if comment.stickied is True:
        print("Stickied!\n\n")
        return False
    if comment.author is None:
        print("deleted or removed\n\n")
        return False
    if prp_ratio(comment) > 0.1:
        return False

    return True


def update_preferences(googled: Submission) -> None:
    googled.comment_sort = "top"
    googled.comment_limit = 20
    googled.comments.replace_more(limit=0)  # flattening the comment tree


def print(text) -> None:
    with open("log.txt", "a") as f:
        f.write(text)


print(f"STARTING NEW SESSION\n\n")
for asked in subreddit.stream.submissions(skip_existing=True):
    # average token lenght of top 1000 posts is < 14
    if len(nlp(asked.title)) > 20:
        print(f"{'[SKipping long question]':-^40}\n\n")
        continue
    print("~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~====~=\n")
    print("~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~====~=\n")
    print("~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~====~=\n\n")
    print(f"asked:   {asked.title}\n\n")
    query = f"site:www.reddit.com/r/askreddit {asked.title}"
    candidates = []
    for searched in search(query=query, num=3, stop=3, country="US"):
        match = re.search(pattern=pattern, string=searched)
        googled = reddit.submission(match.group(1))
        update_preferences(googled)
        if post_age(googled) < 14:
            continue
        print(f"googled: {googled.title}\n\n")
        similarity = calculate_similarity(asked.title, googled.title)
        print(f"score={googled.score}; similar={round(similarity,4)}\n\n")
        if similarity > 0.95 and googled.score > 100:
            print("GOT ONE!\n\n")
            candidates.extend(comment for comment in googled.comments)
        else:
            print("Googled post didnt met criteria\n\n")
        print("************************************************\n\n")

    if candidates:
        valid_comments = []
        for comment in candidates:
            if validate_comment(comment):
                valid_comments.append(comment)

        valid_comments.sort(key=lambda x: x.score, reverse=True)
        for top_comment in valid_comments:
            print("@@@@@@@@@@@@@@@@\n\n")
            print(f"[{top_comment.score}] {top_comment.body}\n\n")
            print("@@@@@@@@@@@@@@@@\n\n")
    else:
        print("No googled post had >100 score or >0.95 similarity\n\n")


# TODO periodically look at 'rising' posts also as bot will sleep after commenting, missing out on a lot
# TODO implementing the above will also need to keep track of which posts have been visited
