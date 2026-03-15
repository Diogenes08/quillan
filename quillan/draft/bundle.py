"""Context bundle assembly for beat drafting."""

from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.config import Settings
    from quillan.paths import Paths

_SCOPE_CONTRACT_TEMPLATE = textwrap.dedent("""\
    ## Scope Contract for {beat_id}

    **Goal:** {goal}

    **Must include:**
    {scope_items}

    **Must NOT include:**
    {out_of_scope_items}

    **Style constraints:**
    {rules_items}
    """)


async def assemble_bundle(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_id: str,
    settings: "Settings",
    attempt: int = 0,
) -> Path:
    """Assemble context.md for a beat draft.

    Sections:
    1. Canon Packet
    2. Beat Spec (YAML)
    3. Scope Contract, Constraints, Style
    4. Fix List (if prior audit failed)
    5. Story history (last N beat excerpts, bounded)

    Also writes inputs.json with SHA-256 hashes of all input files.
    Returns path to context.md.
    """
    import aiofiles
    from quillan.io import atomic_write

    beat_dir = paths.beat(world, canon, series, story, beat_id)
    beat_dir.mkdir(parents=True, exist_ok=True)

    context_path = paths.beat_context(world, canon, series, story, beat_id)
    inputs_path = paths.beat_inputs(world, canon, series, story, beat_id)

    sections: list[str] = []
    input_hashes: dict[str, str] = {}

    # ── 1. Canon Packet ───────────────────────────────────────────────────
    canon_packet_path = paths.canon_packet(world, canon, series, story)
    if canon_packet_path.exists():
        async with aiofiles.open(canon_packet_path, encoding="utf-8", errors="replace") as _f:
            canon_text = await _f.read()
        input_hashes["canon_packet"] = _sha256(canon_text)
        sections.append(f"# Canon Packet\n\n{canon_text}")

    # ── 2. Beat Spec ──────────────────────────────────────────────────────
    spec_path = paths.beat_spec(world, canon, series, story, beat_id)
    spec_data: dict = {}
    if spec_path.exists():
        async with aiofiles.open(spec_path, encoding="utf-8", errors="replace") as _f:
            spec_text = await _f.read()
        input_hashes["beat_spec"] = _sha256(spec_text)
        try:
            spec_data = yaml.safe_load(spec_text) or {}
        except yaml.YAMLError:
            spec_data = {}
        sections.append(f"# Beat Specification\n\n```yaml\n{spec_text}\n```")

    # ── 3. Scope Contract ────────────────────────────────────────────────
    scope_section = _build_scope_contract(beat_id, spec_data)
    sections.append(scope_section)

    # ── 3.5. Author Context ───────────────────────────────────────────────
    brief_path = paths.creative_brief(world, canon, series, story)
    brief_text: str | None = None
    if brief_path.exists():
        async with aiofiles.open(brief_path, encoding="utf-8", errors="replace") as _f:
            brief_text = await _f.read()
        input_hashes["creative_brief"] = _sha256(brief_text)
    author_context = _build_author_context(
        paths, world, canon, series, story, spec_data, brief_text=brief_text
    )
    if author_context:
        sections.append(author_context)

    # ── 3.55. Style Reference (optional) ─────────────────────────────────
    style_section = _build_style_reference(paths, world, canon, series, story)
    if style_section:
        sections.append(style_section)

    # ── 3.6. Character Voices (optional) ─────────────────────────────────
    beat_characters: list[str] = spec_data.get("characters", [])
    if beat_characters:
        from quillan.structure.dialogue import load_voice_profiles, format_voice_section
        profiles = load_voice_profiles(paths, world, canon, series, story, beat_characters)
        voice_section = format_voice_section(profiles)
        if voice_section:
            sections.append(voice_section)

    # ── 3.7. Continuity Deltas ────────────────────────────────────────────
    delta_section = _build_continuity_deltas(
        paths, world, canon, series, story, beat_id
    )
    if delta_section:
        sections.append(delta_section)

    # ── 4. Fix List (if retry) ────────────────────────────────────────────
    if attempt > 0:
        fix_path = paths.beat_fix_list(world, canon, series, story, beat_id)
        if fix_path.exists():
            async with aiofiles.open(fix_path, encoding="utf-8", errors="replace") as _f:
                fix_text = await _f.read()
            input_hashes["fix_list"] = _sha256(fix_text)
            sections.append(f"# Fix List (Attempt {attempt})\n\n{fix_text}")

    # ── 5. Story History ──────────────────────────────────────────────────
    history_text = _build_history(
        paths, world, canon, series, story, beat_id, settings
    )
    if history_text:
        input_hashes["history"] = _sha256(history_text)
        sections.append(f"# Story History\n\n{history_text}")

    # ── Assemble and write ────────────────────────────────────────────────
    context_text = "\n\n---\n\n".join(sections)
    atomic_write(context_path, context_text)

    # Write inputs manifest
    atomic_write(inputs_path, json.dumps({"sha256": input_hashes}, indent=2))

    return context_path


def _build_scope_contract(beat_id: str, spec_data: dict) -> str:
    """Build scope contract section from beat spec."""
    goal = spec_data.get("goal", "Advance the story")
    scope = spec_data.get("scope", [])
    out_of_scope = spec_data.get("out_of_scope", [])
    rules = spec_data.get("rules", [])
    tone = spec_data.get("tone", "neutral")
    wc = spec_data.get("word_count_target", 1500)

    scope_items = "\n".join(f"- {s}" for s in scope) if scope else "- (not specified)"
    oos_items = "\n".join(f"- {s}" for s in out_of_scope) if out_of_scope else "- (none)"
    rules_items = "\n".join(f"- {r}" for r in rules) if rules else "- Maintain narrative voice"

    contract = _SCOPE_CONTRACT_TEMPLATE.format(
        beat_id=beat_id,
        goal=goal,
        scope_items=scope_items,
        out_of_scope_items=oos_items,
        rules_items=rules_items,
    )

    constraints = (
        f"## Constraints\n\n"
        f"- **Tone:** {tone}\n"
        f"- **Target word count:** {wc} words\n"
        f"- **Beat ID:** {beat_id}\n"
    )

    return f"# Scope and Constraints\n\n{contract}\n{constraints}"


def _outline_beat_order(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
) -> list[str]:
    """Return beat IDs in Outline.yaml narrative order, or [] if unavailable."""
    from quillan.validate import extract_beat_ids
    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        return []
    try:
        data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return extract_beat_ids(data)


def _build_history(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    current_beat_id: str,
    settings: "Settings",
) -> str:
    """Build story history from prior beats, bounded by continuity_max_context_chars."""
    # Determine which beats precede current beat
    beats_dir = paths.story_beats(world, canon, series, story)
    if not beats_dir.exists():
        return ""

    # Check continuity files first
    summary_path = paths.continuity_summary(world, canon, series, story)
    threads_path = paths.continuity_threads(world, canon, series, story)

    parts: list[str] = []
    remaining_chars = settings.continuity_max_context_chars

    # Add continuity summary
    if settings.continuity_include_history and summary_path.exists():
        summary = summary_path.read_text(encoding="utf-8", errors="replace")
        if summary.strip():
            chunk = summary[:min(len(summary), remaining_chars // 2)]
            parts.append(f"## Story Summary\n\n{chunk}")
            remaining_chars -= len(chunk)

    # Add open threads
    if threads_path.exists() and remaining_chars > 500:
        threads = threads_path.read_text(encoding="utf-8", errors="replace")
        if threads.strip():
            chunk = threads[:min(len(threads), remaining_chars // 3)]
            parts.append(f"## Open Story Threads\n\n{chunk}")
            remaining_chars -= len(chunk)

    # Add excerpts from last N completed beats
    if settings.continuity_last_beats_n > 0 and remaining_chars > 200:
        outline_order = _outline_beat_order(paths, world, canon, series, story)
        existing_dirs = {d.name: d for d in beats_dir.iterdir() if d.is_dir()}
        if outline_order:
            # Use narrative order from Outline.yaml; stop before current beat
            try:
                current_pos = outline_order.index(current_beat_id)
            except ValueError:
                current_pos = len(outline_order)
            prior_ids = [
                bid for bid in outline_order[:current_pos] if bid in existing_dirs
            ]
            recent = [existing_dirs[bid] for bid in prior_ids[-settings.continuity_last_beats_n:]]
        else:
            # Fallback: alphabetical sort (e.g. single-digit beat IDs only)
            beat_dirs = sorted(existing_dirs.values(), key=lambda d: d.name)
            prior_dirs = [d for d in beat_dirs if d.name != current_beat_id]
            recent = prior_dirs[-settings.continuity_last_beats_n:]

        beat_excerpts: list[str] = []
        for bdir in reversed(recent):
            if remaining_chars <= 0:
                break
            draft = bdir / "Beat_Draft.md"
            if draft.exists():
                text = draft.read_text(encoding="utf-8", errors="replace")
                excerpt = text[:min(len(text), remaining_chars // max(1, len(recent)))]
                beat_excerpts.append(f"### {bdir.name}\n\n{excerpt}")
                remaining_chars -= len(excerpt)

        if beat_excerpts:
            parts.append("## Recent Beats\n\n" + "\n\n---\n\n".join(reversed(beat_excerpts)))

    return "\n\n".join(parts)


def _build_author_context(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    spec_data: dict,
    brief_text: str | None = None,
) -> str:
    """Build an Author Context section from beat spec fields and Creative_Brief.yaml.

    Surfaces arc position, tension, voice, active motifs, character arc state,
    and per-character motivation/goal to the draft LLM.
    Returns an empty string if no authoring data is available.
    """
    parts: list[str] = []

    # Dramatic position (from enriched beat spec)
    arc_pos = spec_data.get("arc_position", "")
    tension = spec_data.get("tension_level", "")
    emotional_beat = spec_data.get("emotional_beat", "")
    theme_payoff = spec_data.get("theme_payoff", "")
    pacing = spec_data.get("pacing", "")
    antagonist_pressure = spec_data.get("antagonist_pressure", "")
    if arc_pos or tension or emotional_beat or theme_payoff or pacing:
        parts.append("## Dramatic Position\n\n")
        if arc_pos:
            parts.append(f"- **Arc position:** {arc_pos}\n")
        if tension:
            parts.append(f"- **Tension level:** {tension}/10\n")
        if emotional_beat:
            parts.append(f"- **Emotional beat:** {emotional_beat}\n")
        if theme_payoff:
            parts.append(f"- **Theme to develop:** {theme_payoff}\n")
        if pacing:
            parts.append(f"- **Pacing:** {pacing}\n")
        if antagonist_pressure:
            parts.append(f"- **Antagonist pressure:** {antagonist_pressure}\n")

    # Voice (from Creative_Brief.yaml — caller may pass text to avoid double-read)
    if brief_text is None:
        brief_path = paths.creative_brief(world, canon, series, story)
        if brief_path.exists():
            try:
                brief_text = brief_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                brief_text = None
    if brief_text:
        try:
            brief_data = yaml.safe_load(brief_text) or {}
            voice = brief_data.get("voice", {})
            if isinstance(voice, dict) and voice:
                parts.append("\n## Voice\n\n")
                if voice.get("prose_style"):
                    parts.append(f"- **Prose style:** {voice['prose_style']}\n")
                if voice.get("pov"):
                    parts.append(f"- **POV:** {voice['pov']}\n")
                patterns = voice.get("characteristic_patterns", [])
                if patterns:
                    parts.append(f"- **Use:** {', '.join(str(p) for p in patterns)}\n")
                avoid = voice.get("avoid", [])
                if avoid:
                    parts.append(f"- **Avoid:** {', '.join(str(a) for a in avoid)}\n")
        except yaml.YAMLError:
            pass

    # Active motifs (from enriched beat spec)
    motifs = spec_data.get("active_motifs", [])
    if motifs:
        parts.append("\n## Active Motifs\n\n")
        for m in motifs:
            if isinstance(m, dict):
                name = m.get("name", "")
                note = m.get("note", "")
                if name:
                    line = f"- {name}" + (f" — {note}" if note else "")
                    parts.append(line + "\n")

    # Character arc state + motivation (from enriched beat spec + Character_Arcs.yaml)
    char_notes = spec_data.get("char_arc_notes", {})
    arcs_path = paths.character_arcs(world, canon, series, story)
    char_motivations: dict[str, str] = {}
    if arcs_path.exists():
        try:
            arcs_data = yaml.safe_load(
                arcs_path.read_text(encoding="utf-8", errors="replace")
            ) or {}
            for char in arcs_data.get("characters", []):
                name = char.get("name", "")
                motivation = char.get("motivation", "")
                if name and motivation:
                    char_motivations[name] = motivation
        except yaml.YAMLError:
            pass

    if isinstance(char_notes, dict) and char_notes:
        parts.append("\n## Character Arc State\n\n")
        for name, note in char_notes.items():
            motivation = char_motivations.get(name, "")
            line = f"- **{name}:** {note}"
            if motivation:
                line += f" _(motivation: {motivation})_"
            parts.append(line + "\n")
    elif char_motivations:
        # No arc notes from spec, but we have motivations from arcs file
        parts.append("\n## Character Motivations\n\n")
        for name, motivation in char_motivations.items():
            parts.append(f"- **{name}:** {motivation}\n")

    if not parts:
        return ""
    return "# Author Context\n\n" + "".join(parts)


_STYLE_REF_MAX_CHARS = 3000  # hard cap so samples don't crowd out spec + history


def _build_style_reference(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
) -> str:
    """Return a Style Reference section if samples.md or style_profile.yaml exists.

    Structure (when both are present):
      ## Style Fingerprint   — structured YAML profile extracted by LLM
      ## Style Samples       — raw prose excerpts (capped at _STYLE_REF_MAX_CHARS)

    Returns empty string when neither file is present.
    """
    parts: list[str] = []

    # ── Style fingerprint (structured profile, injected first) ────────────
    profile_path = paths.style_profile(world, canon, series, story)
    if profile_path.exists():
        try:
            profile_text = profile_path.read_text(encoding="utf-8", errors="replace").strip()
            if profile_text:
                parts.append("## Style Fingerprint\n\n```yaml\n" + profile_text + "\n```")
        except OSError:
            pass

    # ── Raw prose samples ─────────────────────────────────────────────────
    samples_path = paths.style_samples(world, canon, series, story)
    if samples_path.exists():
        try:
            text = samples_path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                if len(text) > _STYLE_REF_MAX_CHARS:
                    text = text[:_STYLE_REF_MAX_CHARS] + "\n...(truncated)"
                parts.append("## Style Samples\n\n" + text)
        except OSError:
            pass

    if not parts:
        return ""

    return (
        "# Style Reference\n\n"
        "Write prose that matches the rhythm, voice, and texture demonstrated "
        "below. Do not copy; let the style inform your own prose.\n\n"
        + "\n\n".join(parts)
    )


def _build_continuity_deltas(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    current_beat_id: str,
) -> str:
    """Build a 'What Changed Last Beat' section from state files.

    Compares current_state.yaml with the most recent per-beat state snapshot
    to surface character location changes and newly resolved threads for the
    draft LLM.  Returns empty string if no prior state is available.
    """
    state_path = paths.state_current(world, canon, series, story)
    if not state_path.exists():
        return ""

    try:
        current_state = yaml.safe_load(
            state_path.read_text(encoding="utf-8", errors="replace")
        ) or {}
    except yaml.YAMLError:
        return ""

    # Find most recent beat snapshot (alphabetically last = most recent timestamp prefix)
    state_dir = paths.story_state(world, canon, series, story)
    snapshots = sorted(
        [f for f in state_dir.iterdir() if f.name.endswith("_state.yaml")
         and f.name != "current_state.yaml"],
        key=lambda f: f.name,
    )
    if len(snapshots) < 2:
        # Not enough history to compute a delta
        return ""

    # Second-to-last snapshot is the "previous" state
    prev_snapshot = snapshots[-2] if snapshots else None
    if not prev_snapshot or not prev_snapshot.exists():
        return ""

    try:
        prev_state = yaml.safe_load(
            prev_snapshot.read_text(encoding="utf-8", errors="replace")
        ) or {}
    except yaml.YAMLError:
        return ""

    deltas: list[str] = []

    # Character location / status changes
    prev_chars = prev_state.get("characters", {})
    curr_chars = current_state.get("characters", {})
    if isinstance(prev_chars, dict) and isinstance(curr_chars, dict):
        for name, curr_data in curr_chars.items():
            prev_data = prev_chars.get(name, {})
            if not isinstance(curr_data, dict) or not isinstance(prev_data, dict):
                continue
            for field in ("location", "status", "condition"):
                prev_val = prev_data.get(field)
                curr_val = curr_data.get(field)
                if curr_val and curr_val != prev_val:
                    deltas.append(
                        f"- **{name}** {field}: {prev_val!r} → {curr_val!r}"
                    )

    # World state changes
    prev_world = prev_state.get("world_state", {})
    curr_world = current_state.get("world_state", {})
    if isinstance(prev_world, dict) and isinstance(curr_world, dict):
        for key, curr_val in curr_world.items():
            prev_val = prev_world.get(key)
            if curr_val != prev_val:
                deltas.append(f"- **World/{key}:** {prev_val!r} → {curr_val!r}")

    if not deltas:
        return ""

    return "# What Changed Last Beat\n\n" + "\n".join(deltas)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
