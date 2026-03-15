"""World planning: create world dirs and build the Canon Packet."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
from quillan.templates import get_prompt

CANON_PACKET_MAX_CHARS = 24000

_BIBLE_STUB = textwrap.dedent("""\
    # Universe Bible

    ## Setting
    [Describe your world's setting here]

    ## History
    [Key historical events that shape your story]

    ## Geography
    [World map, regions, important locations]

    ## Factions & Powers
    [Major factions, their goals, alliances]
    """)

_CANON_RULES_STUB = textwrap.dedent("""\
    # Canon Rules

    ## Hard Rules (never violate)
    - [Rule 1]
    - [Rule 2]

    ## Soft Rules (bend with care)
    - [Soft rule 1]

    ## Continuity Notes
    [Key continuity constraints]
    """)

_WORLD_AXIOMS_STUB = textwrap.dedent("""\
    # World Axioms

    ## Physics & Magic
    [How does the world work at a fundamental level?]

    ## Social Structure
    [Class, power, culture]

    ## Technology Level
    [What technology exists?]
    """)






async def create_world_if_missing(
    paths: "Paths",
    world: str,
    llm: "LLMClient",
    seed_text: str,
) -> None:
    """Create world dir + planning templates.

    If API keys are available: generates Universe_Bible, Canon_Rules, World_Axioms via LLM.
    Otherwise: writes editable stubs.
    """
    from quillan.io import atomic_write

    planning_dir = paths.world_planning(world)
    planning_dir.mkdir(parents=True, exist_ok=True)

    bible_path = paths.world_bible(world)
    rules_path = paths.world_canon_rules(world)
    axioms_path = paths.world_axioms(world)

    # If all files already exist, skip
    if bible_path.exists() and rules_path.exists() and axioms_path.exists():
        return

    if llm.settings.has_api_keys:
        # Generate via LLM
        if not bible_path.exists():
            sys_prompt = "You are a world-building expert. Output clean markdown."
            user_prompt = get_prompt("world_bible_user", world_dir=paths.world(world)).format(seed=seed_text)
            bible_text = await llm.call("planning", sys_prompt, user_prompt)
            atomic_write(bible_path, bible_text)
        else:
            bible_text = bible_path.read_text(encoding="utf-8")

        if not rules_path.exists():
            sys_prompt = "You are a world-building expert. Output clean markdown."
            user_prompt = get_prompt("world_canon_rules_user", world_dir=paths.world(world)).format(bible=bible_text[:8000])
            rules_text = await llm.call("planning", sys_prompt, user_prompt)
            atomic_write(rules_path, rules_text)

        if not axioms_path.exists():
            sys_prompt = "You are a world-building expert. Output clean markdown."
            user_prompt = get_prompt("world_axioms_user", world_dir=paths.world(world)).format(bible=bible_text[:8000])
            axioms_text = await llm.call("planning", sys_prompt, user_prompt)
            atomic_write(axioms_path, axioms_text)
    else:
        # Write stubs for manual editing
        if not bible_path.exists():
            atomic_write(bible_path, _BIBLE_STUB)
        if not rules_path.exists():
            atomic_write(rules_path, _CANON_RULES_STUB)
        if not axioms_path.exists():
            atomic_write(axioms_path, _WORLD_AXIOMS_STUB)


async def build_canon_packet(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    llm: "LLMClient",
    prior_story_section: str = "",
) -> Path:
    """Compress world + story planning into a single bounded Canon_Packet.md.

    Maximum CANON_PACKET_MAX_CHARS characters. LLM path if keys present, static otherwise.
    Returns the path to the written Canon_Packet.md.
    """
    from quillan.io import atomic_write

    out_path = paths.canon_packet(world, canon, series, story)
    paths.ensure(out_path)

    # Gather source documents
    bible_path = paths.world_bible(world)
    rules_path = paths.world_canon_rules(world)
    axioms_path = paths.world_axioms(world)
    story_planning_dir = paths.story_planning(world, canon, series, story)

    bible_text = bible_path.read_text(encoding="utf-8") if bible_path.exists() else ""
    rules_text = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""
    axioms_text = axioms_path.read_text(encoding="utf-8") if axioms_path.exists() else ""

    story_planning_text = ""
    if story_planning_dir.is_dir():
        parts = []
        for f in sorted(story_planning_dir.iterdir()):
            if f.is_file() and f.suffix in (".md", ".txt", ".yaml", ".yml"):
                parts.append(f.read_text(encoding="utf-8", errors="replace"))
        story_planning_text = "\n\n---\n\n".join(parts)

    # Inject character registries (world-level + canon-level)
    from quillan.structure.character_registry import (
        load_registry_section,
        load_world_registry_section,
    )
    registry_section = load_registry_section(paths, world, canon)
    world_registry_section = load_world_registry_section(paths, world)
    combined_registry = "\n\n".join(
        s for s in [world_registry_section, registry_section] if s
    )

    if llm.settings.has_api_keys:
        sys_prompt = "You are an expert story development assistant. Output clean markdown."
        user_prompt = get_prompt("world_packet_distill_user", world_dir=paths.world(world)).format(
            max_chars=CANON_PACKET_MAX_CHARS,
            bible=bible_text[:6000],
            rules=rules_text[:4000],
            axioms=axioms_text[:4000],
            story_planning=story_planning_text[:4000],
            prior_story=(prior_story_section + "\n\n" + combined_registry)[:3000],
        )
        packet_text = await llm.call("planning", sys_prompt, user_prompt)
    else:
        # Static concatenation with hard cap
        sections = [
            ("# Canon Packet\n\n## Universe Bible\n\n" + bible_text),
            ("## Canon Rules\n\n" + rules_text),
            ("## World Axioms\n\n" + axioms_text),
        ]
        if story_planning_text:
            sections.append("## Story Planning\n\n" + story_planning_text)
        if prior_story_section:
            sections.append(prior_story_section)
        if combined_registry:
            sections.append(combined_registry)
        packet_text = "\n\n---\n\n".join(sections)

    # Enforce hard character cap
    if len(packet_text) > CANON_PACKET_MAX_CHARS:
        # Apply 60/40 window in-memory
        head = int(CANON_PACKET_MAX_CHARS * 0.60)
        tail = CANON_PACKET_MAX_CHARS - head
        marker = "\n\n[...trimmed...]\n\n"
        packet_text = packet_text[:head] + marker + packet_text[len(packet_text) - tail:]

    atomic_write(out_path, packet_text)
    return out_path
