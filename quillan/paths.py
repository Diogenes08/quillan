"""Single source of truth for all path construction in Quillan2.

Never construct paths by string concatenation elsewhere — always use this module.
"""

from pathlib import Path


class Paths:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    # ── Top-level directories ─────────────────────────────────────────────

    def worlds_dir(self) -> Path:
        return self.data_dir / "worlds"

    def runs_dir(self) -> Path:
        return self.data_dir / ".runs"

    def cache_dir(self) -> Path:
        return self.data_dir / ".cache"

    def tmp_dir(self) -> Path:
        return self.data_dir / ".tmp"

    # ── World / Canon / Series hierarchy ─────────────────────────────────

    def world(self, world: str) -> Path:
        return self.worlds_dir() / world

    def world_planning(self, world: str) -> Path:
        return self.world(world) / "planning"

    def world_bible(self, world: str) -> Path:
        return self.world_planning(world) / "Universe_Bible.md"

    def world_canon_rules(self, world: str) -> Path:
        return self.world_planning(world) / "Canon_Rules.md"

    def world_axioms(self, world: str) -> Path:
        return self.world_planning(world) / "World_Axioms.md"

    def canon(self, world: str, canon: str) -> Path:
        return self.world(world) / "canons" / canon

    def series(self, world: str, canon: str, series: str) -> Path:
        return self.canon(world, canon) / "series" / series

    # ── Story directories ─────────────────────────────────────────────────

    def story(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.series(world, canon, series) / "stories" / story

    def story_input(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story(world, canon, series, story) / "input"

    def story_planning(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story(world, canon, series, story) / "planning"

    def story_structure(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story(world, canon, series, story) / "structure"

    def story_beats(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story(world, canon, series, story) / "beats"

    def story_state(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story(world, canon, series, story) / "state"

    def story_export(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story(world, canon, series, story) / "export"

    def story_continuity(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story(world, canon, series, story) / "continuity"

    # ── Planning files ────────────────────────────────────────────────────

    def creative_brief_interview(
        self, world: str, canon: str, series: str, story: str
    ) -> Path:
        return self.story_planning(world, canon, series, story) / "Creative_Brief_Interview.md"

    def creative_brief(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_planning(world, canon, series, story) / "Creative_Brief.yaml"

    # ── Structure files ───────────────────────────────────────────────────

    def outline(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_structure(world, canon, series, story) / "Outline.yaml"

    def dependency_map(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_structure(world, canon, series, story) / "dependency_map.json"

    def canon_packet(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_structure(world, canon, series, story) / "Canon_Packet.md"

    def story_spine(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_structure(world, canon, series, story) / "Story_Spine.yaml"

    def character_arcs(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_structure(world, canon, series, story) / "Character_Arcs.yaml"

    def subplot_register(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_structure(world, canon, series, story) / "Subplot_Register.yaml"

    def conflict_map(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_structure(world, canon, series, story) / "Conflict_Map.yaml"

    # ── Beat directories and files ────────────────────────────────────────

    def beat(self, world: str, canon: str, series: str, story: str, beat_id: str) -> Path:
        return self.story_beats(world, canon, series, story) / beat_id

    def beat_spec(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        return self.beat(world, canon, series, story, beat_id) / "beat_spec.yaml"

    def beat_draft(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        return self.beat(world, canon, series, story, beat_id) / "Beat_Draft.md"

    def beat_context(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        return self.beat(world, canon, series, story, beat_id) / "context.md"

    def beat_inputs(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        return self.beat(world, canon, series, story, beat_id) / "inputs.json"

    def beat_forensic_dir(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        return self.beat(world, canon, series, story, beat_id) / "forensic"

    def beat_versions_dir(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        return self.beat(world, canon, series, story, beat_id) / "versions"

    def beat_lock(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        """Sentinel file: beats/<beat_id>/.lock — presence means beat is locked."""
        return self.beat(world, canon, series, story, beat_id) / ".lock"

    def beat_version(
        self, world: str, canon: str, series: str, story: str, beat_id: str, ts: str
    ) -> Path:
        """Path for a timestamped beat-draft snapshot: versions/<ts>.md"""
        return self.beat_versions_dir(world, canon, series, story, beat_id) / f"{ts}.md"

    def beat_mega_audit(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        return self.beat_forensic_dir(world, canon, series, story, beat_id) / "mega_audit.json"

    def beat_fix_list(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        return self.beat_forensic_dir(world, canon, series, story, beat_id) / "fix_list.txt"

    # ── State files ───────────────────────────────────────────────────────

    def state_bundle(
        self, world: str, canon: str, series: str, story: str, beat_id: str
    ) -> Path:
        return self.story_state(world, canon, series, story) / f"{beat_id}_state.yaml"

    def state_current(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_state(world, canon, series, story) / "current_state.yaml"

    def state_checkpoints_dir(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_state(world, canon, series, story) / "checkpoints"

    def state_checkpoint(
        self, world: str, canon: str, series: str, story: str, beat_id: str, ts: str
    ) -> Path:
        """Path for a timestamped pre-write checkpoint: checkpoints/{ts}_{beat_id}.yaml"""
        return self.state_checkpoints_dir(world, canon, series, story) / f"{ts}_{beat_id}.yaml"

    # ── Continuity files ──────────────────────────────────────────────────

    def continuity_summary(
        self, world: str, canon: str, series: str, story: str
    ) -> Path:
        return self.story_continuity(world, canon, series, story) / "Summary.md"

    def continuity_threads(
        self, world: str, canon: str, series: str, story: str
    ) -> Path:
        return self.story_continuity(world, canon, series, story) / "Open_Threads.md"

    def continuity_ledger(
        self, world: str, canon: str, series: str, story: str
    ) -> Path:
        return self.story_continuity(world, canon, series, story) / "Ledger.md"

    def continuity_lock(
        self, world: str, canon: str, series: str, story: str
    ) -> Path:
        return self.story_continuity(world, canon, series, story) / ".lock"

    def drift_report(self, world: str, canon: str, series: str, story: str) -> Path:
        """Cached continuity drift results: continuity/drift_report.json"""
        return self.story_continuity(world, canon, series, story) / "drift_report.json"

    # ── Queue directory ───────────────────────────────────────────────────

    def queue_dir(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_continuity(world, canon, series, story) / "queue"

    def queue_item(
        self, world: str, canon: str, series: str, story: str, beat_id: str, ts: str
    ) -> Path:
        return self.queue_dir(world, canon, series, story) / f"{ts}_{beat_id}.json"

    # ── Character registry (canon-level, persists across stories) ────────

    def character_registry(self, world: str, canon: str) -> Path:
        return self.canon(world, canon) / "Character_Registry.yaml"

    def world_character_registry(self, world: str) -> Path:
        """World-level registry: aggregates characters across all canons."""
        return self.world(world) / "Character_Registry.yaml"

    # ── Series ordering ───────────────────────────────────────────────────

    def series_order(self, world: str, canon: str, series: str) -> Path:
        return self.series(world, canon, series) / "Series_Order.yaml"

    # ── Cover / Lulu files ────────────────────────────────────────────────

    def cover_image(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_export(world, canon, series, story) / f"{story}_cover.png"

    def lulu_bundle(self, world: str, canon: str, series: str, story: str) -> Path:
        return self.story_export(world, canon, series, story) / f"{story}_lulu_bundle.zip"

    # ── Hook directories ──────────────────────────────────────────────────

    def global_hooks_dir(self) -> Path:
        """<data_dir>/hooks/ — hooks that fire for every story."""
        return self.data_dir / "hooks"

    def world_hooks_dir(self, world: str) -> Path:
        """<world>/hooks/ — hooks for all stories in this world."""
        return self.world(world) / "hooks"

    def story_hooks_dir(self, world: str, canon: str, series: str, story: str) -> Path:
        """<story>/hooks/ — hooks for a specific story only."""
        return self.story(world, canon, series, story) / "hooks"

    # ── Dialogue / voice profiles ─────────────────────────────────────────

    def dialogue_dir(self, world: str, canon: str, series: str, story: str) -> Path:
        """Directory holding per-character voice profile YAML files."""
        return self.story_structure(world, canon, series, story) / "dialogue"

    def voice_profile(
        self, world: str, canon: str, series: str, story: str, character_slug: str
    ) -> Path:
        """Path for a character voice profile: structure/dialogue/<slug>.yaml"""
        return self.dialogue_dir(world, canon, series, story) / f"{character_slug}.yaml"

    # ── Style reference ───────────────────────────────────────────────────

    def style_reference_dir(self, world: str, canon: str, series: str, story: str) -> Path:
        """Directory holding style samples and the extracted style profile."""
        return self.story_structure(world, canon, series, story) / "style_reference"

    def style_samples(self, world: str, canon: str, series: str, story: str) -> Path:
        """Prose samples file — plain text excerpts used as style examples."""
        return self.style_reference_dir(world, canon, series, story) / "samples.md"

    def style_profile(self, world: str, canon: str, series: str, story: str) -> Path:
        """LLM-extracted style fingerprint (Phase 2)."""
        return self.style_reference_dir(world, canon, series, story) / "style_profile.yaml"

    # ── Per-world / per-story settings overrides ─────────────────────────

    def world_settings(self, world: str) -> Path:
        """Optional quillan.yaml at world level — overrides global Settings."""
        return self.world(world) / "quillan.yaml"

    def story_settings(self, world: str, canon: str, series: str, story: str) -> Path:
        """Optional quillan.yaml at story level — overrides world + global Settings."""
        return self.story(world, canon, series, story) / "quillan.yaml"

    # ── Convenience: ensure directory exists ──────────────────────────────

    def ensure(self, path: Path) -> Path:
        """Create directory (or parent of file path) and return path."""
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
        return path
