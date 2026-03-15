"""Character Arc Trajectories: per-character story-scale arc generation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
from quillan.templates import get_prompt




async def generate_character_arcs(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
) -> None:
    """Generate Character_Arcs.yaml."""
    from quillan.io import atomic_write

    out_path = paths.character_arcs(world, canon, series, story)
    paths.ensure(out_path)

    outline_path = paths.outline(world, canon, series, story)
    outline_text = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""

    brief_path = paths.creative_brief(world, canon, series, story)
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""

    input_dir = paths.story_input(world, canon, series, story)
    seed_files = list(input_dir.iterdir()) if input_dir.exists() else []
    idea_text = seed_files[0].read_text(encoding="utf-8") if seed_files else ""

    if llm.settings.has_api_keys and outline_text:
        user_prompt = get_prompt("character_arcs_user", world_dir=paths.world(world)).format(
            idea=idea_text[:1000],
            brief=brief_text[:1500],
            outline=outline_text[:4000],
        )
        raw = await llm.call("planning", get_prompt("character_arcs_system", world_dir=paths.world(world)), user_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        atomic_write(out_path, raw)
    else:
        stub = {
            "characters": [
                {
                    "name": "Protagonist",
                    "arc_type": "positive_change",
                    "starting_state": "TBD — fill in from story idea",
                    "ending_state": "TBD — fill in from story idea",
                    "motivation": "TBD",
                    "turning_points": [],
                }
            ]
        }
        atomic_write(out_path, yaml.dump(stub, default_flow_style=False, allow_unicode=True))


def get_char_arc_notes(beat_id: str, arcs_data: dict) -> dict[str, str]:
    """Return a {name: arc_summary} dict for all characters in *arcs_data*.

    The summary describes where the character sits in their arc at the given beat,
    based on their turning points.
    """
    notes: dict[str, str] = {}
    for char in arcs_data.get("characters", []):
        name = char.get("name", "")
        if not name:
            continue
        arc_type = char.get("arc_type", "")
        starting = char.get("starting_state", "")
        ending = char.get("ending_state", "")

        # Find the latest turning point before or at this beat
        last_tp_label = None
        for tp in char.get("turning_points", []):
            if tp.get("beat_id", "") <= beat_id:
                last_tp_label = tp.get("label", "")

        if last_tp_label:
            notes[name] = f"{arc_type} arc — post '{last_tp_label}'"
        else:
            notes[name] = f"{arc_type} arc — '{starting}' → '{ending}'"

    return notes
