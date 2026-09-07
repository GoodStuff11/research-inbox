from paper_finder import parse_arxiv_feed, fuzzy_title_match, verify_candidate, find_paper_data

ATTENTION_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <updated>2017-12-06T00:00:00Z</updated>
    <published>2017-06-12T17:57:34Z</published>
    <title>
   Attention Is All You Need
</title>
    <summary>The dominant sequence transduction models...</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <author><name>Niki Parmar</name></author>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
</feed>"""


def test_parse_arxiv_feed_extracts_title_id_authors_venue():
    entries = parse_arxiv_feed(ATTENTION_FEED)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["title"] == "Attention Is All You Need"
    assert entry["arxiv_id"] == "1706.03762"
    assert entry["authors"] == "Ashish Vaswani et al., 2017"
    assert entry["venue"] == "cs.CL"


def test_parse_arxiv_feed_empty_returns_empty_list():
    assert parse_arxiv_feed(EMPTY_FEED) == []


def test_fuzzy_title_match_true_for_identical_strings():
    assert fuzzy_title_match("Attention Is All You Need", "Attention Is All You Need")


def test_fuzzy_title_match_true_for_whitespace_and_case_differences():
    assert fuzzy_title_match("Attention Is All You Need", "  attention is all you need  ")


def test_fuzzy_title_match_false_for_unrelated_titles():
    assert not fuzzy_title_match("Attention Is All You Need", "Deep Residual Learning for Image Recognition")


def _fake_http_get(id_response=None, search_response=None):
    def http_get(url):
        if "id_list=" in url:
            return id_response if id_response is not None else EMPTY_FEED
        return search_response if search_response is not None else EMPTY_FEED
    return http_get


def test_verify_candidate_matches_by_arxiv_id():
    candidate = {"title": "Attention Is All You Need", "arxiv_id": "1706.03762"}
    http_get = _fake_http_get(id_response=ATTENTION_FEED)

    result = verify_candidate(candidate, http_get)

    assert result["arxiv_id"] == "1706.03762"
    assert result["authors"] == "Ashish Vaswani et al., 2017"


def test_verify_candidate_falls_back_to_title_search_when_id_missing():
    candidate = {"title": "Attention Is All You Need", "arxiv_id": None}
    http_get = _fake_http_get(search_response=ATTENTION_FEED)

    result = verify_candidate(candidate, http_get)

    assert result["arxiv_id"] == "1706.03762"


def test_verify_candidate_returns_none_when_no_match():
    candidate = {"title": "A Paper That Does Not Exist Anywhere", "arxiv_id": "9999.99999"}
    http_get = _fake_http_get(id_response=EMPTY_FEED, search_response=EMPTY_FEED)

    assert verify_candidate(candidate, http_get) is None


def test_verify_candidate_rejects_id_match_with_mismatched_title():
    candidate = {"title": "A Completely Different Paper Title", "arxiv_id": "1706.03762"}
    http_get = _fake_http_get(id_response=ATTENTION_FEED, search_response=EMPTY_FEED)

    assert verify_candidate(candidate, http_get) is None


GOOD_CANDIDATE_JSON = """{
  "title": "Attention Is All You Need",
  "authors": "Vaswani et al., 2017",
  "arxiv_id": "1706.03762",
  "venue": "NeurIPS 2017",
  "why": "It introduces the transformer architecture you asked about."
}"""

BAD_CANDIDATE_JSON = """{
  "title": "A Paper That Does Not Exist Anywhere",
  "authors": "Nobody",
  "arxiv_id": "9999.99999",
  "venue": "Unknown",
  "why": "This is a hallucinated paper."
}"""


def _queue_llm_call(responses):
    responses = list(responses)

    def llm_call(prompt):
        return responses.pop(0)

    return llm_call


def test_find_paper_data_succeeds_on_first_try():
    llm_call = _queue_llm_call([GOOD_CANDIDATE_JSON])
    http_get = _fake_http_get(id_response=ATTENTION_FEED)

    result = find_paper_data("what is attention?", llm_call, http_get)

    assert result["status"] == "found"
    assert result["paper"]["arxiv_id"] == "1706.03762"
    assert result["paper"]["authors"] == "Ashish Vaswani et al., 2017"
    assert result["paper"]["why"] == "It introduces the transformer architecture you asked about."


def test_find_paper_data_retries_once_after_failed_verification_then_succeeds():
    llm_call = _queue_llm_call([BAD_CANDIDATE_JSON, GOOD_CANDIDATE_JSON])

    def http_get(url):
        if "9999.99999" in url:
            return EMPTY_FEED
        if "id_list=" in url:
            return ATTENTION_FEED
        return EMPTY_FEED

    result = find_paper_data("what is attention?", llm_call, http_get)

    assert result["status"] == "found"
    assert result["paper"]["arxiv_id"] == "1706.03762"


def test_find_paper_data_returns_error_after_max_attempts_all_fail():
    llm_call = _queue_llm_call([BAD_CANDIDATE_JSON, BAD_CANDIDATE_JSON])
    http_get = _fake_http_get(id_response=EMPTY_FEED, search_response=EMPTY_FEED)

    result = find_paper_data("what is attention?", llm_call, http_get)

    assert result["status"] == "error"
    assert result["paper"] is None


def test_find_paper_data_treats_malformed_llm_json_as_a_failed_attempt():
    llm_call = _queue_llm_call(["not json at all", GOOD_CANDIDATE_JSON])
    http_get = _fake_http_get(id_response=ATTENTION_FEED)

    result = find_paper_data("what is attention?", llm_call, http_get)

    assert result["status"] == "found"
    assert result["paper"]["arxiv_id"] == "1706.03762"
