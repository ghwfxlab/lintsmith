"""Pick the upstream Super-Linter release to sync to.

Usage:
    lintsmith select-upstream --pinned-file upstream-version.txt
        [--force-tag TAG] [--cooldown-days N] [--repo super-linter/super-linter]

Reads the releases of the upstream repository with the ``gh`` CLI. The target is the
newest published release (no draft, no prerelease) that is at least ``--cooldown-days``
old; ``--force-tag`` bypasses that. The target counts only when it is newer than the
pinned version. Prints a summary line and, when ``GITHUB_OUTPUT`` is set, writes
``pinned``, ``latest`` and ``behind`` to it.

Exit code: 0 done, 2 a bad argument or the releases could not be read.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

UPSTREAM = "super-linter/super-linter"


def version_key(tag: str) -> tuple[int, ...]:
    """Sort key for a tag such as v9.0.0; tags without numbers sort first."""
    return tuple(int(part) for part in re.findall(r"\d+", tag))


def parse_time(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def eligible(releases: Sequence[dict[str, Any]], cooldown_days: int, now: datetime) -> str:
    """The newest published release that is at least `cooldown_days` old, or an empty string."""
    oldest_allowed = now - timedelta(days=cooldown_days)
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        if parse_time(release["published_at"]) <= oldest_allowed:
            return str(release["tag_name"])
    return ""


def is_behind(pinned: str, latest: str) -> bool:
    return latest != pinned and version_key(latest) > version_key(pinned)


def fetch_releases(repo: str) -> list[dict[str, Any]]:
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases?per_page=50"], capture_output=True, text=True, check=True
    ).stdout
    releases: list[dict[str, Any]] = json.loads(out)
    return releases


def write_outputs(pinned: str, latest: str, behind: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as handle:
            handle.write(f"pinned={pinned}\nlatest={latest}\nbehind={str(behind).lower()}\n")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pinned-file", required=True, help="file with the pinned upstream tag")
    ap.add_argument("--force-tag", default="", help="sync to this tag even if it is not the latest")
    ap.add_argument("--cooldown-days", default="0", help="only consider releases at least this many days old")
    ap.add_argument("--repo", default=UPSTREAM, help="the upstream repository (default: %(default)s)")
    args = ap.parse_args(argv)

    if not args.cooldown_days.isdigit():
        print(f"::error::cooldown_days must be a whole number, got '{args.cooldown_days}'")
        return 2
    cooldown_days = int(args.cooldown_days)
    try:
        pinned = Path(args.pinned_file).read_text().strip()
    except OSError as e:
        print(f"::error::cannot read {args.pinned_file}: {e}")
        return 2

    latest = args.force_tag
    if not latest:
        try:
            releases = fetch_releases(args.repo)
        except (OSError, ValueError, subprocess.CalledProcessError) as e:
            print(f"::error::cannot read the releases of {args.repo}: {e}")
            return 2
        latest = eligible(releases, cooldown_days, datetime.now(UTC))
        if cooldown_days:
            print(f"Cooldown {cooldown_days} days: newest eligible upstream release is '{latest or 'none'}'.")
        latest = latest or pinned

    behind = is_behind(pinned, latest)
    if behind:
        print(f"Pinned {pinned} is behind upstream {latest}. Running the sync.")
    else:
        print(f"Pinned {pinned} is current (upstream {latest}). Nothing to do.")
    write_outputs(pinned, latest, behind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
