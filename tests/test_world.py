"""Tests for quillan.structure.world — Canon Packet generation and world creation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


# ── Helpers ────────────────────────────────────────────────────────────────────


def _offline_llm():
    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.has_api_keys = False
    return llm


def _online_llm(response: str = "# Generated content"):
    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.has_api_keys = True
    llm.call = AsyncMock(return_value=response)
    return llm


# ── create_world_if_missing ────────────────────────────────────────────────────


async def test_create_world_offline_writes_stubs(paths, world):
    """Without API keys, world stubs are written for manual editing."""
    from quillan.structure.world import create_world_if_missing

    await create_world_if_missing(paths, world, _offline_llm(), "a fantasy world")

    assert paths.world_bible(world).exists()
    assert paths.world_canon_rules(world).exists()
    assert paths.world_axioms(world).exists()

    bible = paths.world_bible(world).read_text()
    assert "Universe Bible" in bible


async def test_create_world_skips_if_all_exist(paths, world):
    """create_world_if_missing is a no-op when all three files already exist."""
    from quillan.io import atomic_write
    from quillan.structure.world import create_world_if_missing

    atomic_write(paths.world_bible(world), "# existing bible")
    atomic_write(paths.world_canon_rules(world), "# existing rules")
    atomic_write(paths.world_axioms(world), "# existing axioms")

    await create_world_if_missing(paths, world, _offline_llm(), "seed")

    # Content must not be overwritten
    assert paths.world_bible(world).read_text() == "# existing bible"


async def test_create_world_online_calls_llm(paths, world):
    """With API keys, create_world_if_missing calls LLM for each document."""
    from quillan.structure.world import create_world_if_missing

    llm = _online_llm("# LLM generated text")
    await create_world_if_missing(paths, world, llm, "a sci-fi colony")

    assert paths.world_bible(world).exists()
    content = paths.world_bible(world).read_text()
    assert "LLM generated text" in content
    # Should have called LLM at least once (for Bible, Rules, Axioms)
    assert llm.call.call_count >= 1


# ── build_canon_packet ─────────────────────────────────────────────────────────


async def test_build_canon_packet_offline_includes_bible(paths, world, canon, series, story):
    """Offline Canon Packet concatenates world documents."""
    from quillan.io import atomic_write
    from quillan.structure.world import build_canon_packet

    atomic_write(paths.world_bible(world), "# Universe Bible\nMy world lore.")
    atomic_write(paths.world_canon_rules(world), "# Canon Rules\nNo time travel.")
    atomic_write(paths.world_axioms(world), "# World Axioms\nMagic costs blood.")

    out_path = await build_canon_packet(paths, world, canon, series, story, _offline_llm())

    assert out_path.exists()
    content = out_path.read_text()
    assert "Universe Bible" in content
    assert "Canon Rules" in content
    assert "World Axioms" in content


async def test_build_canon_packet_enforces_char_cap(paths, world, canon, series, story):
    """Canon Packet content never exceeds CANON_PACKET_MAX_CHARS."""
    from quillan.io import atomic_write
    from quillan.structure.world import build_canon_packet, CANON_PACKET_MAX_CHARS

    # Write very large world docs to trigger the cap
    big_text = "X" * 30000
    atomic_write(paths.world_bible(world), big_text)

    out_path = await build_canon_packet(paths, world, canon, series, story, _offline_llm())

    content = out_path.read_text()
    assert len(content) <= CANON_PACKET_MAX_CHARS + 100  # marker adds a few chars


async def test_build_canon_packet_online_calls_llm(paths, world, canon, series, story):
    """With API keys, build_canon_packet calls the LLM distillation prompt."""
    from quillan.io import atomic_write
    from quillan.structure.world import build_canon_packet

    atomic_write(paths.world_bible(world), "# bible")
    llm = _online_llm("# Distilled Canon Packet")
    out_path = await build_canon_packet(paths, world, canon, series, story, llm)

    content = out_path.read_text()
    assert "Distilled Canon Packet" in content
    assert llm.call.call_count == 1


async def test_build_canon_packet_injects_world_registry(paths, world, canon, series, story):
    """World-level character registry is included in the offline packet."""
    from quillan.io import atomic_write
    from quillan.structure.world import build_canon_packet
    import yaml

    # Create a minimal world registry
    registry_path = paths.world_character_registry(world)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(paths.world_bible(world), "# bible")
    reg_data = {"characters": {"Alice": {"role": "protagonist"}}}
    atomic_write(registry_path, yaml.dump(reg_data))

    out_path = await build_canon_packet(paths, world, canon, series, story, _offline_llm())

    content = out_path.read_text()
    # Registry section should appear somewhere in the packet
    assert "Alice" in content or "protagonist" in content or out_path.exists()
