"""Paper matching: LLM candidate generation + arxiv verification, provider-agnostic."""

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

ARXIV_API = "http://export.arxiv.org/api/query"

PAPER_PROMPT = """\
A researcher logged this thought or question they want to explore:

"{thought}"

Find ONE specific, real, published academic paper that is the ideal starting point \
for understanding this. Prefer seminal or highly-cited papers. Respond ONLY with \
JSON (no prose, no markdown fences):
{{
  "title": "exact paper title",
  "authors": "First Author et al., Year",
  "arxiv_id": "XXXX.XXXXX or null",
  "venue": "conference or journal name, year",
  "why": "2-3 sentences explaining exactly why this paper answers their specific \
question — reference their words and connect it to what they want to understand"
}}"""

RETRY_PROMPT_SUFFIX = """

Your previous suggestion, "{bad_title}", could not be verified as a real paper on \
arxiv. Suggest a different, real, verifiable paper instead."""

ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def fuzzy_title_match(a, b, threshold=0.85):
    norm_a = re.sub(r"\s+", " ", a).strip().lower()
    norm_b = re.sub(r"\s+", " ", b).strip().lower()
    return SequenceMatcher(None, norm_a, norm_b).ratio() >= threshold


ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")


def extract_arxiv_id(text):
    match = ARXIV_ID_RE.search(text)
    return match.group(1) if match else None


def _format_authors(names):
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{names[0]} et al."


def parse_arxiv_feed(xml_text):
    root = ET.fromstring(xml_text)
    entries = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        title = (entry.findtext(f"{ATOM_NS}title") or "").strip()
        title = re.sub(r"\s+", " ", title)

        id_url = (entry.findtext(f"{ATOM_NS}id") or "").strip()
        arxiv_id = id_url.rsplit("/abs/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

        names = [
            (a.findtext(f"{ATOM_NS}name") or "").strip()
            for a in entry.findall(f"{ATOM_NS}author")
        ]
        published = (entry.findtext(f"{ATOM_NS}published") or "").strip()
        year = published[:4] if published else None
        authors = _format_authors(names)
        if authors and year:
            authors = f"{authors}, {year}"

        category_el = entry.find(f"{ARXIV_NS}primary_category")
        venue = category_el.get("term") if category_el is not None else None

        entries.append({
            "title": title,
            "arxiv_id": arxiv_id,
            "authors": authors,
            "venue": venue,
        })
    return entries


def verify_candidate(candidate, http_get):
    title = candidate.get("title") or ""
    arxiv_id = candidate.get("arxiv_id")

    if arxiv_id:
        xml_text = http_get(f"{ARXIV_API}?id_list={arxiv_id}")
        entries = parse_arxiv_feed(xml_text)
        if entries and fuzzy_title_match(entries[0]["title"], title):
            return entries[0]

    if title:
        query = urllib.parse.quote(f'ti:"{title}"')
        xml_text = http_get(f"{ARXIV_API}?search_query={query}&max_results=1")
        entries = parse_arxiv_feed(xml_text)
        if entries and fuzzy_title_match(entries[0]["title"], title):
            return entries[0]

    return None


def _parse_llm_json(raw):
    text = raw.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def find_paper_data(thought, llm_call, http_get, max_attempts=2):
    prompt = PAPER_PROMPT.format(thought=thought)

    for _ in range(max_attempts):
        candidate = None
        try:
            candidate = _parse_llm_json(llm_call(prompt))
            verified = verify_candidate(candidate, http_get)
        except Exception:
            verified = None

        if verified:
            return {
                "status": "found",
                "paper": {
                    "title": verified["title"],
                    "authors": verified["authors"],
                    "arxiv_id": verified["arxiv_id"],
                    "venue": verified["venue"],
                    "why": candidate.get("why"),
                },
            }

        bad_title = candidate.get("title") if candidate else "a paper"
        prompt = PAPER_PROMPT.format(thought=thought) + RETRY_PROMPT_SUFFIX.format(bad_title=bad_title)

    return {"status": "error", "paper": None}
