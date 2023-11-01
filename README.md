# rue
Automatically answers questions asked in r/askreddit using Google searches and SpaCy model.

Features:
* Deletes poor-performing comments
* Error Recovering
* Checking for shadowban on account
* Logs backed up to a local db
* Schedule the bot based on different time zone and hour
* Only using comments meeting a minimum threshold
* Filtering comments containing certain banned words

Log Snapshot:
```
2023-11-01 11:33:24,264  DEBUG   __init__.py:18   Loaded spaCy model 'en_core_web_sm'
2023-11-01 11:33:25,705  DEBUG   __init__.py:32   Initialized <class 'praw.reddit.Reddit'> '#Reddit-Username'
2023-11-01 11:33:25,789  DEBUG   savedids.py:24   Successfully initialized <class 'rue.savedids.SavedIds'>
2023-11-01 11:33:28,051  DEBUG   rue.py:233  deleted poor performing comment. (9)
2023-11-01 11:33:28,654  DEBUG   rue.py:233  deleted poor performing comment. (8)
2023-11-01 11:33:29,057  DEBUG   rue.py:197  json: [0/30 retries] 429 Too Many Requests
2023-11-01 11:33:30,139   INFO   rue.py:199  json: [2/30 retries] 200 OK
2023-11-01 11:33:30,715   INFO   rue.py:221  none of 25 fetched comments were shadowbanned
2023-11-01 11:33:32,866   INFO   rue.py:292  question #1: AskReddit[new]: Whose picture is in your wallet?
2023-11-01 11:33:33,135   INFO   rue.py:302  validation: valid
2023-11-01 11:33:36,573  ERROR   rue.py:125  googled: Too Many Requests
Traceback (most recent call last):
    (Logging Stack Info)
    logger.exception(f"googled: {exception.msg}", stack_info=True)
2023-11-01 11:33:36,639   INFO   rue.py:126  googled: retrying after 20 minutes
[#.................................................] - waking up in ~20:26 (approx)
User: '#Reddit-Username'; Karma: 61247; Last 5 comments score: [12, 6809, 17, 16, 20]
```
