"""Story Spine: dramatic curve, act structure, turning points, tension arc."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
from quillan.templates import get_prompt




async def generate_story_spine(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
) -> None:
    """Generate Story_Spine.yaml from outline, creative brief, and idea."""
    from quillan.io import atomic_write
    from quillan.structure.story import _extract_beat_ids

    out_path = paths.story_spine(world, canon, series, story)
    paths.ensure(out_path)

    outline_path = paths.outline(world, canon, series, story)
    outline_text = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""
    outline_data = yaml.safe_load(outline_text) or {}

    brief_path = paths.creative_brief(world, canon, series, story)
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""

    input_dir = paths.story_input(world, canon, series, story)
    seed_files = list(input_dir.iterdir()) if input_dir.exists() else []
    idea_text = seed_files[0].read_text(encoding="utf-8") if seed_files else ""

    if llm.settings.has_api_keys and outline_text:
        user_prompt = get_prompt("story_spine_user", world_dir=paths.world(world)).format(
            idea=idea_text[:1000],
            brief=brief_text[:2000],
            outline=outline_text[:4000],
        )
        raw = await llm.call("planning", get_prompt("story_spine_system", world_dir=paths.world(world)), user_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        atomic_write(out_path, raw)
    else:
        beat_ids = _extract_beat_ids(outline_data)
        stub = _stub_spine(beat_ids)
        atomic_write(out_path, yaml.dump(stub, default_flow_style=False, allow_unicode=True))


def _stub_spine(beat_ids: list[str]) -> dict:
    """Build a deterministic three-act spine from beat IDs.

    Tension curve: piecewise linear rise from 2→9 over 70% of beats,
    then fall from 9→3 over the remaining 30%.
    """
    n = len(beat_ids)
    act1_end = max(1, n // 3)
    act2_end = max(act1_end + 1, (2 * n) // 3)

    acts = [
        {
            "act": 1,
            "label": "Setup",
            "beats": beat_ids[:act1_end],
            "tension_range": [2, 4],
        },
        {
            "act": 2,
            "label": "Confrontation",
            "beats": beat_ids[act1_end:act2_end],
            "tension_range": [4, 9],
        },
        {
            "act": 3,
            "label": "Resolution",
            "beats": beat_ids[act2_end:],
            "tension_range": [9, 3],
        },
    ]

    beat_tension: dict[str, int] = {}
    for i, bid in enumerate(beat_ids):
        pct = i / max(n - 1, 1)
        if pct < 0.7:
            t = 2 + pct * (9 - 2) / 0.7
        else:
            t = 9 - (pct - 0.7) * (9 - 3) / 0.3
        beat_tension[bid] = max(1, min(10, round(t)))

    turning_points: dict[str, str] = {}
    if n >= 1:
        turning_points["inciting_incident"] = beat_ids[min(1, n - 1)]
    if n >= 4:
        turning_points["first_plot_point"] = beat_ids[n // 4]
        turning_points["midpoint"] = beat_ids[n // 2]
        turning_points["low_point"] = beat_ids[(3 * n) // 4]
        turning_points["climax"] = beat_ids[max(n - 2, 0)]
        turning_points["resolution"] = beat_ids[-1]

    return {
        "structure": "three_act",
        "acts": acts,
        "turning_points": turning_points,
        "beat_tension": beat_tension,
    }


def get_beat_arc_context(beat_id: str, spine_data: dict) -> dict:
    """Return arc_position and tension_level for a single beat from spine data."""
    beat_tension = spine_data.get("beat_tension", {})
    tension = beat_tension.get(beat_id, 5)

    # Default position from which act the beat falls in
    arc_position = "rising_action"
    for act in spine_data.get("acts", []):
        if beat_id in act.get("beats", []):
            label = act.get("label", "").lower()
            act_num = act.get("act", 2)
            if act_num == 1 or "setup" in label:
                arc_position = "setup"
            elif act_num == 3 or "resolution" in label:
                arc_position = "resolution"
            else:
                arc_position = "rising_action"
            break

    # Refine: check if beat_id matches a named turning point
    for tp_name, tp_beat in spine_data.get("turning_points", {}).items():
        if tp_beat == beat_id:
            arc_position = tp_name
            break

    return {"arc_position": arc_position, "tension_level": tension}
