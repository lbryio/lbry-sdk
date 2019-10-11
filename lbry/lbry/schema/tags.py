from typing import List
import re

MULTI_SPACE_RE = re.compile(r"\s{2,}")
WEIRD_CHARS_RE = re.compile(r"[#!~]")


def normalize_tag(tag: str):
    return MULTI_SPACE_RE.sub(' ', WEIRD_CHARS_RE.sub(' ', tag.lower().replace("'", ""))).strip()


def clean_tags(tags: List[str]):
    clean = []
    for idx, tag in enumerate(tags):
        norm_tag = normalize_tag(tag)
        if norm_tag and norm_tag not in clean[:idx]:
            clean.append(norm_tag)
    return clean
