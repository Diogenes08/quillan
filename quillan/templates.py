"""Prompt template loader with per-story → per-world → built-in fallback chain.

All LLM prompts live as plain-text files in ``quillan/templates/``.  Users can
override any prompt without touching source code by placing a file with the same
name in their story or world directory:

  <story_dir>/templates/<name>.txt   — highest priority (per-story)
  <world_dir>/templates/<name>.txt   — medium priority  (per-world)
  quillan/templates/<name>.txt      — built-in fallback (always present)

Template files use Python ``str.format()`` substitution: ``{variable}`` for
interpolation, ``{{`` / ``}}`` for literal braces.  Callers call ``.format()``
on the returned string exactly as they would on a hardcoded string.

Example
-------
::

    from quillan.templates import get_prompt

    system = get_prompt("draft_system")
    user   = get_prompt(
        "draft_user",
        story_dir=paths.story(world, canon, series, story),
        world_dir=paths.world_dir(world),
    ).format(context=ctx, word_count=wc)
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger("quillan.templates")
_BUILTIN_DIR = Path(__file__).parent / "templates"


def get_prompt(
    name: str,
    *,
    story_dir: Path | None = None,
    world_dir: Path | None = None,
) -> str:
    """Return the prompt template string for *name*.

    Searches override directories before falling back to the built-in template.

    Parameters
    ----------
    name:
        Template name without extension (e.g. ``"draft_user"``).
    story_dir:
        Story root directory (``paths.story(world, canon, series, story)``).
        When provided, ``<story_dir>/templates/<name>.txt`` is checked first.
    world_dir:
        World root directory (``paths.world_dir(world)``).
        When provided, ``<world_dir>/templates/<name>.txt`` is checked second.

    Raises
    ------
    FileNotFoundError
        If no template is found (should never happen for built-in names).
    """
    candidates: list[Path] = []
    if story_dir is not None:
        candidates.append(story_dir / "templates" / f"{name}.txt")
    if world_dir is not None:
        candidates.append(world_dir / "templates" / f"{name}.txt")
    candidates.append(_BUILTIN_DIR / f"{name}.txt")

    for path in candidates:
        if path.exists():
            if path.parent != _BUILTIN_DIR:
                _log.debug("Using override template %r from %s", name, path)
            return path.read_text(encoding="utf-8")

    raise FileNotFoundError(
        f"Prompt template {name!r} not found. "
        f"Checked {len(candidates)} location(s): {[str(p) for p in candidates]}"
    )
