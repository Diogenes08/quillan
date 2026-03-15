"""Subplot Register: defined sub-arcs and their intersection with the main plot."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
from quillan.templates import get_prompt




async def generate_subplot_register(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
) -> None:
    """Generate Subplot_Register.yaml."""
    from quillan.io import atomic_write

    out_path = paths.subplot_register(world, canon, series, story)
    paths.ensure(out_path)

    outline_path = paths.outline(world, canon, series, story)
    outline_text = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""

    brief_path = paths.creative_brief(world, canon, series, story)
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""

    input_dir = paths.story_input(world, canon, series, story)
    seed_files = list(input_dir.iterdir()) if input_dir.exists() else []
    idea_text = seed_files[0].read_text(encoding="utf-8") if seed_files else ""

    if llm.settings.has_api_keys and outline_text:
        user_prompt = get_prompt("subplots_user", world_dir=paths.world(world)).format(
            idea=idea_text[:1000],
            brief=brief_text[:1500],
            outline=outline_text[:4000],
        )
        raw = await llm.call("planning", get_prompt("subplots_system", world_dir=paths.world(world)), user_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        atomic_write(out_path, raw)
    else:
        stub: dict[str, list] = {"subplots": []}
        atomic_write(out_path, yaml.dump(stub, default_flow_style=False, allow_unicode=True))
