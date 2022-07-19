from requests import codes, post

from config import secrets


def _para_hugging(payload, api_token):
    model_id = "tuner007/pegasus_paraphrase"
    headers = {"Authorization": f"Bearer {api_token}"}
    api_url = f"https://api-inference.huggingface.co/models/{model_id}"
    response = post(api_url, headers=headers, json=payload)
    if response.status_code == codes.OK:
        return response.json()[0]["generated_text"]
    else:
        raise NotImplementedError


def _para_spinbot(payload):
    # character limit of 1000
    assert len(payload) < 1000
    url = "https://spinbot-back.azurewebsites.net/spin/rewrite-text"
    json = {"text": payload, "x_spin_cap_words": False, "x_words_to_skip": ""}

    response = post(url=url, json=json)
    if response.status_code == codes.OK:
        return response.json()
    else:
        raise NotImplementedError


def paraphrase(sentence: str, method: str) -> str:
    api_token = secrets["hugging_face"]["api_token"]
    if method == "hugging_face" and api_token is not None:
        return _para_hugging(sentence, api_token)
    else:
        return _para_spinbot(sentence)
