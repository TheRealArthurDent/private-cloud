"""Renovate rules for the images whose versions Paperless-ngx dictates.

Paperless talks to Gotenberg and Tika over their HTTP APIs and supports only the majors its own compose files use
(docker/compose/ upstream). Renovate must not raise them on its own; the Paperless update PR carries a note that says
how to align them with the new Paperless version.
"""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RENOVATE = json.loads((ROOT / "renovate.json").read_text())
PAPERLESS_COMPOSE = yaml.safe_load((ROOT / "paperless" / "docker-compose.yaml").read_text())


def rules_for(package):
    return [rule for rule in RENOVATE.get("packageRules", []) if package in rule.get("matchPackageNames", [])]


def pinned_major(service):
    tag = PAPERLESS_COMPOSE["services"][service]["image"].rsplit(":", 1)[1]
    return int(tag.split(".")[0])


def allowed_versions(package):
    values = [rule["allowedVersions"] for rule in rules_for(package) if "allowedVersions" in rule]
    assert len(values) == 1, f"{package} needs exactly one allowedVersions rule"
    return values[0]


def test_gotenberg_stays_on_the_pinned_major():
    assert allowed_versions("gotenberg/gotenberg") == f"<{pinned_major('gotenberg') + 1}"


def test_tika_stays_on_the_pinned_major():
    assert allowed_versions("apache/tika") == f"<{pinned_major('tika') + 1}"


def test_paperless_pr_says_how_to_align_gotenberg_and_tika():
    notes = [note for rule in rules_for("ghcr.io/paperless-ngx/paperless-ngx") for note in rule.get("prBodyNotes", [])]
    text = "\n".join(notes)
    assert re.search(r"gotenberg", text, re.I)
    assert re.search(r"tika", text, re.I)
    assert "{{{newVersion}}}" in text
    assert "allowedVersions" in text
