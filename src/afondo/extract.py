"""Conservative sentence candidate extraction, NOT an AI or factual verification model."""

import re


def extract_candidates(text: str, limit: int = 20) -> list[str]:
    """Identify potentially checkable sentences; intentionally no truth claims."""
    pieces = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    result: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        sentence = " ".join(piece.split()).strip()
        key = sentence.casefold()
        if 30 <= len(sentence) <= 600 and key not in seen:
            result.append(sentence)
            seen.add(key)
        if len(result) >= limit:
            break
    return result
