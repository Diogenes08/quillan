"""Conflict Map: antagonist pressure, core conflict, resolution arc."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
from quillan.templates import get_prompt




async def generate_conflict_map(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
) -> None:
    """Generate Conflict_Map.yaml."""
    from quillan.io import atomic_write

    out_path = paths.conflict_map(world, canon, series, story)
    paths.ensure(out_path)

    outline_path = paths.outline(world, canon, series, story)
    outline_text = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""

    brief_path = paths.creative_brief(world, canon, series, story)
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""

    input_dir = paths.story_input(world, canon, series, story)
    seed_files = list(input_dir.iterdir()) if input_dir.exists() else []
    idea_text = seed_files[0].read_text(encoding="utf-8") if seed_files else ""

    if llm.settings.has_api_keys and outline_text:
        user_prompt = get_prompt("conflicts_user", world_dir=paths.world(world)).format(
            idea=idea_text[:1000],
            brief=brief_text[:1500],
            outline=outline_text[:4000],
        )
        raw = await llm.call("planning", get_prompt("conflicts_system", world_dir=paths.world(world)), user_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        atomic_write(out_path, raw)
    else:
        stub = {
            "protagonist_goal": "TBD — derive from story idea",
            "antagonist": "TBD — identify main opposing force",
            "antagonist_goal": "TBD — what does the antagonist want",
            "core_conflict": "TBD — one sentence core dramatic tension",
            "conflict_type": "external",
            "resolution_arc": "TBD — how the conflict resolves",
            "antagonist_pressure": [],
            "stakes": "TBD — what is lost if the protagonist fails",
        }
        atomic_write(out_path, yaml.dump(stub, default_flow_style=False, allow_unicode=True))


def get_antagonist_pressure(beat_id: str, conflict_data: dict) -> str:
    """Return the antagonist pressure note for a specific beat, or empty string."""
    for entry in conflict_data.get("antagonist_pressure", []):
        if entry.get("beat_id") == beat_id:
            return str(entry.get("pressure", ""))
    return ""
