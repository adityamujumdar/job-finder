"""Smoke tests: verify skill files exist and CLAUDE.md routes to them."""

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]

SKILLS = ["jobhunter", "classify-jobs", "tailor-resume"]


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_md_exists(skill):
    """Each skill directory must contain a SKILL.md file."""
    path = ROOT / skill / "SKILL.md"
    assert path.exists(), f"Missing: {skill}/SKILL.md"
    content = path.read_text()
    assert len(content) > 100, f"{skill}/SKILL.md is suspiciously short ({len(content)} bytes)"


@pytest.mark.parametrize("skill", SKILLS)
def test_jac_skill_alias_exists(skill):
    """Each skill must have a .jac/skills/ alias file."""
    path = ROOT / ".jac" / "skills" / f"{skill}.md"
    assert path.exists(), f"Missing: .jac/skills/{skill}.md"
    content = path.read_text()
    assert f"{skill}/SKILL.md" in content, (
        f".jac/skills/{skill}.md doesn't reference {skill}/SKILL.md"
    )


def test_claude_md_has_routing():
    """CLAUDE.md must contain routing instructions for all three skills."""
    path = ROOT / "CLAUDE.md"
    assert path.exists(), "Missing: CLAUDE.md"
    content = path.read_text()
    for skill in SKILLS:
        assert f"`{skill}/SKILL.md`" in content, (
            f"CLAUDE.md missing routing for {skill}/SKILL.md"
        )


def test_claude_md_has_trigger_phrases():
    """CLAUDE.md must list trigger phrases so Claude can route natural language."""
    content = (ROOT / "CLAUDE.md").read_text()
    assert "find me jobs" in content.lower(), "Missing trigger phrase: 'find me jobs'"
    assert "build a resume" in content.lower(), "Missing trigger phrase: 'build a resume'"


def test_profile_example_no_netflix_lever():
    """Netflix should NOT be listed as a Lever slug in profile.yaml.example (it's Workday)."""
    path = ROOT / "config" / "profile.yaml.example"
    content = path.read_text()
    # Find the lever section and check netflix isn't a list entry (comments are OK)
    in_lever = False
    for line in content.splitlines():
        if "lever:" in line.lower():
            in_lever = True
        elif re.match(r"^\s{2}\w", line) and in_lever:
            # Next top-level key, exit lever section
            in_lever = False
        # Only flag if netflix appears as a YAML list entry (starts with -)
        if in_lever and "netflix" in line.lower() and line.strip().startswith("-"):
            pytest.fail("Netflix is still a Lever slug in profile.yaml.example — it should be under 'workday:'")


def test_readme_cron_time_matches():
    """README UTC time should match actual cron schedule."""
    readme = (ROOT / "README.md").read_text()
    workflow = (ROOT / ".github" / "workflows" / "daily.yml").read_text()

    # Extract cron hour from workflow
    cron_match = re.search(r"cron:\s*'(\d+)\s+(\d+)", workflow)
    assert cron_match, "Could not find cron schedule in daily.yml"
    cron_hour = int(cron_match.group(2))

    # Check README mentions the correct hour (strip markdown formatting)
    readme_plain = readme.lower().replace("*", "")
    assert f"{cron_hour}am utc" in readme_plain or f"{cron_hour} utc" in readme_plain, (
        f"README says a different UTC time than the cron ({cron_hour}am UTC)"
    )
