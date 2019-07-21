from typing import List
import re

MULTI_SPACE_RE = re.compile(r"\s{2,}")
WEIRD_CHARS_RE = re.compile(r"[#!~]")


def normalize_tag(tag: str):
    return MULTI_SPACE_RE.sub(' ', WEIRD_CHARS_RE.sub(' ', tag.lower())).strip()


def clean_tags(tags: List[str]):
    return [tag for tag in set(normalize_tag(tag) for tag in tags) if tag]
