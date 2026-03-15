"""Creative Brief: specificity classification, interview generation, brief generation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from quillan.llm import LLMClient
    from quillan.paths import Paths
from quillan.templates import get_prompt


class NeedsInterviewError(Exception):
    """Raised when a story idea is too vague and needs interview answers first."""

    def __init__(self, story: str, interview_path: Path) -> None:
        self.story = story
        self.interview_path = interview_path
        super().__init__(
            f"Story idea is too vague. Fill in {interview_path} and re-run 'create'."
        )


# ── Prompts ───────────────────────────────────────────────────────────────────





# ── Public API ────────────────────────────────────────────────────────────────

async def classify_specificity(
    idea_text: str,
    llm: "LLMClient",
) -> dict:
    """Return specificity classification for *idea_text*.

    When API keys are unavailable, falls back to a word-count heuristic:
    80+ words counts as specific enough to skip the interview.
    """
    from quillan.validate import py_extract_json

    if not llm.settings.has_api_keys:
        words = idea_text.split()
        score = min(len(words) / 80.0, 1.0)
        return {
            "specificity_score": round(score, 2),
            "needs_interview": score < 0.5,
            "detected_signals": {
                "has_named_characters": False,
                "has_explicit_theme": False,
                "has_stated_tone": False,
                "has_plot_structure": False,
            },
        }

    user_prompt = get_prompt("creative_brief_specificity_user").format(idea=idea_text[:2000])
    raw = await llm.call("planning", get_prompt("creative_brief_specificity_system"), user_prompt, mode="json")
    return py_extract_json(raw, ["specificity_score", "needs_interview"])


async def generate_creative_brief_interview(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    idea_text: str,
    llm: "LLMClient",
) -> Path:
    """Write Creative_Brief_Interview.md and return its path."""
    from quillan.io import atomic_write

    out_path = paths.creative_brief_interview(world, canon, series, story)
    paths.ensure(out_path)

    if llm.settings.has_api_keys:
        classification = await classify_specificity(idea_text, llm)
        signals = classification.get("detected_signals", {})
        missing_items = [k.replace("has_", "").replace("_", " ")
                         for k, v in signals.items() if not v]
        missing_str = ", ".join(missing_items) if missing_items else "context and depth"
        user_prompt = get_prompt("creative_brief_interview_user").format(
            idea=idea_text[:1000], missing=missing_str
        )
        content = await llm.call("planning", get_prompt("creative_brief_interview_system"), user_prompt)
    else:
        content = _stub_interview(story, idea_text)

    atomic_write(out_path, content)
    return out_path


async def generate_creative_brief(
    paths: "Paths",
    world: str,
    canon: str,
    series: str,
    story: str,
    idea_text: str,
    llm: "LLMClient",
) -> None:
    """Write Creative_Brief.yaml, loading any existing interview answers."""
    from quillan.io import atomic_write

    out_path = paths.creative_brief(world, canon, series, story)
    paths.ensure(out_path)

    interview_path = paths.creative_brief_interview(world, canon, series, story)
    answers_section = ""
    if interview_path.exists():
        answers_text = interview_path.read_text(encoding="utf-8")
        answers_section = f"Interview answers:\n{answers_text[:3000]}"

    if llm.settings.has_api_keys:
        user_prompt = get_prompt("creative_brief_user").format(
            idea=idea_text[:2000],
            answers_section=answers_section,
        )
        raw = await llm.call("planning", get_prompt("creative_brief_system"), user_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        atomic_write(out_path, raw)
    else:
        stub = _stub_creative_brief(idea_text)
        atomic_write(out_path, yaml.dump(stub, default_flow_style=False, allow_unicode=True))


# ── Offline stubs ─────────────────────────────────────────────────────────────

def _stub_interview(story: str, idea_text: str) -> str:
    """Minimal offline interview template."""
    return f"""\
# Creative Brief Interview

Your story idea is open-ended. Answer the questions below to help Quillan plan your story,
then save this file and re-run: quillan create <idea_file>

Story idea: {idea_text[:300]}

---

1. Who is your protagonist? What do they want, and what stands in their way?

**Answer:**

2. What is the emotional core of this story? What should the reader feel?

**Answer:**

3. What tone or atmosphere are you aiming for? (e.g. tense thriller, melancholic drama)

**Answer:**

4. Where does your protagonist end up by the end? What has changed for them?

**Answer:**

5. Are there any themes you want to explore? (e.g. identity, betrayal, redemption)

**Answer:**

6. What's the inciting event that disrupts the status quo?

**Answer:**

7. Are there important secondary characters? What roles do they play?

**Answer:**

8. Any subplots or parallel storylines?

**Answer:**

---

When done, save this file and re-run: quillan create <idea_file>
"""


def _stub_creative_brief(idea_text: str) -> dict:
    """Minimal offline creative brief."""
    return {
        "voice": {
            "prose_style": "clear and direct",
            "pov": "close third",
            "characteristic_patterns": ["measured pacing", "sensory grounding"],
            "avoid": ["purple prose", "head-hopping"],
        },
        "tone_palette": [
            {"register": "neutral", "chapters": [1]},
        ],
        "themes": [
            {"name": "TBD", "description": "To be developed from story idea"},
        ],
        "motifs": [],
        "arc_intent": f"Protagonist transforms through: {idea_text[:100].strip()}",
    }
