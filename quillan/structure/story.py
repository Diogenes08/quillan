"""Story planning: outline generation, beat specs, dependency map."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from quillan.templates import get_prompt
from quillan.validate import extract_beat_ids as _extract_beat_ids

logger = logging.getLogger("quillan.structure.story")

if TYPE_CHECKING:
    from quillan.config import Settings
    from quillan.llm import LLMClient
    from quillan.paths import Paths





async def create_story(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    seed_file: Path,
    llm: "LLMClient",
    settings: "Settings",
    skip_interview: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Full orchestration: dirs → world → creative brief → spine → arcs → subplots → outline → beat specs.

    Returns story_name (derived from seed file stem).
    Raises NeedsInterviewError if the idea is vague and no interview answers exist yet
    (unless skip_interview=True, in which case the brief is inferred directly).
    """
    from quillan.io import atomic_write
    from quillan.structure.world import create_world_if_missing, build_canon_packet
    from quillan.structure.creative_brief import (
        classify_specificity,
        generate_creative_brief,
        generate_creative_brief_interview,
        NeedsInterviewError,
    )
    from quillan.structure.story_spine import generate_story_spine
    from quillan.structure.character_arcs import generate_character_arcs
    from quillan.structure.subplots import generate_subplot_register
    from quillan.structure.conflicts import generate_conflict_map
    from quillan.validate import (
        validate_creative_brief,
        validate_story_spine,
        validate_character_arcs,
        validate_subplot_register,
        validate_conflict_map,
    )

    import aiofiles

    def _prog(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    seed_file = Path(seed_file)
    story = seed_file.stem

    _prog("Initialising story structure")
    # Create directory tree
    for d in [
        paths.story_input(world, canon, series, story),
        paths.story_planning(world, canon, series, story),
        paths.story_structure(world, canon, series, story),
        paths.story_beats(world, canon, series, story),
        paths.story_state(world, canon, series, story),
        paths.story_export(world, canon, series, story),
        paths.story_continuity(world, canon, series, story),
        paths.queue_dir(world, canon, series, story),
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy seed file
    seed_dest = paths.story_input(world, canon, series, story) / seed_file.name
    if not seed_dest.exists():
        from quillan.io import atomic_write_from
        atomic_write_from(seed_dest, seed_file)

    async with aiofiles.open(seed_file, encoding="utf-8") as _f:
        seed_text = await _f.read()

    # World planning
    _prog("Creating world context")
    await create_world_if_missing(paths, world, llm, seed_text)

    # ── Phase 1: Creative Brief (specificity gate) ────────────────────────────
    _prog("Generating creative brief")
    brief_path = paths.creative_brief(world, canon, series, story)
    interview_path = paths.creative_brief_interview(world, canon, series, story)

    if not brief_path.exists():
        classification = await classify_specificity(seed_text, llm)
        if classification["needs_interview"] and not interview_path.exists() and not skip_interview:
            # Generate the interview template and stop — user must fill it in
            await generate_creative_brief_interview(
                paths, world, canon, series, story, seed_text, llm
            )
            raise NeedsInterviewError(story, interview_path)
        else:
            # Detailed enough, interview answered, or interview explicitly skipped
            await generate_creative_brief(
                paths, world, canon, series, story, seed_text, llm
            )
    validate_creative_brief(brief_path)

    # Story planning concept doc
    planning_dir = paths.story_planning(world, canon, series, story)
    concept_path = planning_dir / "Story_Concept.md"
    if not concept_path.exists():
        if llm.settings.has_api_keys:
            sys_p = "You are a story development expert. Output clean markdown."
            usr_p = f"Expand this story seed into a detailed story concept:\n\n{seed_text}"
            concept_text = await llm.call("planning", sys_p, usr_p)
            atomic_write(concept_path, concept_text)
        else:
            atomic_write(concept_path, f"# Story Concept\n\n{seed_text}\n")

    # Outline (brief is now available to enrich the prompt)
    _prog("Building story outline")
    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        await generate_outline(paths, world, canon, series, story, llm, seed_text)

    # ── Phases 2–4: Story Spine, Character Arcs, Subplot Register ────────────
    # These three are fully independent (each writes to a different path and
    # only reads the outline, which is already on disk). Run them in parallel.
    import asyncio as _asyncio

    spine_path = paths.story_spine(world, canon, series, story)
    arcs_path = paths.character_arcs(world, canon, series, story)
    subplot_path = paths.subplot_register(world, canon, series, story)
    conflict_path = paths.conflict_map(world, canon, series, story)

    _prog("Building planning artifacts (spine, arcs, subplots, conflicts)")
    _gen_coros = []
    if not spine_path.exists():
        _gen_coros.append(generate_story_spine(paths, world, canon, series, story, llm))
    if not arcs_path.exists():
        _gen_coros.append(generate_character_arcs(paths, world, canon, series, story, llm))
    if not subplot_path.exists():
        _gen_coros.append(generate_subplot_register(paths, world, canon, series, story, llm))
    if not conflict_path.exists():
        _gen_coros.append(generate_conflict_map(paths, world, canon, series, story, llm))
    if _gen_coros:
        await _asyncio.gather(*_gen_coros)

    validate_story_spine(spine_path)
    validate_character_arcs(arcs_path)
    validate_subplot_register(subplot_path)
    validate_conflict_map(conflict_path)

    # Dependency map
    _prog("Generating dependency map")
    dep_path = paths.dependency_map(world, canon, series, story)
    if not dep_path.exists():
        await generate_dependency_map(paths, world, canon, series, story, llm)

    # Beat specs — load all planning artifacts once, pass to each beat
    outline_text = outline_path.read_text(encoding="utf-8")
    outline_data = yaml.safe_load(outline_text) or {}
    beat_ids = _extract_beat_ids(outline_data)

    spine_data = _load_yaml_safe(paths.story_spine(world, canon, series, story))
    brief_data = _load_yaml_safe(paths.creative_brief(world, canon, series, story))
    arcs_data = _load_yaml_safe(paths.character_arcs(world, canon, series, story))
    conflict_data = _load_yaml_safe(paths.conflict_map(world, canon, series, story))

    _prog(f"Generating beat specs ({len(beat_ids)} beats)")
    _spec_sem = _asyncio.Semaphore(settings.max_parallel)

    async def _gen_one_spec(beat_id: str) -> None:
        async with _spec_sem:
            beat_dir = paths.beat(world, canon, series, story, beat_id)
            beat_dir.mkdir(parents=True, exist_ok=True)
            spec_path = paths.beat_spec(world, canon, series, story, beat_id)
            if not spec_path.exists():
                await generate_beat_spec(
                    paths, world, canon, series, story, beat_id, llm,
                    outline_text=outline_text,
                    spine_data=spine_data, brief_data=brief_data, arcs_data=arcs_data,
                    conflict_data=conflict_data,
                )

    await _asyncio.gather(*[_gen_one_spec(bid) for bid in beat_ids])

    # Canon packet — inject prior story continuity if this is not the first story
    _prog("Assembling canon packet")
    from quillan.structure.series_handoff import (
        register_and_get_prior_story,
        build_prior_story_section,
    )
    prior_story = register_and_get_prior_story(paths, world, canon, series, story)
    prior_section = (
        build_prior_story_section(paths, world, canon, series, prior_story)
        if prior_story else ""
    )
    await build_canon_packet(paths, world, canon, series, story, llm,
                             prior_story_section=prior_section)

    # Update cross-story character registry with newly created arcs
    from quillan.structure.character_registry import update_registry
    update_registry(paths, world, canon, series, story)

    _prog("Done")
    return story


async def generate_outline(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
    seed_text: str = "",
) -> None:
    """Generate and write Outline.yaml, incorporating Creative Brief if available."""
    import aiofiles
    from quillan.io import atomic_write

    if not seed_text:
        seed_path = paths.story_input(world, canon, series, story)
        seed_files = list(seed_path.iterdir()) if seed_path.exists() else []
        if seed_files:
            async with aiofiles.open(seed_files[0], encoding="utf-8") as _f:
                seed_text = await _f.read()
        else:
            seed_text = ""

    outline_path = paths.outline(world, canon, series, story)

    brief_path = paths.creative_brief(world, canon, series, story)
    if brief_path.exists():
        async with aiofiles.open(brief_path, encoding="utf-8") as _f:
            brief_text = await _f.read()
    else:
        brief_text = "(none)"

    if llm.settings.has_api_keys:
        user_prompt = get_prompt("outline_user", world_dir=paths.world(world)).format(seed=seed_text, brief=brief_text[:2000])
        raw = await llm.call("planning", get_prompt("outline_system", world_dir=paths.world(world)), user_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        atomic_write(outline_path, raw)
    else:
        stub = _generate_stub_outline(story, seed_text)
        atomic_write(outline_path, yaml.dump(stub, default_flow_style=False, allow_unicode=True))


async def generate_dependency_map(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
) -> None:
    """Generate dependency_map.json from Outline.yaml."""
    import aiofiles
    from quillan.io import atomic_write
    from quillan.validate import py_extract_json

    outline_path = paths.outline(world, canon, series, story)
    dep_path = paths.dependency_map(world, canon, series, story)

    if outline_path.exists():
        async with aiofiles.open(outline_path, encoding="utf-8") as _f:
            outline_text = await _f.read()
    else:
        outline_text = ""
    outline_data = yaml.safe_load(outline_text) or {}
    beat_ids = _extract_beat_ids(outline_data)

    if llm.settings.has_api_keys and outline_text:
        user_prompt = get_prompt("depmap_user", world_dir=paths.world(world)).format(outline=outline_text[:6000])
        raw = await llm.call("planning", get_prompt("depmap_system", world_dir=paths.world(world)), user_prompt, mode="json")
        dep_map = py_extract_json(raw, ["dependencies"])
    else:
        dep_map = {"dependencies": _linear_dep_map(beat_ids)}

    atomic_write(dep_path, json.dumps(dep_map, indent=2))


async def generate_beat_spec(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    llm: "LLMClient",
    outline_text: str = "",
    spine_data: dict | None = None,
    brief_data: dict | None = None,
    arcs_data: dict | None = None,
    conflict_data: dict | None = None,
    recent_pacing: str = "",
) -> None:
    """Generate beat_spec.yaml for one beat, enriched with planning artifacts."""
    from quillan.io import atomic_write
    from quillan.structure.story_spine import get_beat_arc_context
    from quillan.structure.character_arcs import get_char_arc_notes
    from quillan.structure.conflicts import get_antagonist_pressure

    import aiofiles

    spec_path = paths.beat_spec(world, canon, series, story, beat_id)
    paths.ensure(spec_path)

    if not outline_text:
        ol = paths.outline(world, canon, series, story)
        if ol.exists():
            async with aiofiles.open(ol, encoding="utf-8") as _f:
                outline_text = await _f.read()
        else:
            outline_text = ""

    spine_data = spine_data or {}
    brief_data = brief_data or {}
    arcs_data = arcs_data or {}
    conflict_data = conflict_data or {}

    # Extract enrichment context
    arc_ctx = get_beat_arc_context(beat_id, spine_data)
    arc_position = arc_ctx["arc_position"]
    tension_level = arc_ctx["tension_level"]

    motifs = brief_data.get("motifs", [])
    char_notes = get_char_arc_notes(beat_id, arcs_data)
    antagonist_pressure = get_antagonist_pressure(beat_id, conflict_data)

    if llm.settings.has_api_keys and outline_text:
        # Build YAML fragments for the prompt
        motifs_yaml = _indent_yaml_list(
            [{"name": m.get("name", ""), "note": m.get("meaning", "")} for m in motifs],
            indent=2,
        )
        char_arc_notes_yaml = _indent_yaml_dict(char_notes, indent=2)
        char_arc_notes_text = "\n".join(
            f"  {name}: {note}" for name, note in char_notes.items()
        ) or "  (no character arc data yet)"

        brief_text = ""
        if brief_data:
            brief_text = yaml.dump(brief_data, default_flow_style=False, allow_unicode=True)[:1500]

        # Build conflict context summary
        conflict_text = "(none)"
        if conflict_data:
            core = conflict_data.get("core_conflict", "")
            stakes = conflict_data.get("stakes", "")
            if core or stakes:
                conflict_text = ""
                if core:
                    conflict_text += f"  core_conflict: {core}\n"
                if stakes:
                    conflict_text += f"  stakes: {stakes}"
            if antagonist_pressure:
                conflict_text += f"\n  antagonist_pressure_this_beat: {antagonist_pressure}"

        user_prompt = get_prompt("beatspec_user", world_dir=paths.world(world)).format(
            beat_id=beat_id,
            outline=outline_text[:5000],
            brief=brief_text,
            arc_position=arc_position,
            tension_level=tension_level,
            motifs_yaml=motifs_yaml or "  []",
            char_arc_notes_yaml=char_arc_notes_yaml or "  {}",
            char_arc_notes_text=char_arc_notes_text,
            conflict_text=conflict_text,
            recent_pacing=recent_pacing or "(none yet)",
            antagonist_pressure=antagonist_pressure or "",
        )
        raw = await llm.call("planning", get_prompt("beatspec_system", world_dir=paths.world(world)), user_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        atomic_write(spec_path, raw)
    else:
        stub = {
            "beat_id": beat_id,
            "title": f"Beat {beat_id}",
            "goal": "Advance the story",
            "setting": "TBD",
            "characters": [],
            "pov_character": "TBD",
            "tone": "neutral",
            "word_count_target": 1500,
            "emotional_beat": "neutral",
            "theme_payoff": "TBD",
            "pacing": "medium",
            "scope": ["Events to happen in this beat"],
            "out_of_scope": [],
            "rules": [],
            "dependencies": [],
            "arc_position": arc_position,
            "tension_level": tension_level,
            "active_motifs": [{"name": m.get("name", ""), "note": ""} for m in motifs],
            "char_arc_notes": char_notes,
            "antagonist_pressure": antagonist_pressure,
        }
        atomic_write(spec_path, yaml.dump(stub, default_flow_style=False, allow_unicode=True))


async def regen_beat_specs(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
    beats: list[str] | None = None,
) -> int:
    """Delete and regenerate beat specs using current planning artifacts.

    Reads existing Brief/Spine/Arcs from disk — does not regenerate them.
    If *beats* is None, regenerates all beats in Outline.yaml order.
    Returns count of specs regenerated.
    """
    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        return 0

    outline_text = outline_path.read_text(encoding="utf-8")
    outline_data = yaml.safe_load(outline_text) or {}
    all_beat_ids = _extract_beat_ids(outline_data)

    target_beats = beats if beats is not None else all_beat_ids

    spine_data = _load_yaml_safe(paths.story_spine(world, canon, series, story))
    brief_data = _load_yaml_safe(paths.creative_brief(world, canon, series, story))
    arcs_data = _load_yaml_safe(paths.character_arcs(world, canon, series, story))
    conflict_data = _load_yaml_safe(paths.conflict_map(world, canon, series, story))

    count = 0
    for beat_id in target_beats:
        beat_dir = paths.beat(world, canon, series, story, beat_id)
        beat_dir.mkdir(parents=True, exist_ok=True)
        spec_path = paths.beat_spec(world, canon, series, story, beat_id)
        if spec_path.exists():
            spec_path.unlink()
        await generate_beat_spec(
            paths, world, canon, series, story, beat_id, llm,
            outline_text=outline_text,
            spine_data=spine_data,
            brief_data=brief_data,
            arcs_data=arcs_data,
            conflict_data=conflict_data,
        )
        count += 1

    return count


# ── Helpers ───────────────────────────────────────────────────────────────────

def _linear_dep_map(beat_ids: list[str]) -> dict[str, list[str]]:
    """Build a simple linear dependency chain."""
    deps: dict[str, list[str]] = {}
    for i, bid in enumerate(beat_ids):
        deps[bid] = [beat_ids[i - 1]] if i > 0 else []
    return deps


def _generate_stub_outline(story: str, seed_text: str) -> dict:
    """Generate a minimal stub outline for offline use."""
    return {
        "title": story.replace("_", " ").title(),
        "genre": "Fiction",
        "theme": "TBD",
        "chapters": [
            {
                "chapter": 1,
                "title": "Act 1",
                "beats": [
                    {
                        "beat_id": "C1-S1-B1",
                        "title": "Opening",
                        "goal": "Establish setting and protagonist",
                        "setting": "TBD",
                        "characters": [],
                        "word_count_target": 1500,
                    },
                    {
                        "beat_id": "C1-S1-B2",
                        "title": "Inciting Incident",
                        "goal": "Disrupt the status quo",
                        "setting": "TBD",
                        "characters": [],
                        "word_count_target": 1500,
                    },
                ],
            }
        ],
        "seed": seed_text[:500],
    }


def _load_yaml_safe(path: "Path") -> dict:
    """Load a YAML file, returning {} on any failure."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Could not load YAML file %s: %s", path, exc)
        return {}


def _indent_yaml_list(items: list, indent: int = 2) -> str:
    """Render a list of dicts as indented YAML lines."""
    if not items:
        return " " * indent + "[]"
    lines = []
    for item in items:
        first = True
        for k, v in item.items():
            prefix = " " * indent + ("- " if first else "  ")
            lines.append(f"{prefix}{k}: {v}")
            first = False
    return "\n".join(lines)


def _indent_yaml_dict(d: dict, indent: int = 2) -> str:
    """Render a flat dict as indented YAML lines."""
    if not d:
        return " " * indent + "{}"
    lines = []
    for k, v in d.items():
        lines.append(" " * indent + f"{k}: {v}")
    return "\n".join(lines)
