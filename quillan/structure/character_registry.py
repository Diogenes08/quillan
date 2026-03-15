"""Canon-level character registry: persists character data across stories.

The registry lives at:
  worlds/<world>/canons/<canon>/Character_Registry.yaml

It is updated (not replaced) after each story is created or drafted.
No LLM calls are made — data comes from Character_Arcs.yaml and current_state.yaml.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.paths import Paths

_REGISTRY_SCHEMA_VERSION = 1


def update_registry(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
) -> None:
    """Merge this story's character data into the canon-level registry.

    Reads:
      - structure/Character_Arcs.yaml  (descriptions, motivations, arc roles)
      - state/current_state.yaml       (final location, status, condition)

    Updates the registry atomically without overwriting unrelated characters.
    No-op if neither source file exists.
    """
    from quillan.io import atomic_write
    from quillan.lock import sync_file_lock

    arcs_path = paths.character_arcs(world, canon, series, story)
    state_path = paths.state_current(world, canon, series, story)

    if not arcs_path.exists() and not state_path.exists():
        return

    registry_path = paths.character_registry(world, canon)

    with sync_file_lock(registry_path.with_suffix(".lock")):
        # Load existing registry
        registry: dict = {}
        if registry_path.exists():
            try:
                registry = yaml.safe_load(
                    registry_path.read_text(encoding="utf-8")
                ) or {}
            except yaml.YAMLError:
                registry = {}

        if "_meta" not in registry:
            registry["_meta"] = {"schema_version": _REGISTRY_SCHEMA_VERSION}
        if "characters" not in registry:
            registry["characters"] = {}

        chars: dict = registry["characters"]

        # ── Merge from Character_Arcs.yaml ────────────────────────────────
        if arcs_path.exists():
            try:
                arcs_data = yaml.safe_load(
                    arcs_path.read_text(encoding="utf-8")
                ) or {}
                for char in arcs_data.get("characters", []):
                    name = char.get("name", "").strip()
                    if not name:
                        continue
                    entry = chars.setdefault(name, {"first_story": story, "stories": []})
                    if story not in entry.get("stories", []):
                        entry.setdefault("stories", []).append(story)
                    # Update descriptive fields (overwrite with latest story's data)
                    for field in ("description", "motivation", "arc_role", "arc_end"):
                        if char.get(field):
                            entry[field] = char[field]
            except yaml.YAMLError:
                pass

        # ── Merge from current_state.yaml (final status per story) ────────
        if state_path.exists():
            try:
                state_data = yaml.safe_load(
                    state_path.read_text(encoding="utf-8")
                ) or {}
                state_chars = state_data.get("characters", {})
                if isinstance(state_chars, dict):
                    for name, char_state in state_chars.items():
                        if not isinstance(char_state, dict):
                            continue
                        entry = chars.setdefault(name, {"first_story": story, "stories": []})
                        if story not in entry.get("stories", []):
                            entry.setdefault("stories", []).append(story)
                        # Record final state from this story
                        story_states = entry.setdefault("story_states", {})
                        story_states[story] = {
                            k: v for k, v in char_state.items()
                            if k in ("location", "status", "condition", "alive")
                        }
                        # Convenience: keep top-level "last_known_status" current
                        if char_state.get("status"):
                            entry["last_known_status"] = char_state["status"]
                        if "alive" in char_state:
                            entry["alive"] = char_state["alive"]
            except yaml.YAMLError:
                pass

        registry["characters"] = chars
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            registry_path,
            yaml.dump(registry, default_flow_style=False, allow_unicode=True),
        )

    # Propagate up to the world-level aggregate registry
    update_world_registry(paths, world)


def update_world_registry(paths: "Paths", world: str) -> None:
    """Aggregate all canon-level registries into a world-level Character_Registry.yaml.

    Scans worlds/<world>/canons/*/Character_Registry.yaml and merges them.
    Characters appearing in multiple canons are merged under one entry; the
    ``canons`` list records which canons they appear in.
    No LLM calls are made.
    """
    from quillan.io import atomic_write
    from quillan.lock import sync_file_lock

    world_registry_path = paths.world_character_registry(world)
    canons_dir = paths.world(world) / "canons"
    if not canons_dir.is_dir():
        return

    canon_registries = list(canons_dir.glob("*/Character_Registry.yaml"))
    if not canon_registries:
        return

    with sync_file_lock(world_registry_path.with_suffix(".lock")):
        merged: dict[str, dict] = {}

        for reg_path in sorted(canon_registries):
            canon_name = reg_path.parent.name
            try:
                data = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            for name, info in data.get("characters", {}).items():
                if not isinstance(info, dict):
                    continue
                entry = merged.setdefault(name, {})
                # Merge canonical list
                entry.setdefault("canons", [])
                if canon_name not in entry["canons"]:
                    entry["canons"].append(canon_name)
                # Merge stories list (prefixed with canon name for disambiguation)
                for story in info.get("stories", []):
                    tagged = f"{canon_name}/{story}"
                    entry.setdefault("stories", [])
                    if tagged not in entry["stories"]:
                        entry["stories"].append(tagged)
                # Overwrite descriptive fields with the latest data found
                for field in ("description", "motivation", "arc_role", "arc_end",
                               "last_known_status", "alive", "first_story"):
                    if info.get(field) is not None:
                        entry[field] = info[field]

        if not merged:
            return

        registry = {
            "_meta": {"schema_version": _REGISTRY_SCHEMA_VERSION, "scope": "world"},
            "characters": merged,
        }
        world_registry_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            world_registry_path,
            yaml.dump(registry, default_flow_style=False, allow_unicode=True),
        )


def load_registry_section(paths: "Paths", world: str, canon: str) -> str:
    """Return a Markdown summary of the registry for injection into Canon Packet.

    Returns empty string if the registry doesn't exist or has no characters.
    """
    registry_path = paths.character_registry(world, canon)
    if not registry_path.exists():
        return ""

    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ""

    chars = data.get("characters", {})
    if not isinstance(chars, dict) or not chars:
        return ""

    lines = ["## Established Characters (Canon Registry)\n"]
    for name, info in sorted(chars.items()):
        if not isinstance(info, dict):
            continue
        desc = info.get("description", "")
        motivation = info.get("motivation", "")
        status = info.get("last_known_status", "")
        stories = ", ".join(info.get("stories", []))
        parts = [f"- **{name}**"]
        if desc:
            parts.append(f": {desc}")
        if motivation:
            parts.append(f" _(motivation: {motivation})_")
        if status:
            parts.append(f" [status: {status}]")
        if stories:
            parts.append(f" (appeared in: {stories})")
        lines.append("".join(parts))

    return "\n".join(lines) + "\n"


def load_world_registry_section(paths: "Paths", world: str) -> str:
    """Return a Markdown summary of world-level characters for cross-canon context.

    Returns empty string if the world registry doesn't exist or has no characters.
    """
    registry_path = paths.world_character_registry(world)
    if not registry_path.exists():
        return ""

    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ""

    chars = data.get("characters", {})
    if not isinstance(chars, dict) or not chars:
        return ""

    lines = ["## Established Characters (World Registry — All Canons)\n"]
    for name, info in sorted(chars.items()):
        if not isinstance(info, dict):
            continue
        desc = info.get("description", "")
        canons = ", ".join(info.get("canons", []))
        status = info.get("last_known_status", "")
        parts = [f"- **{name}**"]
        if desc:
            parts.append(f": {desc}")
        if status:
            parts.append(f" [status: {status}]")
        if canons:
            parts.append(f" (canons: {canons})")
        lines.append("".join(parts))

    return "\n".join(lines) + "\n"
