"""Token estimation and sliding-window trimming for Quillan2."""

from __future__ import annotations

from pathlib import Path

_TIKTOKEN_AVAILABLE: bool | None = None
_ENCODING = None


def _get_encoding():
    global _TIKTOKEN_AVAILABLE, _ENCODING
    if _TIKTOKEN_AVAILABLE is None:
        try:
            import tiktoken
            _ENCODING = tiktoken.get_encoding("cl100k_base")
            _TIKTOKEN_AVAILABLE = True
        except Exception:  # ImportError if tiktoken not installed; other errors if encoding unavailable
            _TIKTOKEN_AVAILABLE = False
    return _ENCODING if _TIKTOKEN_AVAILABLE else None


def estimate_tokens(text: str) -> int:
    """Estimate token count for *text*.

    Uses tiktoken cl100k_base if available, else words * 1.3 heuristic.
    """
    enc = _get_encoding()
    if enc is not None:
        return len(enc.encode(text))
    # Fallback: word count * 1.3, with a char-based floor for whitespace-free text
    words = len(text.split())
    return max(int(words * 1.3), len(text) // 4)


def estimate_tokens_file(path: Path) -> int:
    """Estimate token count for the contents of *path*."""
    path = Path(path)
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    return estimate_tokens(text)


def trim_to_tokens(text: str, max_tokens: int) -> str:
    """Trim *text* to at most *max_tokens* using a 60/40 head/tail window.

    If trimming is needed, inserts "\\n\\n[...middle trimmed...]\\n\\n" between
    the head (60% of budget) and tail (40% of budget).

    Returns the original text unchanged if it already fits.
    """
    if max_tokens <= 0:
        return text

    if estimate_tokens(text) <= max_tokens:
        return text

    marker = "\n\n[...middle trimmed...]\n\n"
    marker_tokens = estimate_tokens(marker)
    budget = max_tokens - marker_tokens
    if budget <= 0:
        return text[:100]  # degenerate case

    head_tokens = int(budget * 0.60)
    tail_tokens = budget - head_tokens

    # Binary-search for char boundaries that satisfy token budgets
    head_text = _trim_chars_to_tokens(text, head_tokens, from_end=False)
    tail_text = _trim_chars_to_tokens(text, tail_tokens, from_end=True)

    return head_text + marker + tail_text


def _trim_chars_to_tokens(text: str, max_tok: int, from_end: bool) -> str:
    """Return a prefix (from_end=False) or suffix (from_end=True) of *text*
    that fits within *max_tok* tokens, using binary search."""
    n = len(text)
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[-mid:] if from_end else text[:mid]
        if estimate_tokens(candidate) <= max_tok:
            lo = mid
        else:
            hi = mid - 1
    if from_end:
        return text[-lo:] if lo else ""
    return text[:lo]


def trim_file_to_tokens(path: Path, max_tokens: int) -> None:
    """In-place trim of file at *path* to *max_tokens*."""
    from quillan.io import atomic_write

    path = Path(path)
    if not path.exists() or max_tokens <= 0:
        return

    text = path.read_text(encoding="utf-8", errors="replace")
    trimmed = trim_to_tokens(text, max_tokens)
    if trimmed != text:
        atomic_write(path, trimmed)
