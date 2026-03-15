"""Click CLI entry point for Quillan2."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import click

from quillan.config import Settings
from quillan.paths import Paths

logger = logging.getLogger("quillan.cli")


@click.group(
    epilog=(
        "Typical workflow:\n\n"
        "  1. Write your idea to a text file.\n"
        "  2. Run 'create' to plan the story (outline, beat specs).\n"
        "  3. Review / edit the generated YAML files if you like.\n"
        "  4. Run 'draft' to write prose for every beat.\n"
        "  5. Run 'export' to produce a finished manuscript.\n\n"
        "Or use 'quickdraft' to do steps 2-4 in one command.\n\n"
        "API keys are read from environment variables or a .env file:\n"
        "  OPENAI_API_KEY, XAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY\n\n"
        "Run 'quillan selftest' to verify your installation without\n"
        "making any API calls."
    )
)
@click.option("--world", default="default", show_default=True,
              help="World name — a shared universe that stories live inside. "
                   "Use the same world name to reuse world-building documents "
                   "across multiple stories.")
@click.option("--canon", default=None,
              help="Canon name — an alternate timeline or continuity within a "
                   "world (default: 'default', or QUILLAN_CANON env var).")
@click.option("--series", default=None,
              help="Series name — a story arc grouping within a canon "
                   "(default: 'default', or QUILLAN_SERIES env var).")
@click.option("--data-dir", "data_dir", default=None, type=click.Path(),
              help="Root directory where all story data is stored "
                   "(default: ./quillan_data, or QUILLAN_DATA_DIR env var).")
@click.option("--config", "config_file", default=None, type=click.Path(),
              help="Path to a .env config file containing API keys and settings.")
@click.pass_context
def main(
    ctx: click.Context,
    world: str,
    canon: str | None,
    series: str | None,
    data_dir: str | None,
    config_file: str | None,
) -> None:
    """Quillan2 — filesystem-driven AI story generation.

    Turns a short idea file into a fully planned and drafted long-form story.
    Stories are organised in a hierarchy: world → canon → series → story.
    All generated files are plain YAML / Markdown — human-readable and editable.
    """
    ctx.ensure_object(dict)

    # Build settings, allowing CLI overrides
    kwargs: dict[str, Any] = {}
    if data_dir:
        kwargs["data_dir"] = Path(data_dir)
    if config_file:
        import os
        os.environ["QUILLAN_ENV_FILE"] = config_file

    settings = Settings(**kwargs)

    ctx.obj["settings"] = settings
    ctx.obj["world"] = world
    ctx.obj["canon"] = canon or settings.canon
    ctx.obj["series"] = series or settings.series
    ctx.obj["paths"] = Paths(settings.data_dir)


def _require_api_keys(settings: Settings) -> None:
    """Exit with a helpful message if no API keys or local LLM base URLs are configured."""
    if not settings.has_api_keys:
        click.echo(
            "No API keys configured. Quillan2 needs at least one LLM provider to work.\n"
            "\n"
            "  Set one of: OPENAI_API_KEY, XAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY\n"
            "  Or configure a local LLM with QUILLAN_DRAFT_API_BASE / QUILLAN_PLANNING_API_BASE.\n"
            "\n"
            "  See 'quillan.env.example' for all options, or run 'quillan doctor' for diagnostics.",
            err=True,
        )
        sys.exit(1)


def _make_llm_and_telemetry(ctx: click.Context):
    """Create LLMClient and Telemetry from context."""
    from quillan.llm import LLMClient
    from quillan.migrate import run_migrations
    from quillan.telemetry import Telemetry

    settings: Settings = ctx.obj["settings"]
    paths: Paths = ctx.obj["paths"]

    run_migrations(paths.data_dir)
    telemetry = Telemetry(paths.runs_dir(), enabled=settings.telemetry)
    llm = LLMClient(settings, telemetry, cache_dir=settings.cache_dir)
    return llm, telemetry


@main.command(
    epilog=(
        "Example:\n\n"
        "  echo 'A detective uncovers a city-wide conspiracy' > idea.txt\n"
        "  quillan --world noir create idea.txt\n\n"
        "After this command you can review and edit the generated outline\n"
        "and beat specs before running 'draft' to write the actual prose."
    )
)
@click.argument("idea_file", type=click.Path(exists=True))
@click.option(
    "--no-interview", "skip_interview", is_flag=True, default=False,
    help="Skip the creative brief interview even for vague ideas — "
         "Quillan will infer voice, themes, and tone directly from the idea text.",
)
@click.pass_context
def create(ctx: click.Context, idea_file: str, skip_interview: bool) -> None:
    """Create story structure from an idea file — no prose yet.

    Reads IDEA_FILE (a plain text description of your story concept) and uses
    an LLM to generate the full planning structure:

    \b
      • Universe_Bible.md  — world-building rules and lore
      • Story_Concept.md   — expanded story concept
      • Outline.yaml       — chapters and beats (the story blueprint)
      • beat_spec.yaml     — per-beat planning and constraints
      • dependency_map.json — which beats depend on which

    No prose is written at this stage. Use 'draft' (or 'quickdraft') after
    reviewing the generated files.
    """
    from quillan.config import load_story_settings
    from quillan.structure.story import create_story

    settings: Settings = ctx.obj["settings"]
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    # Apply world-level quillan.yaml overrides (story doesn't exist yet).
    settings = load_story_settings(paths, world, canon, series, story="", base=settings)
    ctx.obj["settings"] = settings

    _require_api_keys(settings)
    llm, telemetry = _make_llm_and_telemetry(ctx)

    async def _run() -> None:
        from quillan.structure.creative_brief import NeedsInterviewError
        from quillan.hooks import run_hooks
        try:
            story_name = await create_story(
                paths, world, canon, series, Path(idea_file), llm, settings,
                skip_interview=skip_interview,
                on_progress=lambda msg: click.echo(f"  {msg}"),
            )
            click.echo(f"Created story: {story_name}")
            click.echo(f"Data dir: {paths.story(world, canon, series, story_name)}")
            await run_hooks("post_create", paths, world, canon, series, story_name)
        except NeedsInterviewError as exc:
            click.echo("")
            click.echo("Your idea is open-ended — a Creative Brief Interview has been generated.")
            click.echo(f"  {exc.interview_path}")
            click.echo("")
            click.echo("Fill in the answers, save the file, then re-run:")
            click.echo(f"  quillan create {idea_file}")
            click.echo("")

    try:
        asyncio.run(_run())
    finally:
        telemetry.finalize()


@main.command(
    epilog=(
        "Examples:\n\n"
        "  # Draft every beat in one go\n"
        "  quillan --world noir draft my_story\n\n"
        "  # Draft only the first five beats, review, then continue\n"
        "  quillan --world noir draft my_story --beats 5\n\n"
        "  # Re-draft specific beats by ID\n"
        "  quillan --world noir draft my_story --beats C1-S1-B1,C1-S1-B3 --force\n\n"
        "  # Re-draft B1 and every beat that depends on it\n"
        "  quillan --world noir draft my_story --beats C1-S1-B1 --cascade\n"
    )
)
@click.argument("story")
@click.option(
    "--beats", "beats_arg", default="all", show_default=True,
    help="'all', an integer count, or comma-separated beat IDs "
         "(e.g. 'C1-S1-B1,C2-S1-B3').",
)
@click.option(
    "--force", is_flag=True, default=False,
    help="Re-draft beats that already have a Beat_Draft.md. "
         "By default, already-drafted beats are skipped.",
)
@click.option(
    "--cascade", "cascade", is_flag=True, default=False,
    help="Also re-draft every beat that transitively depends on --beats. "
         "Implies --force (existing drafts in the cascade set are overwritten).",
)
@click.option(
    "--stale-only", "stale_only", is_flag=True, default=False,
    help="Re-draft only beats whose spec is newer than their draft. "
         "Implies --force. Can be combined with --cascade to also "
         "re-draft downstream dependents.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False,
    help="Print one progress line per beat as it is drafted.",
)
@click.option(
    "--stream", "stream", is_flag=True, default=False,
    help="Write a live Markdown preview to <story>.live.md during drafting.",
)
@click.option(
    "--dry-run", "dry_run", is_flag=True, default=False,
    help="Print which beats would be drafted without making any LLM calls or writes.",
)
@click.pass_context
def draft(
    ctx: click.Context,
    story: str,
    beats_arg: str,
    force: bool,
    cascade: bool,
    stale_only: bool,
    verbose: bool,
    stream: bool,
    dry_run: bool,
) -> None:
    """Draft prose for the beats of an existing story structure.

    Runs the two-phase drafting pipeline for STORY (which must have been
    created with 'create' first):

    \b
      Phase 1 — parallel:  bundle context → write prose → audit quality
      Phase 2 — serial:    extract state changes → update continuity

    Beats are scheduled using the dependency graph so that each beat has
    access to everything that happened before it. Uses up to QUILLAN_MAX_PARALLEL
    concurrent LLM calls (default: 3).

    Drafting is incremental by default: already-drafted beats are skipped.
    Use --force to overwrite existing drafts (e.g. after editing a beat spec).
    Use --cascade to automatically re-draft all downstream dependents too.
    """
    from quillan.config import load_story_settings
    from quillan.pipeline.runner import draft_story

    settings: Settings = ctx.obj["settings"]
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    # Apply world + story quillan.yaml overrides before building the LLM client.
    settings = load_story_settings(paths, world, canon, series, story, base=settings)
    ctx.obj["settings"] = settings

    if not dry_run:
        _require_api_keys(settings)
    llm, telemetry = _make_llm_and_telemetry(ctx)

    _draft_failed: dict[str, str] = {}

    async def _run() -> None:
        effective_force = force
        beats: list[str] | None = None

        if stale_only:
            import yaml as _yaml
            from quillan.structure.story import _extract_beat_ids
            outline_path = paths.outline(world, canon, series, story)
            if not outline_path.exists():
                click.echo("Error: outline not found — run 'create' first.", err=True)
                sys.exit(1)
            outline_data = _yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
            all_beat_ids = _extract_beat_ids(outline_data)
            beats = _find_stale_beats(paths, world, canon, series, story, all_beat_ids)
            if not beats:
                click.echo("No stale drafts found.")
                return
            effective_force = True
        else:
            beats = _parse_beats_arg(beats_arg, paths, world, canon, series, story)

        if cascade:
            if beats is None:
                click.echo(
                    "--cascade with --beats all is redundant; drafting all beats.",
                    err=True,
                )
            else:
                from quillan.pipeline.dag import compute_dependents
                from quillan.validate import validate_dependency_map
                dep_map_data = validate_dependency_map(
                    paths.dependency_map(world, canon, series, story)
                )
                beats = compute_dependents(dep_map_data, beats)
                effective_force = True  # --cascade always implies --force

        if dry_run:
            # Resolve the actual beat list without making any calls
            if beats is None:
                from quillan.validate import validate_dependency_map
                from quillan.pipeline.dag import compute_batches
                dep_path = paths.dependency_map(world, canon, series, story)
                if not dep_path.exists():
                    click.echo("Error: dependency_map.json not found — run 'create' first.", err=True)
                    sys.exit(1)
                dep_map_data = validate_dependency_map(dep_path)
                beats = [bid for batch in compute_batches(dep_map_data) for bid in batch]
            click.echo(f"Dry run — would draft {len(beats)} beat(s):")
            for bid in beats:
                click.echo(f"  {bid}")
            return

        stream_path: Path | None = None
        if stream:
            export_dir = paths.story_export(world, canon, series, story)
            export_dir.mkdir(parents=True, exist_ok=True)
            stream_path = export_dir / f"{story}.live.md"
            click.echo(f"Streaming draft to: {stream_path}")
        if verbose:
            click.echo(f"Drafting beats for story: {story}")
        from quillan.hooks import run_hooks as _run_hooks

        async def _on_beat_done(beat_id: str) -> None:
            await _run_hooks(
                "post_beat", paths, world, canon, series, story,
                extra_env={
                    "QUILLAN_BEAT_ID": beat_id,
                    "QUILLAN_DRAFT_PATH": str(
                        paths.beat_draft(world, canon, series, story, beat_id)
                    ),
                },
            )

        draft_result = await draft_story(
            paths, world, canon, series, story,
            beats_mode="all",
            settings=settings, llm=llm, telemetry=telemetry,
            force=effective_force, verbose=verbose, stream_path=stream_path,
            explicit_beats=beats,
            on_beat_complete=_on_beat_done,
        )
        _draft_failed.update(draft_result.failed)
        n_done = len(draft_result.completed)
        n_fail = len(draft_result.failed)
        await _run_hooks(
            "post_draft", paths, world, canon, series, story,
            extra_env={
                "QUILLAN_BEATS_COMPLETED": str(n_done),
                "QUILLAN_BEATS_FAILED": str(n_fail),
            },
        )
        if n_fail == 0:
            click.echo(f"Draft complete for story: {story} ({n_done} beat(s) drafted)")
        else:
            click.echo(
                f"Draft complete for story: {story} "
                f"({n_done} drafted, {n_fail} failed)"
            )

    try:
        asyncio.run(_run())
    finally:
        telemetry.finalize()

    if _draft_failed:
        click.echo(f"\nFailed beats ({len(_draft_failed)}):", err=True)
        for bid, err in sorted(_draft_failed.items()):
            click.echo(f"  {bid}: {err}", err=True)
        sys.exit(1)


@main.command(
    epilog=(
        "Example:\n\n"
        "  quillan --world scifi quickdraft my_idea.txt\n\n"
        "Tip: use --beats 10 to get a quick preview of the first chapter\n"
        "before committing to drafting the whole story."
    )
)
@click.argument("idea_file", type=click.Path(exists=True))
@click.option(
    "--beats", "beats_mode", default="all", show_default=True,
    help="How many beats to draft: 'all' or an integer.",
)
@click.option(
    "--force", is_flag=True, default=False,
    help="Re-draft beats that already have a Beat_Draft.md.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False,
    help="Print one progress line per beat as it is drafted.",
)
@click.option(
    "--stream", "stream", is_flag=True, default=False,
    help="Write a live Markdown preview to <story>.live.md during drafting.",
)
@click.option(
    "--no-interview", "skip_interview", is_flag=True, default=False,
    help="Skip the creative brief interview even for vague ideas.",
)
@click.pass_context
def quickdraft(ctx: click.Context, idea_file: str, beats_mode: str, force: bool, verbose: bool, stream: bool, skip_interview: bool) -> None:
    """Create story structure and draft prose in one step.

    Equivalent to running 'create' followed immediately by 'draft'. Useful
    for rapid prototyping when you want a full draft without reviewing the
    intermediate planning files first.

    IDEA_FILE is a plain text file containing your story concept.
    """
    from quillan.config import load_story_settings
    from quillan.structure.story import create_story
    from quillan.pipeline.runner import draft_story

    settings: Settings = ctx.obj["settings"]
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    # Apply world-level overrides before create phase (story name not yet known).
    settings = load_story_settings(paths, world, canon, series, story="", base=settings)
    ctx.obj["settings"] = settings

    _require_api_keys(settings)
    llm, telemetry = _make_llm_and_telemetry(ctx)

    async def _run() -> None:
        from quillan.llm import LLMClient
        from quillan.structure.creative_brief import NeedsInterviewError
        try:
            story_name = await create_story(
                paths, world, canon, series, Path(idea_file), llm, settings,
                skip_interview=skip_interview,
                on_progress=lambda msg: click.echo(f"  {msg}"),
            )
        except NeedsInterviewError as exc:
            click.echo("")
            click.echo("Your idea is open-ended — a Creative Brief Interview has been generated.")
            click.echo(f"  {exc.interview_path}")
            click.echo("")
            click.echo("Fill in the answers, save the file, then re-run:")
            click.echo(f"  quillan quickdraft {idea_file}")
            click.echo("")
            return
        click.echo(f"Created story: {story_name}. Starting draft...")

        # Story now exists — re-apply with story-level overrides for draft phase.
        draft_settings = load_story_settings(paths, world, canon, series, story_name, base=settings)
        draft_llm = LLMClient(draft_settings, telemetry, cache_dir=draft_settings.cache_dir) \
            if draft_settings is not settings else llm

        stream_path: Path | None = None
        if stream:
            export_dir = paths.story_export(world, canon, series, story_name)
            export_dir.mkdir(parents=True, exist_ok=True)
            stream_path = export_dir / f"{story_name}.live.md"
            click.echo(f"Streaming draft to: {stream_path}")
        if verbose:
            click.echo(f"Drafting beats for story: {story_name}")
        await draft_story(
            paths, world, canon, series, story_name, beats_mode, draft_settings, draft_llm,
            telemetry, force=force, verbose=verbose, stream_path=stream_path,
        )
        click.echo(f"Quickdraft complete: {story_name}")

    try:
        asyncio.run(_run())
    finally:
        telemetry.finalize()


@main.command(
    epilog=(
        "Examples:\n\n"
        "  # Publish with a detailed idea — no prompts\n"
        "  quillan --world noir publish my_detailed_idea.txt\n\n"
        "  # Skip the interview gate for a vague idea\n"
        "  quillan publish vague_idea.txt --no-interview\n\n"
        "  # Export as Word document instead of epub\n"
        "  quillan publish my_idea.txt --format docx\n"
    )
)
@click.argument("idea_file", type=click.Path(exists=True))
@click.option(
    "--format", "fmt", default="epub", show_default=True,
    type=click.Choice(["markdown", "epub", "docx", "pdf", "print-pdf", "lulu",
                       "mobi", "azw3", "audiobook"]),
    help="Output format for the finished manuscript.",
)
@click.option(
    "--no-interview", "skip_interview", is_flag=True, default=False,
    help="Skip the creative brief interview even for vague ideas — "
         "Quillan will infer voice, themes, and tone directly from the idea text.",
)
@click.option(
    "--cover/--no-cover", "do_cover", default=True, show_default=True,
    help="Generate an AI cover image (requires OPENAI_API_KEY). "
         "Disable with --no-cover to skip cover generation.",
)
@click.option(
    "--beats", "beats_mode", default="all", show_default=True,
    help="How many beats to draft: 'all' or an integer.",
)
@click.option(
    "--force", is_flag=True, default=False,
    help="Re-draft beats that already have a Beat_Draft.md.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False,
    help="Print one progress line per beat during drafting.",
)
@click.option(
    "--stream", "stream", is_flag=True, default=False,
    help="Write a live Markdown preview to <story>.live.md during drafting.",
)
@click.option(
    "--dry-run", "dry_run", is_flag=True, default=False,
    help="Print what would happen without making any LLM calls.",
)
@click.pass_context
def publish(
    ctx: click.Context,
    idea_file: str,
    fmt: str,
    skip_interview: bool,
    do_cover: bool,
    beats_mode: str,
    force: bool,
    verbose: bool,
    stream: bool,
    dry_run: bool,
) -> None:
    """Create, draft, and export a finished manuscript in one step.

    The fully automated pipeline: idea → planning → draft → export.
    No intermediate review — ideal for hands-off generation or scripting.

    \b
    Interview gate (default on):
      Short or vague ideas generate a Creative_Brief_Interview.md and pause.
      Fill it in and re-run, or pass --no-interview to skip entirely.

    \b
    Format options:
      epub      — EPUB 3 e-book  (default; requires Pandoc)
      markdown  — plain Markdown (no extra tools needed)
      docx      — Word document  (requires Pandoc)
      pdf       — PDF            (requires Pandoc + LaTeX)
      print-pdf — print-ready 6×9" PDF (requires Pandoc + XeLaTeX)
      lulu      — Lulu POD bundle (requires Pandoc + XeLaTeX + Pillow)
      mobi      — Kindle MOBI    (requires Pandoc)
      azw3      — Kindle AZW3    (requires Pandoc)
      audiobook — M4B or ZIP of MP3s (requires OPENAI_API_KEY)
    """
    from quillan.structure.story import create_story
    from quillan.pipeline.runner import draft_story
    from quillan.export import export_story

    settings: Settings = ctx.obj["settings"]
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    _require_api_keys(settings)
    llm, telemetry = _make_llm_and_telemetry(ctx)

    async def _run() -> None:
        from quillan.structure.creative_brief import NeedsInterviewError

        # Planning
        click.echo("Planning story structure...")
        try:
            story_name = await create_story(
                paths, world, canon, series, Path(idea_file), llm, settings,
                skip_interview=skip_interview,
                on_progress=lambda msg: click.echo(f"  {msg}"),
            )
        except NeedsInterviewError as exc:
            click.echo("")
            click.echo("Your idea is open-ended — a Creative Brief Interview has been generated.")
            click.echo(f"  {exc.interview_path}")
            click.echo("")
            click.echo("Fill in the answers, save the file, then re-run:")
            click.echo(f"  quillan publish {idea_file}")
            click.echo("Or bypass the interview with: --no-interview")
            click.echo("")
            return

        if dry_run:
            from quillan.validate import validate_dependency_map
            from quillan.pipeline.dag import compute_batches
            dep_path = paths.dependency_map(world, canon, series, story_name)
            if dep_path.exists():
                dep_map = validate_dependency_map(dep_path)
                beats = [b for batch in compute_batches(dep_map) for b in batch]
                click.echo(f"Dry run — would draft {len(beats)} beat(s), then export as {fmt}.")
            else:
                click.echo("Dry run — story created but no dependency map found.")
            return

        # Drafting
        click.echo(f"Drafting {story_name}...")
        stream_path: Path | None = None
        if stream:
            export_dir = paths.story_export(world, canon, series, story_name)
            export_dir.mkdir(parents=True, exist_ok=True)
            stream_path = export_dir / f"{story_name}.live.md"
            click.echo(f"Streaming draft to: {stream_path}")
        await draft_story(
            paths, world, canon, series, story_name, beats_mode, settings, llm, telemetry,
            force=force, verbose=verbose, stream_path=stream_path,
        )

        # Cover (optional, silent)
        cover_path: Path | None = None
        if do_cover and settings.has_api_keys:
            click.echo("Generating cover image...")
            try:
                from quillan.structure.cover import generate_cover
                cover_path = await generate_cover(
                    paths, world, canon, series, story_name, llm
                )
                click.echo(f"Cover saved: {cover_path}")
            except Exception as cover_exc:
                click.echo(f"Cover generation skipped: {cover_exc}", err=True)

        # Export
        click.echo(f"Exporting as {fmt}...")
        try:
            if fmt == "audiobook":
                from quillan.tts import export_audiobook
                out_path = await export_audiobook(
                    paths, world, canon, series, story_name, settings,
                    on_progress=click.echo,
                )
            else:
                result = export_story(
                    paths, world, canon, series, story_name, fmt=fmt, settings=settings,
                    cover_path=cover_path,
                )
                if result.degraded:
                    click.echo(
                        f"Warning: {fmt} export unavailable; saved as {result.fmt} instead.",
                        err=True,
                    )
                out_path = result.path
            click.echo(f"Published: {out_path}")
        except (FileNotFoundError, ValueError, ImportError) as exc:
            click.echo(f"Export failed: {exc}", err=True)
            sys.exit(1)

    try:
        asyncio.run(_run())
    finally:
        telemetry.finalize()


@main.command("cover")
@click.argument("story")
@click.option(
    "--image", "image_path", default=None, type=click.Path(exists=True),
    help="Use an existing image file instead of AI generation.",
)
@click.option(
    "--author", default="",
    help="Author name for spine and cover text overlay.",
)
@click.option(
    "--regen", is_flag=True, default=False,
    help="Regenerate even if a cover image already exists.",
)
@click.pass_context
def cover_cmd(ctx: click.Context, story: str, image_path: str | None, author: str, regen: bool) -> None:
    """Generate or assign a cover image for STORY.

    By default, calls DALL-E 3 to generate a cover from the story's metadata
    (title, genre, themes, motifs from Creative_Brief.yaml). The resulting
    PNG is saved to the story's export/ directory and used automatically by
    subsequent 'export --format epub' and 'export --format lulu' commands.

    \b
    Use --image to supply your own cover file instead of AI generation.
    Use --regen to overwrite an existing cover.

    \b
    Examples:
      quillan --world noir cover my_story
      quillan --world noir cover my_story --image my_cover.png
      quillan --world noir cover my_story --regen
    """
    from quillan.structure.cover import generate_cover
    from quillan.llm import LLMError

    settings: Settings = ctx.obj["settings"]
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    if image_path is None and not settings.has_api_keys:
        click.echo(
            "Error: no API keys configured and no --image supplied.\n"
            "Set OPENAI_API_KEY or use: quillan cover <story> --image <file>",
            err=True,
        )
        sys.exit(1)

    llm, telemetry = _make_llm_and_telemetry(ctx)

    async def _run() -> None:
        try:
            out = await generate_cover(
                paths, world, canon, series, story, llm,
                image_path=Path(image_path) if image_path else None,
                force=regen,
            )
            click.echo(f"Cover saved: {out}")
        except (FileNotFoundError, LLMError) as exc:
            click.echo(f"Cover generation failed: {exc}", err=True)
            sys.exit(1)

    try:
        asyncio.run(_run())
    finally:
        telemetry.finalize()


@main.command("export")
@click.argument("story")
@click.option(
    "--format", "fmt", default="markdown", show_default=True,
    type=click.Choice(["markdown", "epub", "docx", "pdf", "print-pdf", "lulu",
                       "mobi", "azw3", "audiobook"]),
    help="Output format. epub, docx, pdf, print-pdf, and lulu require Pandoc. "
         "audiobook requires OPENAI_API_KEY and ffmpeg (optional for M4B).",
)
@click.pass_context
def export_cmd(ctx: click.Context, story: str, fmt: str) -> None:
    """Assemble and export STORY as a finished manuscript.

    Reads beat drafts in outline order and assembles them into a single
    document with chapter structure and YAML front matter (title, genre, theme).

    \b
      markdown  — plain Markdown with YAML front matter (no extra tools needed)
      epub      — EPUB 3 e-book   (requires Pandoc)
      docx      — Word document   (requires Pandoc)
      pdf       — PDF             (requires Pandoc + a LaTeX engine)
      print-pdf — print-ready PDF (6×9", proper margins; requires Pandoc + XeLaTeX)
      lulu      — zip bundle for Lulu POD (interior PDF + cover PDF + README)
      mobi      — Kindle MOBI     (requires Pandoc)
      azw3      — Kindle AZW3     (requires Pandoc)
      audiobook — M4B or ZIP of MP3s (requires OPENAI_API_KEY)

    The output file is written to the story's export/ directory.
    If a cover image exists (generated via 'cover' command), it is included in
    epub exports automatically.

    \b
    Examples:
      quillan --world noir export my_story
      quillan --world noir export my_story --format docx
      quillan --world noir export my_story --format print-pdf
      quillan --world noir export my_story --format lulu
    """
    from quillan.export import export_story

    settings: Settings = ctx.obj["settings"]
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    if fmt == "audiobook":
        from quillan.tts import export_audiobook
        try:
            out_path = asyncio.run(
                export_audiobook(paths, world, canon, series, story, settings,
                                 on_progress=click.echo)
            )
            click.echo(f"Exported to: {out_path}")
        except (FileNotFoundError, ValueError, ImportError) as exc:
            click.echo(f"Export failed: {exc}", err=True)
            sys.exit(1)
        return

    # Pass cover_path to export if it exists
    cover_path: Path | None = None
    candidate = paths.cover_image(world, canon, series, story)
    if candidate.exists():
        cover_path = candidate

    try:
        result = export_story(
            paths, world, canon, series, story, fmt=fmt, settings=settings,
            cover_path=cover_path,
        )
        if result.degraded:
            click.echo(
                f"Warning: {fmt} export unavailable; saved as {result.fmt} instead.",
                err=True,
            )
        click.echo(f"Exported to: {result.path}")
    except (FileNotFoundError, ValueError, ImportError) as exc:
        click.echo(f"Export failed: {exc}", err=True)
        sys.exit(1)


@main.command("estimate")
@click.argument("story")
@click.option("--beats", "beats_mode", default="all", show_default=True,
              help="How many beats to estimate: 'all' or an integer.")
@click.option("--force", is_flag=True, default=False,
              help="Include already-drafted beats in the estimate.")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Output estimate as JSON.")
@click.pass_context
def estimate_cmd(ctx: click.Context, story: str, beats_mode: str, force: bool, as_json: bool) -> None:
    """Print a cost estimate for drafting STORY.

    Reads local artefacts only — no LLM calls are made.

    \b
    Examples:
      quillan --world noir estimate my_story
      quillan --world scifi estimate the_reckoning --beats 5
      quillan estimate my_story --json
    """
    import json as _json
    from quillan.estimate import estimate_draft_cost

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]
    settings: Settings = ctx.obj["settings"]

    result = estimate_draft_cost(
        paths, world, canon, series, story, settings,
        beats_mode=beats_mode,
        force=force,
    )

    if as_json:
        click.echo(_json.dumps(result.as_dict(), indent=2))
    else:
        if result.num_beats == 0:
            click.echo(
                "No beats pending (story not yet created, or all beats already drafted).\n"
                "Pass --force to include already-drafted beats.",
                err=True,
            )
            sys.exit(1)
        click.echo(f"\nEstimate for: {story}")
        for line in result.summary_lines():
            click.echo(line)
        click.echo()


@main.command("status")
@click.argument("story")
@click.pass_context
def status(ctx: click.Context, story: str) -> None:
    """Show planning and drafting progress for STORY.

    Checks which planning artifacts exist, how many beats have specs and
    drafted prose, and what export files have been produced.

    No LLM calls or writes are made — purely informational.

    \b
    Examples:
      quillan --world noir status my_story
      quillan --world scifi --series arc2 status the_reckoning
    """
    import yaml
    from quillan.structure.story import _extract_beat_ids

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    story_dir = paths.story(world, canon, series, story)
    if not story_dir.exists():
        click.echo(f"Error: story {story!r} not found.", err=True)
        click.echo(f"  Expected: {story_dir}", err=True)
        click.echo( "  Run: quillan create <idea_file>", err=True)
        sys.exit(1)

    click.echo(f"\nStory: {story}")
    click.echo(f"Path:  {story_dir}")

    # ── Planning artifacts ────────────────────────────────────────────────
    CHECK, CROSS = "✓", "✗"

    def mark(p: Path) -> str:
        return CHECK if p.exists() else CROSS

    artifacts = [
        ("Creative Brief",   paths.creative_brief(world, canon, series, story)),
        ("Story Spine",      paths.story_spine(world, canon, series, story)),
        ("Character Arcs",   paths.character_arcs(world, canon, series, story)),
        ("Subplot Register", paths.subplot_register(world, canon, series, story)),
        ("Outline",          paths.outline(world, canon, series, story)),
        ("Dependency Map",   paths.dependency_map(world, canon, series, story)),
    ]
    click.echo("\nPlanning Artifacts")
    for label, artifact_path in artifacts:
        click.echo(f"  {label:<20} {mark(artifact_path)}")

    # ── Beat coverage ─────────────────────────────────────────────────────
    click.echo("\nBeat Coverage")
    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        click.echo("  (outline not found — run 'create' first)")
    else:
        try:
            outline_data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
            beat_ids = _extract_beat_ids(outline_data)
        except Exception as exc:
            logger.warning("Could not parse outline for beat coverage: %s", exc)
            beat_ids = []

        if not beat_ids:
            click.echo("  (no beats found in outline)")
        else:
            total = len(beat_ids)
            specs = sum(
                1 for bid in beat_ids
                if paths.beat_spec(world, canon, series, story, bid).exists()
            )
            drafts = sum(
                1 for bid in beat_ids
                if paths.beat_draft(world, canon, series, story, bid).exists()
            )
            spec_pct = int(100 * specs / total)
            draft_pct = int(100 * drafts / total)
            click.echo(f"  Specs:  {specs:>3} / {total}   ({spec_pct:>3}%)")
            click.echo(f"  Drafts: {drafts:>3} / {total}   ({draft_pct:>3}%)")

            stale_ids = _find_stale_beats(paths, world, canon, series, story, beat_ids)
            n_stale = len(stale_ids)
            if n_stale > 0:
                click.echo(
                    f"  Stale:  {n_stale:>3} draft(s) have an updated spec "
                    f"— run 'draft --stale-only' to refresh"
                )
                if n_stale <= 5:
                    for bid in stale_ids:
                        click.echo(f"    {bid}")
                else:
                    click.echo(f"    ({n_stale} stale beats total)")

    # ── Exports ───────────────────────────────────────────────────────────
    click.echo("\nExports")
    export_dir = paths.story_export(world, canon, series, story)
    export_files = sorted(export_dir.iterdir()) if export_dir.exists() else []
    export_files = [f for f in export_files if f.is_file()]
    if not export_files:
        click.echo("  (none)")
    else:
        for f in export_files:
            size_kb = f.stat().st_size // 1024
            click.echo(f"  {f.name:<30} ({size_kb} KB)")

    # ── Cover & Lulu status ───────────────────────────────────────────────
    cover_p = paths.cover_image(world, canon, series, story)
    lulu_p = paths.lulu_bundle(world, canon, series, story)
    cover_line = f"  {CHECK} Cover image" if cover_p.exists() else f"  {CROSS} Cover image (run 'cover')"
    lulu_line = f"  {CHECK} Lulu bundle" if lulu_p.exists() else None
    click.echo("\nPrint / Cover")
    click.echo(cover_line)
    if lulu_line:
        click.echo(lulu_line)

    # ── Last run telemetry (cost) ─────────────────────────────────────────
    import json as _json
    runs_dir = paths.runs_dir()
    if runs_dir.exists():
        tel_files = sorted(runs_dir.glob("telemetry_*.json"))
        if tel_files:
            try:
                tel_data = _json.loads(tel_files[-1].read_text(encoding="utf-8"))
                cost = tel_data.get("estimated_cost_usd", 0.0)
                tokens = tel_data.get("total_tokens", 0)
                click.echo("\nLast Run")
                if cost > 0:
                    click.echo(f"  Estimated cost: ~${cost:.4f}  ({tokens:,} tokens)")
                elif tokens > 0:
                    click.echo(f"  Tokens: {tokens:,}  (model not in pricing table)")
            except Exception as exc:
                logger.warning("Could not read telemetry file: %s", exc)

    click.echo("")


@main.command("show-outline")
@click.argument("story")
@click.pass_context
def show_outline(ctx: click.Context, story: str) -> None:
    """Display the story outline in a readable format.

    Shows chapters, beat IDs, goals, word count targets, and draft status
    (drafted / pending) for each beat.

    \b
    Examples:
      quillan --world noir show-outline my_story
    """
    import yaml
    from quillan.structure.outline_editor import format_outline

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        click.echo(f"Error: no Outline.yaml found for story {story!r}.", err=True)
        sys.exit(1)

    try:
        outline_data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        click.echo(f"Error: Outline.yaml is not valid YAML: {exc}", err=True)
        sys.exit(1)

    click.echo(format_outline(outline_data, paths, world, canon, series, story))


@main.command("edit-outline")
@click.argument("story")
@click.pass_context
def edit_outline(ctx: click.Context, story: str) -> None:
    """Open the story outline in $EDITOR for direct editing.

    After the editor closes, Quillan validates the YAML structure and required
    fields. If validation passes, the outline is saved atomically and the
    dependency map is rebuilt. If it fails, the errors are shown and you can
    re-open the editor or abort.

    \b
    Examples:
      quillan --world noir edit-outline my_story
    """
    import yaml
    from quillan.structure.outline_editor import validate_outline, rebuild_dep_map_linear
    from quillan.io import atomic_write

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        click.echo(f"Error: no Outline.yaml found for story {story!r}.", err=True)
        sys.exit(1)

    while True:
        click.edit(filename=str(outline_path))

        # Validate the edited file
        try:
            text = outline_path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            click.echo(f"\nYAML parse error:\n  {exc}", err=True)
            if not click.confirm("Re-open editor?", default=True):
                click.echo("Aborted — original file unchanged.", err=True)
                sys.exit(1)
            continue

        errors = validate_outline(data)
        if not errors:
            break

        click.echo("\nValidation errors:", err=True)
        for e in errors:
            click.echo(f"  • {e}", err=True)
        if not click.confirm("Re-open editor?", default=True):
            click.echo("Aborted — original file unchanged.", err=True)
            sys.exit(1)

    # Rebuild dep map with linear fallback
    import json as _json
    dep_map = rebuild_dep_map_linear(data)
    dep_path = paths.dependency_map(world, canon, series, story)
    paths.ensure(dep_path)
    atomic_write(dep_path, _json.dumps(dep_map, indent=2))

    beat_count = sum(len(ch.get("beats", [])) for ch in data.get("chapters", []))
    click.echo(f"Outline saved. {beat_count} beat(s). Dependency map rebuilt.")


@main.command("add-beat")
@click.argument("story")
@click.option("--chapter", "chapter_num", type=int, required=True,
              help="Chapter number to append the new beat to.")
@click.option("--goal", required=True, help="What this beat must accomplish.")
@click.option("--title", default="", help="Short display title (defaults to goal).")
@click.option("--word-count", "word_count", type=int, default=1500,
              help="Target word count. Default: 1500.")
@click.pass_context
def add_beat(
    ctx: click.Context,
    story: str,
    chapter_num: int,
    goal: str,
    title: str,
    word_count: int,
) -> None:
    """Append a new beat to a chapter of STORY's outline.

    Automatically assigns the next sequential beat ID for that chapter,
    creates a stub beat_spec.yaml, and rebuilds the dependency map.

    \b
    Examples:
      quillan --world noir add-beat my_story \\
          --chapter 2 --goal "The detective finds the hidden ledger."
      quillan --world noir add-beat my_story \\
          --chapter 1 --goal "Confrontation at the docks." --word-count 2000
    """
    import yaml
    from quillan.structure.outline_editor import (
        add_beat_to_outline, rebuild_dep_map_linear, write_stub_beat_spec, validate_outline,
    )
    from quillan.io import atomic_write

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    outline_path = paths.outline(world, canon, series, story)
    if not outline_path.exists():
        click.echo(f"Error: no Outline.yaml found for story {story!r}.", err=True)
        sys.exit(1)

    try:
        outline_data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        click.echo(f"Error: Outline.yaml is not valid YAML: {exc}", err=True)
        sys.exit(1)

    try:
        updated_outline, new_beat_id = add_beat_to_outline(
            outline_data, chapter_num, goal, title=title, word_count=word_count
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    # Validate before writing
    errors = validate_outline(updated_outline)
    if errors:
        for e in errors:
            click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Write updated outline
    atomic_write(outline_path, yaml.dump(updated_outline, allow_unicode=True, sort_keys=False))

    # Rebuild dep map
    import json as _json
    dep_map = rebuild_dep_map_linear(updated_outline)
    dep_path = paths.dependency_map(world, canon, series, story)
    paths.ensure(dep_path)
    atomic_write(dep_path, _json.dumps(dep_map, indent=2))

    # Create stub beat spec
    spec_path = write_stub_beat_spec(
        paths, world, canon, series, story, new_beat_id, goal, title=title, word_count=word_count
    )

    click.echo(
        f"Added beat {new_beat_id} to Chapter {chapter_num}.\n"
        f"  Goal: {goal}\n"
        f"  Spec: {spec_path}\n"
        f"  Dependency map rebuilt."
    )


@main.command("list")
@click.option(
    "--world", "filter_world", default=None,
    help="Show only stories in this world. Default: all worlds.",
)
@click.option(
    "--canon", "filter_canon", default=None,
    help="Show only stories in this canon. Default: all canons.",
)
@click.option(
    "--series", "filter_series", default=None,
    help="Show only stories in this series. Default: all series.",
)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    filter_world: str | None,
    filter_canon: str | None,
    filter_series: str | None,
) -> None:
    """List all stories and their progress.

    Scans the data directory and prints a table showing each story's world,
    canon, series, beat count, draft completion percentage, and number of
    export files.

    \b
    Examples:
      quillan list                      # all stories
      quillan list --world noir         # only stories in 'noir' world
      quillan list --canon mirror_timeline
    """
    paths: Paths = ctx.obj["paths"]

    rows = _collect_story_rows(paths, filter_world, filter_canon, filter_series)

    if not rows:
        click.echo("No stories found.")
        hint = []
        if filter_world:
            hint.append(f"--world {filter_world}")
        if filter_canon:
            hint.append(f"--canon {filter_canon}")
        if filter_series:
            hint.append(f"--series {filter_series}")
        if hint:
            click.echo(f"  (filtered by: {', '.join(hint)})")
        click.echo("  Run 'quillan create <idea_file>' to start your first story.")
        return

    # Column widths (min 6 to fit headers)
    w_world  = max(6, max(len(r[0]) for r in rows))
    w_canon  = max(6, max(len(r[1]) for r in rows))
    w_series = max(7, max(len(r[2]) for r in rows))
    w_story  = max(6, max(len(r[3]) for r in rows))

    header = (
        f"{'World':<{w_world}}  {'Canon':<{w_canon}}  "
        f"{'Series':<{w_series}}  {'Story':<{w_story}}  "
        f"{'Beats':>6}  {'Drafted':>8}  {'Exports':>7}"
    )
    sep = "-" * len(header)
    click.echo(header)
    click.echo(sep)

    for world_n, canon_n, series_n, story_n, total, drafted, n_exports in rows:
        pct = f"{int(100*drafted/total)}%" if total > 0 else "  —"
        drafted_col = f"{drafted}/{total} ({pct})"
        click.echo(
            f"{world_n:<{w_world}}  {canon_n:<{w_canon}}  "
            f"{series_n:<{w_series}}  {story_n:<{w_story}}  "
            f"{total:>6}  {drafted_col:>8}  {n_exports:>7}"
        )


def _collect_story_rows(
    paths: "Paths",
    filter_world: str | None,
    filter_canon: str | None,
    filter_series: str | None,
) -> list[tuple]:
    """Walk the filesystem and return a row tuple for every matching story."""
    import yaml as _yaml
    from quillan.structure.story import _extract_beat_ids

    worlds_root = paths.worlds_dir()
    if not worlds_root.exists():
        return []

    rows = []
    for world_dir in sorted(worlds_root.iterdir()):
        if not world_dir.is_dir():
            continue
        world_n = world_dir.name
        if filter_world and world_n != filter_world:
            continue

        canons_root = world_dir / "canons"
        if not canons_root.exists():
            continue

        for canon_dir in sorted(canons_root.iterdir()):
            if not canon_dir.is_dir():
                continue
            canon_n = canon_dir.name
            if filter_canon and canon_n != filter_canon:
                continue

            series_root = canon_dir / "series"
            if not series_root.exists():
                continue

            for series_dir in sorted(series_root.iterdir()):
                if not series_dir.is_dir():
                    continue
                series_n = series_dir.name
                if filter_series and series_n != filter_series:
                    continue

                stories_root = series_dir / "stories"
                if not stories_root.exists():
                    continue

                for story_dir in sorted(stories_root.iterdir()):
                    if not story_dir.is_dir():
                        continue
                    story_n = story_dir.name

                    # Beat stats from outline
                    outline_path = paths.outline(world_n, canon_n, series_n, story_n)
                    total_beats = 0
                    drafted_beats = 0
                    if outline_path.exists():
                        try:
                            data = _yaml.safe_load(
                                outline_path.read_text(encoding="utf-8")
                            ) or {}
                            beat_ids = _extract_beat_ids(data)
                            total_beats = len(beat_ids)
                            drafted_beats = sum(
                                1 for bid in beat_ids
                                if paths.beat_draft(
                                    world_n, canon_n, series_n, story_n, bid
                                ).exists()
                            )
                        except Exception as exc:
                            logger.warning("Could not parse outline for story %r: %s", story_n, exc)

                    # Export file count
                    export_dir = paths.story_export(world_n, canon_n, series_n, story_n)
                    n_exports = 0
                    if export_dir.exists():
                        n_exports = sum(1 for f in export_dir.iterdir() if f.is_file())

                    rows.append((
                        world_n, canon_n, series_n, story_n,
                        total_beats, drafted_beats, n_exports,
                    ))
    return rows


@main.command("import-story")
@click.argument("manuscript_file", type=click.Path(exists=True))
@click.option(
    "--story", "story_name", default=None,
    help="Story slug for this import (default: derived from filename). "
         "Must match [a-z0-9_-] — spaces and special characters are replaced.",
)
@click.option(
    "--target-words", "target_words", default=1500, show_default=True,
    help="Target word count per beat when clustering the manuscript. "
         "Splits always respect paragraph boundaries.",
)
@click.option(
    "--plan", "run_planning", is_flag=True, default=False,
    help="After writing beat drafts, also run the full planning pipeline "
         "(Story_Spine, Character_Arcs, Conflict_Map, etc.). "
         "Requires API keys and makes LLM calls.",
)
@click.pass_context
def import_story_cmd(
    ctx: click.Context,
    manuscript_file: str,
    story_name: str | None,
    target_words: int,
    run_planning: bool,
) -> None:
    """Import an existing manuscript as a Quillan2 story.

    Parses MANUSCRIPT_FILE (Markdown, plain text, or DOCX) into chapters and
    beats, writes a Beat_Draft.md for each beat, and generates a stub
    Outline.yaml, beat_spec.yaml files, and a dependency_map.json.

    \b
      .md / .txt — headings (# or ##) delimit chapters
      .docx      — Heading 1/Heading 2 paragraph styles delimit chapters

    After import the story appears in 'quillan list' and can be drafted
    (to regenerate or improve beats), exported, or published normally.

    \b
    Examples:
      quillan --world noir import-story my_novel.md
      quillan import-story manuscript.docx --story my_book --target-words 2000
      quillan import-story draft.md --plan   # also generate planning artifacts
    """
    from quillan.ingest import ingest_manuscript, _sanitize_story_name

    settings: Settings = ctx.obj["settings"]
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    src = Path(manuscript_file)
    derived = story_name or _sanitize_story_name(src.stem)

    llm = tel = None
    if run_planning:
        llm, tel = _make_llm_and_telemetry(ctx)

    async def _run() -> None:
        result = await ingest_manuscript(
            src,
            paths,
            world,
            canon,
            series,
            derived,
            llm=llm,
            settings=settings,
            target_words_per_beat=target_words,
            run_planning=run_planning,
            on_progress=click.echo,
        )
        click.echo(f"\nImported as story: {result}")
        click.echo(f"Data dir: {paths.story(world, canon, series, result)}")
        if not run_planning:
            click.echo(
                "\nTip: edit the stub Outline.yaml and beat specs, then run:\n"
                f"  quillan --world {world} draft {result}"
            )

    try:
        asyncio.run(_run())
    finally:
        if tel:
            tel.finalize()


@main.command("delete")
@click.argument("story")
@click.option(
    "--force", is_flag=True, default=False,
    help="Skip the confirmation prompt and delete immediately.",
)
@click.pass_context
def delete_cmd(ctx: click.Context, story: str, force: bool) -> None:
    """Permanently delete STORY and all its files.

    Removes the story directory (beat specs, drafts, continuity, exports)
    from the filesystem. This action cannot be undone.

    \b
    Examples:
      quillan --world noir delete my_story
      quillan --world noir delete my_story --force
    """
    import shutil

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    story_dir = paths.story(world, canon, series, story)
    if not story_dir.exists():
        click.echo(f"Error: story {story!r} not found at {story_dir}", err=True)
        sys.exit(1)

    if not force:
        click.confirm(
            f"Delete story {story!r} and all its files at {story_dir}?",
            abort=True,
        )

    shutil.rmtree(story_dir)
    click.echo(f"Deleted: {story_dir}")


@main.command("add-sample")
@click.argument("story")
@click.argument("source")
@click.option(
    "--extract-profile/--no-extract-profile",
    default=False,
    help="After adding the sample, run LLM analysis to update the style fingerprint profile. "
         "Requires API keys.",
)
@click.pass_context
def add_sample(ctx: click.Context, story: str, source: str, extract_profile: bool) -> None:
    """Add a prose style sample to STORY's style reference.

    SOURCE can be a file path or a short text excerpt passed directly.
    If SOURCE is an existing file, its contents are read. Otherwise SOURCE
    is treated as literal text.

    Samples are stored in the story's structure/style_reference/samples.md
    and are injected into every beat's context bundle during drafting.
    Run this command multiple times to add more samples — each new sample
    is appended, separated by a horizontal rule.

    Use --extract-profile to run an LLM analysis of all samples and write a
    structured style fingerprint to style_reference/style_profile.yaml. The
    fingerprint is also injected into every beat's context bundle, giving the
    model a concise style guide without re-reading raw samples each time.

    \b
    Examples:
      quillan --world noir add-sample my_story chapter1.md
      quillan --world noir add-sample my_story "The rain fell in grey curtains."
      quillan --world noir add-sample my_story samples.md --extract-profile
    """
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]
    settings = ctx.obj["settings"]

    story_dir = paths.story(world, canon, series, story)
    if not story_dir.exists():
        click.echo(f"Error: story {story!r} not found.", err=True)
        sys.exit(1)

    # Resolve source: try as file path first, fall back to literal text
    source_path = Path(source)
    if source_path.exists() and source_path.is_file():
        try:
            text = source_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            click.echo(f"Error reading file {source_path}: {exc}", err=True)
            sys.exit(1)
        label = f"Source: {source_path.name}"
    else:
        text = source.strip()
        label = "Source: inline text"

    if not text:
        click.echo("Error: sample text is empty.", err=True)
        sys.exit(1)

    samples_path = paths.style_samples(world, canon, series, story)
    paths.ensure(samples_path)

    separator = "\n\n---\n\n"
    if samples_path.exists() and samples_path.stat().st_size > 0:
        existing = samples_path.read_text(encoding="utf-8")
        new_content = existing.rstrip() + separator + text + "\n"
    else:
        new_content = text + "\n"

    samples_path.write_text(new_content, encoding="utf-8")

    word_count = len(text.split())
    click.echo(
        f"Added style sample ({word_count} words, {label}).\n"
        f"Samples file: {samples_path}"
    )

    if extract_profile:
        if not settings.has_api_keys:
            click.echo(
                "Warning: --extract-profile requires API keys. "
                "Run 'quillan doctor' to check configuration.",
                err=True,
            )
        else:
            llm, telemetry = _make_llm_and_telemetry(ctx)
            click.echo("Extracting style fingerprint…")
            try:
                profile_path = asyncio.run(
                    _extract_style_profile_async(paths, world, canon, series, story, llm, settings)
                )
                if profile_path:
                    click.echo(f"Style profile written: {profile_path}")
                else:
                    click.echo("Style profile extraction returned no result.", err=True)
            finally:
                telemetry.finalize()


async def _extract_style_profile_async(paths, world, canon, series, story, llm, settings):
    """Thin async wrapper so add_sample can call asyncio.run()."""
    from quillan.structure.style import extract_style_profile
    return await extract_style_profile(paths, world, canon, series, story, llm, settings)


@main.command("character-voice")
@click.argument("story")
@click.argument("character_name")
@click.option(
    "--regen", is_flag=True, default=False,
    help="Regenerate the profile even if one already exists.",
)
@click.pass_context
def character_voice(
    ctx: click.Context, story: str, character_name: str, regen: bool
) -> None:
    """Generate a voice profile for CHARACTER_NAME in STORY.

    The profile captures speech patterns, vocabulary level, verbal tics, and
    emotional tells, and is injected into every beat's context bundle when
    that character appears in the beat spec.

    Requires API keys. Run multiple times to profile different characters.

    \b
    Examples:
      quillan --world noir character-voice my_story "Detective Marlowe"
      quillan --world noir character-voice my_story "The Widow" --regen
    """
    from quillan.structure.dialogue import character_slug

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]
    settings = ctx.obj["settings"]

    story_dir = paths.story(world, canon, series, story)
    if not story_dir.exists():
        click.echo(f"Error: story {story!r} not found.", err=True)
        sys.exit(1)

    slug = character_slug(character_name)
    profile_path = paths.voice_profile(world, canon, series, story, slug)

    if profile_path.exists() and not regen:
        click.echo(
            f"Voice profile for {character_name!r} already exists.\n"
            f"  {profile_path}\n"
            "Use --regen to regenerate it."
        )
        return

    _require_api_keys(settings)
    llm, telemetry = _make_llm_and_telemetry(ctx)

    click.echo(f"Generating voice profile for {character_name!r}…")
    try:
        result = asyncio.run(
            _generate_voice_profile_async(
                character_name, paths, world, canon, series, story, llm, settings
            )
        )
    finally:
        telemetry.finalize()

    if result:
        click.echo(f"Voice profile written: {result}")
    else:
        click.echo("Voice profile generation failed (LLM error).", err=True)
        sys.exit(1)


async def _generate_voice_profile_async(character_name, paths, world, canon, series, story,
                                        llm, settings):
    from quillan.structure.dialogue import generate_voice_profile
    return await generate_voice_profile(
        character_name, paths, world, canon, series, story, llm, settings
    )


@main.command("revise")
@click.argument("story")
@click.argument("beat_id")
@click.option(
    "--notes", "notes_text", default=None, metavar="TEXT",
    help="Revision instructions as inline text.",
)
@click.option(
    "--notes-file", "notes_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    default=None,
    help="Read revision instructions from a file.",
)
@click.pass_context
def revise_cmd(
    ctx: click.Context,
    story: str,
    beat_id: str,
    notes_text: str | None,
    notes_file: str | None,
) -> None:
    """Apply targeted revision notes to an existing beat draft.

    Exactly one of --notes or --notes-file must be provided.

    The existing draft is snapshotted to the versions/ directory before
    being overwritten, so the original is always recoverable via
    'quillan restore-beat'.

    \b
    Examples:
      quillan --world noir revise my_story C1-S1-B2 \\
          --notes "Replace the gun with a knife throughout."
      quillan --world noir revise my_story C2-S1-B1 \\
          --notes-file revision_C2B1.txt
    """
    if not notes_text and not notes_file:
        click.echo("Error: provide --notes TEXT or --notes-file PATH.", err=True)
        sys.exit(1)
    if notes_text and notes_file:
        click.echo("Error: --notes and --notes-file are mutually exclusive.", err=True)
        sys.exit(1)

    if notes_file:
        try:
            notes_text = Path(notes_file).read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            click.echo(f"Error reading notes file: {exc}", err=True)
            sys.exit(1)

    if not notes_text:
        click.echo("Error: revision notes are empty.", err=True)
        sys.exit(1)

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]
    settings = ctx.obj["settings"]

    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    if not draft_path.exists():
        click.echo(
            f"Error: no draft found for beat {beat_id!r} in story {story!r}. "
            "Draft the beat first.",
            err=True,
        )
        sys.exit(1)

    llm, telemetry = _make_llm_and_telemetry(ctx)

    click.echo(f"Revising {beat_id}…")

    def _on_chunk(bid: str, chunk: str) -> None:
        click.echo(chunk, nl=False)

    try:
        ok = asyncio.run(
            _run_revise(paths, world, canon, series, story, beat_id, notes_text, llm, settings,
                        on_chunk=_on_chunk)
        )
    finally:
        telemetry.finalize()

    if not ok:
        click.echo("\nRevision failed (LLM error).", err=True)
        sys.exit(1)

    click.echo(f"\nRevision complete: {draft_path}")


async def _run_revise(paths, world, canon, series, story, beat_id, notes, llm, settings,
                      on_chunk=None):
    from quillan.draft.revise import revise_beat
    from quillan.hooks import run_hooks
    ok = await revise_beat(
        paths, world, canon, series, story, beat_id, notes, llm, settings, on_chunk=on_chunk
    )
    if ok:
        await run_hooks(
            "post_revise", paths, world, canon, series, story,
            extra_env={
                "QUILLAN_BEAT_ID": beat_id,
                "QUILLAN_DRAFT_PATH": str(paths.beat_draft(world, canon, series, story, beat_id)),
            },
        )
    return ok


def _parse_beats_arg(
    beats_arg: str,
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
) -> list[str] | None:
    """Parse the --beats argument into a beat ID list (or None = all).

    - "all"             → None  (caller uses all beats from outline)
    - integer string    → first N beat IDs from outline
    - comma-separated   → explicit beat ID list
    """
    beats_arg = beats_arg.strip()
    if beats_arg == "all":
        return None

    # Integer → first N
    if beats_arg.isdigit():
        n = int(beats_arg)
        import yaml
        outline_path = paths.outline(world, canon, series, story)
        if not outline_path.exists():
            return None
        from quillan.structure.story import _extract_beat_ids
        outline_data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
        return _extract_beat_ids(outline_data)[:n]

    # Comma-separated beat IDs
    return [b.strip() for b in beats_arg.split(",") if b.strip()]


def _find_stale_beats(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    beat_ids: list[str],
) -> list[str]:
    """Return beat IDs where beat_spec.yaml is newer than Beat_Draft.md.

    A beat is stale if spec exists AND draft exists AND spec.st_mtime > draft.st_mtime.
    Beats with no draft yet are NOT stale (just unwritten).
    Returns a sorted list for determinism.
    """
    stale = []
    for bid in beat_ids:
        spec_path = paths.beat_spec(world, canon, series, story, bid)
        draft_path = paths.beat_draft(world, canon, series, story, bid)
        if spec_path.exists() and draft_path.exists():
            if spec_path.stat().st_mtime > draft_path.stat().st_mtime:
                stale.append(bid)
    return sorted(stale)


@main.command("regen-specs")
@click.argument("story")
@click.option(
    "--beats", "beats_arg", default="all", show_default=True,
    help="'all' to regenerate every beat, an integer N for the first N beats, "
         "or a comma-separated list of beat IDs (e.g. 'C1-S1-B1,C1-S1-B2').",
)
@click.option(
    "--cascade", "cascade", is_flag=True, default=False,
    help="Also regenerate every beat that transitively depends on --beats.",
)
@click.option(
    "--dry-run", "dry_run", is_flag=True, default=False,
    help="Print which beats would be regenerated without making any LLM calls or writes.",
)
@click.pass_context
def regen_specs(ctx: click.Context, story: str, beats_arg: str, cascade: bool, dry_run: bool) -> None:
    """Regenerate beat specs from current planning artifacts.

    Use after editing Creative_Brief.yaml, Story_Spine.yaml, or
    Character_Arcs.yaml to propagate planning changes into all beat specs.

    Existing beat_spec.yaml files are deleted and rewritten. Beat drafts and
    continuity data are left untouched.

    \b
    Examples:
      # Regenerate all beat specs after editing the story spine
      quillan --world noir regen-specs my_story

      # Regenerate only the first 5 beats
      quillan --world noir regen-specs my_story --beats 5

      # Regenerate specific beats by ID
      quillan --world noir regen-specs my_story --beats C1-S1-B1,C1-S1-B3

      # Regenerate B1 and all beats that depend on it
      quillan --world noir regen-specs my_story --beats C1-S1-B1 --cascade
    """
    from quillan.structure.story import regen_beat_specs

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    llm, telemetry = _make_llm_and_telemetry(ctx)

    async def _run() -> None:
        beats = _parse_beats_arg(beats_arg, paths, world, canon, series, story)
        if cascade:
            if beats is None:
                click.echo(
                    "--cascade with --beats all is redundant; regenerating all beats.",
                    err=True,
                )
            else:
                from quillan.pipeline.dag import compute_dependents
                from quillan.validate import validate_dependency_map
                dep_map_data = validate_dependency_map(
                    paths.dependency_map(world, canon, series, story)
                )
                beats = compute_dependents(dep_map_data, beats)

        if dry_run:
            if beats is None:
                from quillan.validate import validate_dependency_map
                from quillan.pipeline.dag import compute_batches
                dep_path = paths.dependency_map(world, canon, series, story)
                if not dep_path.exists():
                    click.echo("Error: dependency_map.json not found — run 'create' first.", err=True)
                    sys.exit(1)
                dep_map_data = validate_dependency_map(dep_path)
                beats = [bid for batch in compute_batches(dep_map_data) for bid in batch]
            click.echo(f"Dry run — would regenerate {len(beats)} beat spec(s):")
            for bid in beats:
                click.echo(f"  {bid}")
            return

        label = beats_arg if beats_arg != "all" else "all"
        if cascade and beats is not None:
            label = f"{label} (cascade: {len(beats)} beats)"
        click.echo(f"Regenerating beat specs for story '{story}' (beats: {label})...")
        count = await regen_beat_specs(paths, world, canon, series, story, llm, beats=beats)
        click.echo(f"Done. {count} beat spec(s) regenerated.")

    try:
        asyncio.run(_run())
    finally:
        telemetry.finalize()


@main.command()
@click.option("--limit", default=20, show_default=True, type=int, help="Max runs to show.")
@click.option("--run-id", default=None, help="Show detail for one specific run ID.")
@click.pass_context
def runs(ctx: click.Context, limit: int, run_id: str | None) -> None:
    """Show recent run history with token and cost summaries.

    Reads telemetry summary JSON files written by ``draft`` and other
    pipeline commands.  Displays a table of recent runs with duration,
    LLM call counts, token usage, cache hits, and estimated cost.

    \b
    Examples:
      quillan runs
      quillan runs --limit 5
      quillan runs --run-id 20250312_141023_456789
    """
    from quillan.paths import Paths
    from quillan.telemetry import Telemetry

    settings = ctx.obj.get("settings") or __import__("quillan.config", fromlist=["Settings"]).Settings()
    paths = Paths(settings.data_dir)
    summaries = Telemetry.load_run_summaries(paths.runs_dir(), limit=limit)

    if not summaries:
        click.echo("No run history found. Run 'quillan draft' first to generate telemetry.")
        return

    if run_id:
        match = next((s for s in summaries if s.get("run_id") == run_id), None)
        if not match:
            click.echo(f"Run ID not found: {run_id}", err=True)
            ctx.exit(1)
            return
        click.echo(f"Run: {match['run_id']}")
        click.echo(f"  Duration:   {match.get('elapsed_seconds', 0):.1f}s")
        click.echo(f"  LLM calls:  {match.get('total_calls', 0)}")
        click.echo(f"  Cache hits: {match.get('cache_hits', 0)}")
        click.echo(f"  Tokens:     {match.get('total_tokens', 0):,}")
        click.echo(f"  Cost:       ${match.get('estimated_cost_usd', 0):.4f}")
        by_provider = match.get("calls_by_provider", {})
        if by_provider:
            click.echo("  By provider:")
            for p, tok in sorted(by_provider.items()):
                click.echo(f"    {p}: {tok:,} tokens")
        return

    # Table view
    header = f"{'Run ID':<26}  {'Dur(s)':>6}  {'Calls':>5}  {'Cache':>5}  {'Tokens':>9}  {'Cost USD':>9}"
    click.echo(header)
    click.echo("-" * len(header))
    for s in summaries:
        run_str = s.get("run_id", "?")[:26]
        dur = s.get("elapsed_seconds", 0)
        calls = s.get("total_calls", 0)
        cache = s.get("cache_hits", 0)
        tokens = s.get("total_tokens", 0)
        cost = s.get("estimated_cost_usd", 0)
        click.echo(f"{run_str:<26}  {dur:>6.1f}  {calls:>5}  {cache:>5}  {tokens:>9,}  {cost:>9.4f}")


@main.command()
def selftest() -> None:
    """Run built-in diagnostics — no API keys or network needed.

    Verifies that core modules (paths, I/O, validation, token counting,
    dependency graph, state patching, config) all work correctly.
    Exits with status 0 if all checks pass, 1 if any fail.

    Run this after installation to confirm everything is working before
    setting up API keys.
    """
    failures: list[str] = []
    passed: int = 0

    def check(name: str, fn) -> None:
        nonlocal passed
        try:
            fn()
            click.echo(f"  [PASS] {name}")
            passed += 1
        except Exception as exc:
            click.echo(f"  [FAIL] {name}: {exc}")
            failures.append(name)

    click.echo("Running Quillan2 selftest...")

    # paths
    def test_paths():
        from quillan.paths import Paths
        p = Paths(Path("/tmp/q2test"))
        assert p.worlds_dir() == Path("/tmp/q2test/worlds")
        assert p.beat("w", "c", "s", "st", "C1-S1-B1").name == "C1-S1-B1"

    # io
    def test_io():
        import tempfile
        from quillan.io import atomic_write, cap_file_chars

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.txt"
            atomic_write(p, "hello world")
            assert p.read_text() == "hello world"

            # cap_file_chars: text fits, no change
            cap_file_chars(p, 100)
            assert p.read_text() == "hello world"

            # cap_file_chars: text too long
            long_text = "A" * 60 + "B" * 40
            atomic_write(p, long_text)
            cap_file_chars(p, 50)
            result = p.read_text()
            assert "[...middle trimmed...]" in result

    # validate
    def test_validate():
        from quillan.validate import validate_beat_id, py_extract_json
        assert validate_beat_id("C1-S1-B1") is True
        assert validate_beat_id("bad") is False
        d = py_extract_json('{"a": 1, "b": 2}')
        assert d["a"] == 1

    # token_tool
    def test_tokens():
        from quillan.token_tool import estimate_tokens, trim_to_tokens
        n = estimate_tokens("Hello world")
        assert n > 0
        text = "A" * 10000
        trimmed = trim_to_tokens(text, 10)
        assert len(trimmed) < len(text)

    # dag
    def test_dag():
        from quillan.pipeline.dag import compute_batches
        dep_map = {
            "dependencies": {
                "C1-S1-B1": [],
                "C1-S1-B2": ["C1-S1-B1"],
                "C1-S1-B3": ["C1-S1-B1"],
                "C1-S1-B4": ["C1-S1-B2", "C1-S1-B3"],
            }
        }
        batches = compute_batches(dep_map)
        assert batches[0] == ["C1-S1-B1"]
        assert set(batches[1]) == {"C1-S1-B2", "C1-S1-B3"}
        assert batches[2] == ["C1-S1-B4"]

    # state
    def test_state():
        from quillan.continuity.state import apply_state_patch
        state = {"characters": {"Alice": {"location": "home"}}, "events": []}
        patch = {
            "set": {"characters.Alice.location": "forest"},
            "append": {"events": "Alice entered the forest"},
            "delete": [],
        }
        new = apply_state_patch(state, patch)
        assert new["characters"]["Alice"]["location"] == "forest"
        assert "Alice entered the forest" in new["events"]

    # config
    def test_config():
        from quillan.config import Settings
        s = Settings(data_dir=Path("/tmp"))
        assert s.model_for_stage("planning", 0) == "gpt-4o-mini"  # budget
        assert s.model_for_stage("planning", 1) == "gpt-4o"       # quality escalation
        assert s.provider_for_stage("draft", 0) == "xai"
        assert s.provider_for_stage("draft", 2) == "openai"       # cross-provider escape
        assert s.has_api_keys is False

    # creative_brief
    def test_creative_brief():
        import asyncio as _asyncio
        from quillan.structure.creative_brief import classify_specificity, _stub_creative_brief

        class _LLM:
            class settings:
                has_api_keys = False

        result = _asyncio.run(classify_specificity("A story", _LLM()))
        assert "needs_interview" in result
        stub = _stub_creative_brief("test idea")
        assert "voice" in stub and "arc_intent" in stub

    # story_spine
    def test_story_spine():
        from quillan.structure.story_spine import _stub_spine, get_beat_arc_context
        spine = _stub_spine(["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"])
        assert "structure" in spine
        assert all(bid in spine["beat_tension"] for bid in ["C1-S1-B1", "C1-S1-B2", "C1-S1-B3"])
        ctx = get_beat_arc_context("C1-S1-B1", spine)
        assert "arc_position" in ctx and "tension_level" in ctx

    # bundle
    def test_bundle():
        import tempfile as _tempfile
        from quillan.paths import Paths as _Paths
        from quillan.draft.bundle import _build_author_context
        with _tempfile.TemporaryDirectory() as td:
            p = _Paths(Path(td))
            result = _build_author_context(p, "w", "c", "s", "st", {})
            assert result == ""  # no data → no section
            result2 = _build_author_context(
                p, "w", "c", "s", "st",
                {"arc_position": "setup", "tension_level": 3}
            )
            assert "Author Context" in result2

    check("paths", test_paths)
    check("io", test_io)
    check("validate", test_validate)
    check("token_tool", test_tokens)
    check("dag", test_dag)
    check("state", test_state)
    check("config", test_config)
    check("creative_brief", test_creative_brief)
    check("story_spine", test_story_spine)
    check("bundle", test_bundle)

    click.echo("")
    if failures:
        click.echo(f"FAILED: {len(failures)} test(s): {failures}", err=True)
        sys.exit(1)
    else:
        click.echo(f"All {passed} selftest checks passed.")
        click.echo("  Next: run 'quillan doctor' to check API keys, tools, and system readiness.")


@main.command()
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Check system readiness: Python, packages, external tools, API keys, disk space.

    Prints a categorized report with [OK], [WARN], or [FAIL] for each check.
    Exits with status 0 if no failures, 1 if any [FAIL] items are found.

    \b
    Examples:
      quillan doctor
      quillan --data-dir /var/lib/quillan doctor
    """
    from quillan.doctor import run_doctor_checks

    settings = ctx.obj.get("settings") if ctx.obj else None
    data_dir = settings.data_dir if settings else None
    result = run_doctor_checks(data_dir)

    _LABELS = {"python": "Python", "packages": "Required packages",
               "optional": "Optional packages", "tools": "External tools",
               "api_keys": "API keys", "data_dir": "Data directory", "disk": "Disk space"}
    _STATUS = {"ok": "[OK]  ", "warn": "[WARN]", "fail": "[FAIL]"}

    current_cat = None
    for item in result.items:
        if item.category != current_cat:
            click.echo(_LABELS.get(item.category, item.category) + ":")
            current_cat = item.category
        click.echo(f"  {_STATUS[item.status]} {item.message}")

    click.echo("")
    click.echo(f"Doctor summary: {result.ok_count} OK, {result.warn_count} WARN, {result.fail_count} FAIL")
    if result.fail_count:
        ctx.exit(1)


_JWT_DEFAULT_SECRET = "dev-secret-change-in-production"


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Network interface to bind to. Use 0.0.0.0 to accept connections from other machines.")
@click.option("--port", default=8000, show_default=True, type=int,
              help="TCP port number to listen on.")
@click.option("--dev", "dev_mode", is_flag=True, default=False,
              help="Allow starting with the default JWT secret (localhost dev only). "
                   "Never use this flag on a shared or internet-facing server.")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, dev_mode: bool) -> None:
    """Start the Quillan2 web API server.

    Launches a FastAPI server with a REST API and a background job queue.
    Supports user registration, JWT authentication, and async story creation.

    Requires the 'web' optional dependency:

    \b
      pip install quillan[web]

    \b
    QUILLAN_JWT_SECRET must be set to a random string before starting.
    Generate one with: openssl rand -hex 32

    \b
    Examples:
      quillan serve                          # localhost:8000
      quillan serve --host 0.0.0.0 --port 8080
      quillan --data-dir /var/lib/quillan serve
      quillan serve --dev                   # local dev, no secret required
    """
    import os

    try:
        import uvicorn
    except ImportError:
        click.echo("uvicorn required: pip install quillan[web]", err=True)
        sys.exit(1)

    jwt_secret = os.environ.get("QUILLAN_JWT_SECRET", _JWT_DEFAULT_SECRET)
    if jwt_secret == _JWT_DEFAULT_SECRET:
        if not dev_mode:
            click.echo(
                "Error: QUILLAN_JWT_SECRET is not set.\n"
                "The default secret is insecure for any non-localhost use.\n\n"
                "  Generate a secret:  export QUILLAN_JWT_SECRET=$(openssl rand -hex 32)\n"
                "  Local dev only:     quillan serve --dev",
                err=True,
            )
            sys.exit(1)
        click.echo(
            "Warning: running with default JWT secret — do not expose this server.",
            err=True,
        )

    settings: Settings = ctx.obj["settings"]
    os.environ["QUILLAN_DATA_DIR"] = str(settings.data_dir)

    click.echo(f"Starting Quillan2 web server at http://{host}:{port}")
    uvicorn.run("quillan.web.app:app", host=host, port=port, reload=False)


@main.command("restore-state")
@click.argument("story")
@click.argument("checkpoint", required=False)
@click.option("--list", "list_only", is_flag=True, default=False,
              help="List available checkpoints without restoring.")
@click.pass_context
def restore_state(ctx: click.Context, story: str, checkpoint: str | None, list_only: bool) -> None:
    """Restore continuity state from a checkpoint.

    STORY is the story name. CHECKPOINT is the checkpoint filename (without path).
    Omit CHECKPOINT to list available checkpoints.

    Checkpoints are created automatically before every state overwrite and stored
    in state/checkpoints/ as timestamped YAML files.

    \b
    Examples:
      quillan restore-state my_story --list
      quillan restore-state my_story 20240901_142530_123456_beat_01.yaml
    """
    from quillan.io import atomic_write

    _settings: Settings = ctx.obj["settings"]
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    ckpt_dir = paths.state_checkpoints_dir(world, canon, series, story)
    if not ckpt_dir.exists():
        click.echo(f"No checkpoints found for story '{story}'.", err=True)
        sys.exit(1)

    checkpoints = sorted(ckpt_dir.iterdir(), key=lambda p: p.name)
    if not checkpoints:
        click.echo(f"No checkpoints found in {ckpt_dir}.", err=True)
        sys.exit(1)

    if list_only or checkpoint is None:
        click.echo(f"Checkpoints for {world}/{canon}/{series}/{story}:")
        for ckpt in checkpoints:
            click.echo(f"  {ckpt.name}")
        if checkpoint is None and not list_only:
            click.echo(
                "\nRe-run with a checkpoint name to restore, or use --list to suppress this hint.",
                err=True,
            )
        return

    ckpt_path = ckpt_dir / checkpoint
    if not ckpt_path.exists():
        click.echo(f"Checkpoint not found: {ckpt_path}", err=True)
        click.echo("Use --list to see available checkpoints.")
        sys.exit(1)

    state_path = paths.state_current(world, canon, series, story)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(state_path, ckpt_path.read_text(encoding="utf-8"))
    click.echo(f"Restored state from checkpoint: {checkpoint}")
    click.echo(f"State written to: {state_path}")


@main.command("versions")
@click.argument("story")
@click.argument("beat_id")
@click.pass_context
def versions_cmd(ctx: click.Context, story: str, beat_id: str) -> None:
    """List saved draft versions for a beat.

    Shows all historical snapshots of Beat_Draft.md for BEAT_ID in STORY,
    ordered newest-first.  Use 'restore-beat' to switch to a previous version.

    \b
    Examples:
      quillan --world noir versions my_story C1-S1-B1
    """
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    ver_dir = paths.beat_versions_dir(world, canon, series, story, beat_id)
    if not ver_dir.exists():
        click.echo(f"No saved versions for {beat_id} in story {story!r}.")
        return

    files = sorted(ver_dir.glob("*.md"), reverse=True)
    if not files:
        click.echo(f"No saved versions for {beat_id} in story {story!r}.")
        return

    click.echo(f"\nVersions for {beat_id} ({story}):")
    click.echo(f"  {'Timestamp':<22}  {'Words':>6}  {'Bytes':>8}")
    click.echo(f"  {'-'*22}  {'-'*6}  {'-'*8}")
    for f in files:
        stat = f.stat()
        words = len(f.read_text(encoding="utf-8", errors="replace").split())
        click.echo(f"  {f.stem:<22}  {words:>6}  {stat.st_size:>8}")
    click.echo("\n  Current draft:")
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    if draft_path.exists():
        words = len(draft_path.read_text(encoding="utf-8", errors="replace").split())
        click.echo(f"    {words} words")
    else:
        click.echo("    (no current draft)")
    click.echo("")


@main.command("restore-beat")
@click.argument("story")
@click.argument("beat_id")
@click.argument("version")
@click.option(
    "--diff", "show_diff", is_flag=True, default=False,
    help="Show a unified diff of the version vs the current draft before restoring.",
)
@click.option(
    "--force", is_flag=True, default=False,
    help="Skip the confirmation prompt.",
)
@click.pass_context
def restore_beat_cmd(
    ctx: click.Context,
    story: str,
    beat_id: str,
    version: str,
    show_diff: bool,
    force: bool,
) -> None:
    """Restore a saved draft version for a beat.

    Copies the selected VERSION snapshot back to Beat_Draft.md.
    The current draft is automatically saved as a new snapshot first,
    so the restore itself is reversible.

    VERSION is the timestamp string shown by 'versions' (e.g. 20240901T142530Z).

    \b
    Examples:
      quillan --world noir versions my_story C1-S1-B1
      quillan --world noir restore-beat my_story C1-S1-B1 20240901T142530Z
      quillan --world noir restore-beat my_story C1-S1-B1 20240901T142530Z --diff
    """
    import difflib
    from quillan.draft.draft import snapshot_beat_draft
    from quillan.io import atomic_write

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    ver_path = paths.beat_version(world, canon, series, story, beat_id, version)
    if not ver_path.exists():
        click.echo(f"Error: version {version!r} not found for {beat_id}.", err=True)
        click.echo(f"  Run: quillan --world {world} versions {story} {beat_id}", err=True)
        sys.exit(1)

    old_prose = ver_path.read_text(encoding="utf-8", errors="replace")
    draft_path = paths.beat_draft(world, canon, series, story, beat_id)
    current_prose = draft_path.read_text(encoding="utf-8", errors="replace") if draft_path.exists() else ""

    if show_diff:
        diff = list(difflib.unified_diff(
            old_prose.splitlines(keepends=True),
            current_prose.splitlines(keepends=True),
            fromfile=f"version/{version}",
            tofile="current",
            lineterm="",
        ))
        if diff:
            click.echo("".join(diff))
        else:
            click.echo("(no differences)")
        click.echo("")

    if not force:
        click.confirm(
            f"Restore version {version!r} as the current draft for {beat_id}?\n"
            f"  (Current draft will be saved as a new snapshot first.)",
            abort=True,
        )

    # Snapshot current draft first (so the restore itself is reversible),
    # then write the target version. Reading old_prose before snapshotting
    # avoids a same-second timestamp collision overwriting the target.
    snapshot_beat_draft(paths, world, canon, series, story, beat_id)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(draft_path, old_prose)
    click.echo(f"Restored version {version!r} to {beat_id}.")
    click.echo(f"  Word count: {len(old_prose.split())}")


@main.command("lock-beat")
@click.argument("story")
@click.argument("beat_id", required=False, default=None)
@click.option(
    "--all", "lock_all", is_flag=True, default=False,
    help="Lock all beats in the story.",
)
@click.pass_context
def lock_beat_cmd(ctx: click.Context, story: str, beat_id: str | None, lock_all: bool) -> None:
    """Prevent a beat from being (re)drafted.

    Creates a .lock sentinel file inside the beat directory. The draft pipeline
    will skip any locked beat, even when --force is used.

    \b
    Examples:
      quillan --world noir lock-beat my_story C1-S1-B1
      quillan --world noir lock-beat my_story --all
    """
    import yaml

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    if lock_all:
        outline_path = paths.outline(world, canon, series, story)
        if not outline_path.exists():
            click.echo(f"Error: no outline found for story {story!r}.", err=True)
            sys.exit(1)
        from quillan.validate import extract_beat_ids
        outline_data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
        beat_ids = extract_beat_ids(outline_data)
        if not beat_ids:
            click.echo("No beats found in outline.", err=True)
            sys.exit(1)
        for bid in beat_ids:
            lock_path = paths.beat_lock(world, canon, series, story, bid)
            paths.ensure(lock_path)
            lock_path.touch()
        click.echo(f"Locked {len(beat_ids)} beats in story {story!r}.")
    else:
        if not beat_id:
            click.echo("Error: provide BEAT_ID or use --all.", err=True)
            sys.exit(1)
        lock_path = paths.beat_lock(world, canon, series, story, beat_id)
        paths.ensure(lock_path)
        lock_path.touch()
        click.echo(f"Locked {beat_id} in story {story!r}.")


@main.command("unlock-beat")
@click.argument("story")
@click.argument("beat_id", required=False, default=None)
@click.option(
    "--all", "unlock_all", is_flag=True, default=False,
    help="Unlock all beats in the story.",
)
@click.pass_context
def unlock_beat_cmd(ctx: click.Context, story: str, beat_id: str | None, unlock_all: bool) -> None:
    """Allow a previously locked beat to be drafted again.

    Removes the .lock sentinel file from the beat directory.

    \b
    Examples:
      quillan --world noir unlock-beat my_story C1-S1-B1
      quillan --world noir unlock-beat my_story --all
    """
    import yaml

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    if unlock_all:
        outline_path = paths.outline(world, canon, series, story)
        if not outline_path.exists():
            click.echo(f"Error: no outline found for story {story!r}.", err=True)
            sys.exit(1)
        from quillan.validate import extract_beat_ids
        outline_data = yaml.safe_load(outline_path.read_text(encoding="utf-8")) or {}
        beat_ids = extract_beat_ids(outline_data)
        unlocked = 0
        for bid in beat_ids:
            lock_path = paths.beat_lock(world, canon, series, story, bid)
            if lock_path.exists():
                lock_path.unlink()
                unlocked += 1
        click.echo(f"Unlocked {unlocked} beat(s) in story {story!r}.")
    else:
        if not beat_id:
            click.echo("Error: provide BEAT_ID or use --all.", err=True)
            sys.exit(1)
        lock_path = paths.beat_lock(world, canon, series, story, beat_id)
        if not lock_path.exists():
            click.echo(f"{beat_id} is not locked.")
        else:
            lock_path.unlink()
            click.echo(f"Unlocked {beat_id} in story {story!r}.")


@main.command("continuity-check")
@click.argument("story")
@click.option(
    "--llm", "use_llm", is_flag=True, default=False,
    help="Run the LLM semantic drift phase in addition to the pure-Python checks. "
         "Requires API keys.",
)
@click.option(
    "--output", "output_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write the full report to a file (Markdown). Prints summary to stdout regardless.",
)
@click.pass_context
def continuity_check(
    ctx: click.Context,
    story: str,
    use_llm: bool,
    output_path: str | None,
) -> None:
    """Scan STORY for continuity drift across all beat drafts.

    Phase 1 (always): detects duplicate sentences and open threads that are
    never referenced in any beat draft.

    Phase 2 (--llm): feeds the story state, open threads, and recent beats to
    the LLM and asks it to identify semantic contradictions (requires API keys).

    \b
    Examples:
      quillan --world noir continuity-check my_story
      quillan --world noir continuity-check my_story --llm
      quillan --world noir continuity-check my_story --llm --output drift.md
    """
    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]
    settings = ctx.obj["settings"]

    story_dir = paths.story(world, canon, series, story)
    if not story_dir.exists():
        click.echo(f"Error: story {story!r} not found.", err=True)
        sys.exit(1)

    llm = None
    telemetry = None
    if use_llm:
        if not settings.has_api_keys:
            click.echo(
                "Error: --llm requires API keys. Run 'quillan doctor' to check.",
                err=True,
            )
            sys.exit(1)
        llm, telemetry = _make_llm_and_telemetry(ctx)

    try:
        report = asyncio.run(
            _run_continuity_check(paths, world, canon, series, story, settings, llm)
        )
    finally:
        if telemetry:
            telemetry.finalize()

    # ── Render report ─────────────────────────────────────────────────────
    lines: list[str] = [
        f"# Continuity Check: {story}",
        f"Beats checked: {report.checked_beats}  |  "
        f"LLM phase: {'yes' if report.llm_checked else 'no'}",
        "",
    ]

    if not report.issues:
        lines.append("No issues found.")
    else:
        by_kind = {
            "duplicate_sentence": "Duplicate sentences",
            "open_thread": "Orphaned open threads",
            "llm_flag": "LLM-detected drift",
            "llm_error": "LLM errors",
        }
        for kind, label in by_kind.items():
            group = [i for i in report.issues if i.kind == kind]
            if not group:
                continue
            lines.append(f"## {label} ({len(group)})")
            for issue in group:
                prefix = f"[{issue.beat_id}] " if issue.beat_id else ""
                tag = "WARN" if issue.severity == "warn" else "INFO"
                lines.append(f"- [{tag}] {prefix}{issue.description}")
            lines.append("")

        lines.append(
            f"Total: {report.warn_count} warning(s), {report.info_count} info item(s)."
        )

    report_text = "\n".join(lines)

    if output_path:
        from pathlib import Path as _Path
        _Path(output_path).write_text(report_text, encoding="utf-8")
        click.echo(f"Report written to: {output_path}")

    click.echo(report_text)

    if report.warn_count > 0:
        sys.exit(1)


@main.command("hooks")
@click.argument("story")
@click.pass_context
def hooks_list(ctx: click.Context, story: str) -> None:
    """List all active hooks for STORY.

    Searches story-level, world-level, and global hook directories and shows
    which hook scripts are installed. No hooks are executed.

    Hook scripts live in:
      <story>/hooks/<event>[.sh]
      <world>/hooks/<event>[.sh]
      <data_dir>/hooks/<event>[.sh]

    \b
    Examples:
      quillan --world noir hooks my_story
    """
    from quillan.hooks import HOOK_EVENTS, discover_hooks

    paths: Paths = ctx.obj["paths"]
    world: str = ctx.obj["world"]
    canon: str = ctx.obj["canon"]
    series: str = ctx.obj["series"]

    hook_dirs = [
        ("story", paths.story_hooks_dir(world, canon, series, story)),
        ("world", paths.world_hooks_dir(world)),
        ("global", paths.global_hooks_dir()),
    ]

    click.echo(f"Hook directories for story {story!r}:")
    for label, d in hook_dirs:
        status = "exists" if d.exists() else "not found"
        click.echo(f"  [{label}]  {d}  ({status})")
    click.echo("")

    found_any = False
    for event in sorted(HOOK_EVENTS):
        scripts = discover_hooks(event, paths, world, canon, series, story)
        if scripts:
            found_any = True
            for script in scripts:
                scope = "story" if "stories" in str(script) else (
                    "world" if "worlds" in str(script) else "global"
                )
                click.echo(f"  [{scope:6}]  {event:<25}  {script}")

    if not found_any:
        click.echo("No hooks installed.")

    click.echo("")
    click.echo(f"Supported events: {', '.join(sorted(HOOK_EVENTS))}")


async def _run_continuity_check(paths, world, canon, series, story, settings, llm):
    from quillan.continuity.drift import check_drift
    from quillan.hooks import run_hooks
    report = await check_drift(paths, world, canon, series, story, settings, llm=llm)
    await run_hooks(
        "post_continuity_check", paths, world, canon, series, story,
        extra_env={
            "QUILLAN_ISSUE_COUNT": str(len(report.issues)),
            "QUILLAN_WARN_COUNT": str(report.warn_count),
        },
    )
    return report
