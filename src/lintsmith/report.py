"""Turn benchmark results (``bench-*.jsonl`` and ``build-*.jsonl``) into Markdown tables.

Usage:
    lintsmith compare   FILE.jsonl...   lean images against their upstream baseline, per profile
    lintsmith summarize FILE.jsonl...   every variant on its own, median of the runs

Each line is one run written by ``lintsmith bench`` (or the build timing in
``profiles.yaml``). ``variant`` is ``<profile>/<kind>`` with kind ``baseline``,
``baseline-end``, ``lean-gzip`` or ``lean-zstd``; ``mode`` is ``cold``, ``warm`` or
``build`` (missing means ``cold``).

The number formats follow the jq programs these replaced (``scripts/compare.sh``,
``scripts/summarize.sh``): one decimal for seconds, whole megabytes, percentages
rounded half away from zero (a small negative value prints as ``-0%``).
"""

import json
import math
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

Row = dict[str, Any]

MIB = 1048576
DRIFT_WARNING_PERCENT = 15

COLD_HEADER = (
    "| Profile | Baseline | Lean gzip | Lean zstd | Speedup (gzip) | Speedup (zstd) | Baseline unpacked | "
    "Lean unpacked | Unpacked saved | Baseline compressed | Lean compressed | Compressed saved | "
    "Baseline drift | Build gzip | Build zstd |"
)


def read_rows(paths: Iterable[str | Path]) -> list[Row]:
    rows: list[Row] = []
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def round_half_away(value: float) -> float:
    """Round like C's round(): halves go away from zero, and -0.3 gives -0."""
    return math.copysign(math.floor(abs(value) + 0.5), value)


def number(value: float) -> str:
    """Print a number the way jq does: no trailing .0, and negative zero as -0."""
    if value == 0:
        return "-0" if math.copysign(1, value) < 0 else "0"
    if value == int(value):
        return str(int(value))
    return repr(value)


def seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{number(round_half_away(value * 10) / 10)} s"


def whole_mb(value: float | None, floor: bool = False) -> int | None:
    if value is None:
        return None
    mb = value / MIB
    return math.floor(mb) if floor else int(round_half_away(mb))


def megabytes(value: int | None) -> str:
    return "n/a" if value is None else f"{value} MB"


def percent_saved(before: int | None, after: int | None) -> str:
    if before is None or after is None or before == 0:
        return "n/a"
    return f"{number(round_half_away((1 - after / before) * 100))}%"


def drift(first: float | None, last: float | None) -> str:
    if first is None or last is None or first == 0:
        return "n/a"
    change = (last - first) / first * 100
    warning = "WARN " if abs(change) > DRIFT_WARNING_PERCENT else ""
    return f"{warning}{number(round_half_away(change))}%"


def ratio(numerator: float | None, denominator: float | None) -> str:
    if numerator is None or denominator is None or denominator == 0:
        return "n/a"
    return f"{number(round_half_away(numerator / denominator * 10) / 10)}x"


def split_variant(row: Row) -> Row:
    profile, _, kind = str(row["variant"]).partition("/")
    return {**row, "profile": profile, "kind": kind, "mode": row.get("mode") or "cold"}


def by_profile(rows: Iterable[Row]) -> list[list[Row]]:
    groups: dict[str, list[Row]] = {}
    for row in map(split_variant, rows):
        groups.setdefault(row["profile"], []).append(row)
    return [groups[profile] for profile in sorted(groups)]


def select(rows: Sequence[Row], kind: str, mode: str) -> list[Row]:
    return [r for r in rows if r["kind"] == kind and r["mode"] == mode]


def median_of(rows: Sequence[Row], kind: str, mode: str, key: str = "pull_s") -> float | None:
    return median([r[key] for r in select(rows, kind, mode) if r.get(key) is not None])


def size(rows: Sequence[Row], kind: str, key: str) -> int | None:
    cold = select(rows, kind, "cold")
    return whole_mb(cold[0].get(key)) if cold else None


def cold_line(rows: Sequence[Row]) -> str:
    baseline = median_of(rows, "baseline", "cold")
    gzip = median_of(rows, "lean-gzip", "cold")
    zstd = median_of(rows, "lean-zstd", "cold")
    unpacked = [size(rows, k, "uncompressed_bytes") for k in ("baseline", "lean-gzip")]
    compressed = [size(rows, k, "compressed_bytes") for k in ("baseline", "lean-gzip")]
    cells = [
        rows[0]["profile"],
        seconds(baseline),
        seconds(gzip),
        seconds(zstd),
        ratio(baseline, gzip),
        ratio(baseline, zstd),
        megabytes(unpacked[0]),
        megabytes(unpacked[1]),
        percent_saved(unpacked[0], unpacked[1]),
        megabytes(compressed[0]),
        megabytes(compressed[1]),
        percent_saved(compressed[0], compressed[1]),
        drift(baseline, median_of(rows, "baseline-end", "cold")),
        seconds(median_of(rows, "lean-gzip", "build")),
        seconds(median_of(rows, "lean-zstd", "build")),
    ]
    return "| " + " | ".join(cells) + " |"


def warm_line(rows: Sequence[Row]) -> str:
    cells = [
        rows[0]["profile"],
        seconds(median_of(rows, "baseline", "warm")),
        seconds(median_of(rows, "lean-gzip", "warm")),
        seconds(median_of(rows, "baseline", "warm", "start_s")),
        seconds(median_of(rows, "lean-gzip", "warm", "start_s")),
    ]
    return "| " + " | ".join(cells) + " |"


def compare(rows: Iterable[Row]) -> list[str]:
    profiles = by_profile(rows)
    return [
        "### Cold pull (image removed before each pull)",
        "",
        COLD_HEADER,
        "|" + "---|" * 15,
        *[cold_line(p) for p in profiles],
        "",
        "### Warm pull (image already on the runner) and container start",
        "",
        "| Profile | Baseline pull | Lean gzip pull | Baseline start | Lean gzip start |",
        "|---|---|---|---|---|",
        *[warm_line(p) for p in profiles],
    ]


def summarize(rows: Iterable[Row]) -> list[str]:
    groups: dict[tuple[str | None, str, str], list[Row]] = {}
    for row in rows:
        key = (row.get("runner"), row.get("mode") or "cold", str(row["variant"]))
        groups.setdefault(key, []).append(row)

    def optional(group: Sequence[Row], key: str) -> float | None:
        return median([r[key] for r in group if r.get(key) is not None])

    lines = [
        "| Runner | Mode | Variant | Runs | Pull median | Pull min-max | Start | Download (crane) | Load | "
        "Compressed | Uncompressed |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    # a row without a runner (the build timings) sorts first and prints as null, as jq does
    for (runner, mode, variant), group in sorted(
        groups.items(), key=lambda item: (item[0][0] is not None, *map(str, item[0]))
    ):
        pulls = [r["pull_s"] for r in group]
        first = group[0]
        compressed = whole_mb(first.get("compressed_bytes"), floor=True)
        uncompressed = whole_mb(first.get("uncompressed_bytes"), floor=True)
        cells = [
            "null" if runner is None else runner,
            mode,
            variant,
            str(len(group)),
            seconds(median(pulls)),
            f"{seconds(min(pulls))}-{seconds(max(pulls))}",
            seconds(optional(group, "start_s")),
            seconds(optional(group, "download_s")),
            seconds(optional(group, "load_s")),
            megabytes(compressed),
            megabytes(uncompressed),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _run(build: Any, argv: Sequence[str] | None, name: str) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(f"usage: lintsmith {name} FILE.jsonl...\n\n{__doc__}")
        return 0 if args else 2
    try:
        rows = read_rows(args)
    except (OSError, ValueError) as e:
        print(f"::error::cannot read the results: {e}")
        return 2
    print("\n".join(build(rows)))
    return 0


def main_compare(argv: Sequence[str] | None = None) -> int:
    return _run(compare, argv, "compare")


def main_summarize(argv: Sequence[str] | None = None) -> int:
    return _run(summarize, argv, "summarize")
