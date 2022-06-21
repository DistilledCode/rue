import re

import praw
import spacy
from googlesearch import search

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
    targets = ("reddit,", "redditors,", "[serious]", "(serious)", "[nsfw]", "(nsfw)")
    for target in targets:
        title = title.removeprefix(target)
    return title.strip()


def edit_attributes(googled):
    """Edit atributes before fetching any information.

    Updating attributes after fethcing information doesnot update the result.

    Args:
        googled (_type_): submission instance to update
    """
    googled.comment_sort = "top"
    googled.comment_limit = 5
    googled.comments.replace_more(limit=0)  # flattening the comment tree


for asked in subreddit.stream.submissions(skip_existing=True):
    nlp_asked = nlp(asked.title)
    if len(nlp_asked) > 15:
        # average token lenght of top 1000 posts is < 14
        print(f"{'[SKipping long question]':-^40}")
        continue
    print(f"raw title : {asked.title}")
    query = f"site:www.reddit.com/r/askreddit {asked.title}"

    candidate_list = []
    for searched in search(query=query, num=5, stop=5, country="US"):
        match = re.search(pattern=pattern, string=searched)
        googled = reddit.submission(match.group(1))
        edit_attributes(googled=googled)
        similarity = calculate_similarity(asked.title, googled.title)

        if similarity > 0.95 and googled.score > 100:
            candidate_list.append(googled)

    if candidate_list:
        top_down = sorted(candidate_list, key=lambda x: x.score, reverse=True)
        for each in top_down:
            print("---*****----")
            for comment in each.comments:
                print(f"[{comment.score}] {comment.body[:10]}")
            print(f"[{each.score}] {each.title}")
    print("~=" * 20)


# TODO implement a similarity functon which discards punctuation & stop words
# TODO "if len(nlp_asked) > 15:" can be refined I think
