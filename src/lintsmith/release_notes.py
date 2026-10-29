"""Release notes comparing the benchmark results of two upstream versions.

Usage:
    lintsmith release-notes --old-tag v9.0.0 --old-dir results/by-tag/v9.0.0 \\
        --new-tag v9.1.0 --new-dir results/by-tag/v9.1.0 [--profiles ghwm,python] \\
        [--mapping-diff mapping.diff] [--out notes.md]

Each directory holds the bench-<profile>.jsonl files written by
`lintsmith bench` (and optionally build-<profile>.jsonl). For every profile
present in both, the notes show the median cold pull time and the image size
before and after, for the upstream image and for the lean image. Pull times
depend on the runner and the network at the time, so a change smaller than the
noise (the paired upstream baseline shows how large that is) is not a result.
"""

import argparse
import json
import statistics
import sys
from collections.abc import Collection, Iterable, Sequence
from pathlib import Path
from typing import Any


def load(d: str | Path, profiles: Collection[str]) -> dict[str, dict[tuple[str, str], list[dict[str, Any]]]]:
    rows = []
    for f in sorted(Path(d).glob("bench-*.jsonl")) + sorted(Path(d).glob("build-*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    out: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {}
    for r in rows:
        prof, _, kind = r["variant"].partition("/")
        if profiles and prof not in profiles:
            continue
        out.setdefault(prof, {}).setdefault((kind, r.get("mode", "cold")), []).append(r)
    return out


def med(rows: Iterable[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return statistics.median(vals) if vals else None


def mb(b: float | None) -> int | None:
    return None if b is None else round(b / 1048576)


def fmt_s(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f} s"


def fmt_mb(v: int | None) -> str:
    return "n/a" if v is None else f"{v} MB"


def delta(old: float | None, new: float | None) -> str:
    if old in (None, 0) or new is None:
        return "n/a"
    d = (new - old) / old * 100
    return f"{d:+.0f}%"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old-tag", required=True)
    ap.add_argument("--old-dir", required=True)
    ap.add_argument("--new-tag", required=True)
    ap.add_argument("--new-dir", required=True)
    ap.add_argument("--profiles", default="")
    ap.add_argument("--mapping-diff", help="file with the mapping changes between the versions")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    wanted = {p for p in args.profiles.split(",") if p}
    old, new = load(args.old_dir, wanted), load(args.new_dir, wanted)
    profiles = [p for p in sorted(new) if p in old]
    missing = sorted(set(new) - set(old))

    out_lines = [
        f"## Upstream Super-Linter {args.old_tag} to {args.new_tag}",
        "",
        f"Cold pull on the same self-hosted runner, median of the runs, before ({args.old_tag}) and after "
        f"({args.new_tag}). Negative changes are faster or smaller.",
        "",
    ]
    if not profiles:
        out_lines += ["No profile has results for both versions, so there is nothing to compare."]
    else:
        out_lines += [
            "### Lean image pull time",
            "",
            f"| Profile | gzip {args.old_tag} | gzip {args.new_tag} | change | zstd {args.old_tag} | zstd {args.new_tag} | change |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in profiles:
            g_o, g_n = (
                med(old[p].get(("lean-gzip", "cold"), []), "pull_s"),
                med(new[p].get(("lean-gzip", "cold"), []), "pull_s"),
            )
            z_o, z_n = (
                med(old[p].get(("lean-zstd", "cold"), []), "pull_s"),
                med(new[p].get(("lean-zstd", "cold"), []), "pull_s"),
            )
            out_lines.append(
                f"| {p} | {fmt_s(g_o)} | {fmt_s(g_n)} | {delta(g_o, g_n)} | {fmt_s(z_o)} | {fmt_s(z_n)} | {delta(z_o, z_n)} |"
            )
        out_lines += [
            "",
            "### Lean image size",
            "",
            f"| Profile | unpacked {args.old_tag} | unpacked {args.new_tag} | change | compressed {args.old_tag} | compressed {args.new_tag} | change |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in profiles:
            u_o, u_n = (mb(med(d[p].get(("lean-gzip", "cold"), []), "uncompressed_bytes")) for d in (old, new))
            c_o, c_n = (mb(med(d[p].get(("lean-gzip", "cold"), []), "compressed_bytes")) for d in (old, new))
            out_lines.append(
                f"| {p} | {fmt_mb(u_o)} | {fmt_mb(u_n)} | {delta(u_o, u_n)} | {fmt_mb(c_o)} | {fmt_mb(c_n)} | {delta(c_o, c_n)} |"
            )
        out_lines += [
            "",
            "### Upstream image, for reference",
            "",
            f"| Profile | pull {args.old_tag} | pull {args.new_tag} | change | unpacked {args.old_tag} | unpacked {args.new_tag} | change |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in profiles:
            b_o, b_n = (
                med(old[p].get(("baseline", "cold"), []), "pull_s"),
                med(new[p].get(("baseline", "cold"), []), "pull_s"),
            )
            s_o, s_n = (mb(med(d[p].get(("baseline", "cold"), []), "uncompressed_bytes")) for d in (old, new))
            out_lines.append(
                f"| {p} | {fmt_s(b_o)} | {fmt_s(b_n)} | {delta(b_o, b_n)} | {fmt_mb(s_o)} | {fmt_mb(s_n)} | {delta(s_o, s_n)} |"
            )
        out_lines += [
            "",
            "### Build time (gzip build including push)",
            "",
            f"| Profile | {args.old_tag} | {args.new_tag} | change |",
            "|---|---|---|---|",
        ]
        for p in profiles:
            t_o, t_n = (med(d[p].get(("lean-gzip", "build"), []), "pull_s") for d in (old, new))
            out_lines.append(f"| {p} | {fmt_s(t_o)} | {fmt_s(t_n)} | {delta(t_o, t_n)} |")
    if missing:
        out_lines += ["", f"Not compared (no results for {args.old_tag}): {', '.join(missing)}."]
    if args.mapping_diff and Path(args.mapping_diff).exists() and Path(args.mapping_diff).read_text().strip():
        out_lines += ["", "### Mapping changes", "", Path(args.mapping_diff).read_text().strip()]
    out_lines += [
        "",
        "Pull times vary with the runner and the network. Compare the change in the lean image with the change in "
        "the upstream baseline pulled in the same run before reading anything into a small difference.",
    ]
    text = "\n".join(out_lines) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
