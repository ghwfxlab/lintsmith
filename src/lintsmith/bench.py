"""Measure the pull time and container start time of an image.

Usage:
    lintsmith bench IMAGE [RUNS] VARIANT RUNNER [--mode cold|warm] [--out FILE] [--split]

    IMAGE    the image to pull
    RUNS     how many runs (default 5)
    VARIANT  label written to every row, normally ``<profile>/<kind>``
    RUNNER   label of the runner, written to every row

Modes (``--mode``, default ``$BENCH_MODE`` or ``cold``):

    cold
        remove the local image and every other unused image before every run,
        then time ``docker pull``. Other images must go too: the gzip and zstd
        variants of an image share their uncompressed layers, and a variant
        pulled next to the other one would reuse them and look almost free.
        This clears unused images on the runner.
    warm
        the image stays on the runner (a first, unmeasured pull makes sure it
        is there); time the no-op ``docker pull``, which is what a job pays
        when nothing needs downloading.

Rows are printed and appended to ``--out`` (default ``$BENCH_OUT`` or
``bench-results.jsonl``). ``--split`` (or ``BENCH_SPLIT=1``) also times, in cold
mode, a download-only pull to a tarball (crane) and a ``docker load`` of it, a
rough download against unpack split (approximate: load is not the unpack done
by ``docker pull``). Without it crane, if present, only reads the compressed size.

Exit code: 0 done, 1 a docker or crane call failed, 2 a bad argument.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

PLATFORM = "linux/amd64"


class BenchError(Exception):
    """A docker or crane call that must succeed failed."""


def run(command: Sequence[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if check and completed.returncode != 0:
        raise BenchError(f"{' '.join(command[:3])} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed


def timed(action: Callable[[], object]) -> float:
    start = time.perf_counter()
    action()
    return round(time.perf_counter() - start, 2)


def clear_local_images(image: str) -> None:
    """Leave no layer behind that a pull could reuse."""
    run(["docker", "image", "rm", "-f", image], check=False)
    run(["docker", "image", "prune", "-af"], check=False)
    run(["docker", "builder", "prune", "-af"], check=False)


def have_crane() -> bool:
    return shutil.which("crane") is not None


def compressed_bytes(image: str) -> int | None:
    """Sum of the compressed layer sizes, read with crane when it is installed."""
    if not have_crane():
        return None
    completed = run(["crane", "manifest", "--platform", PLATFORM, image], check=False)
    if completed.returncode != 0:
        return None
    try:
        layers = json.loads(completed.stdout)["layers"]
        return sum(int(layer["size"]) for layer in layers)
    except (ValueError, KeyError, TypeError):
        return None


def uncompressed_bytes(image: str) -> int:
    return int(run(["docker", "image", "inspect", "--format", "{{.Size}}", image]).stdout.strip())


def split_download(image: str) -> tuple[float, float]:
    """Seconds to download the image to a tarball with crane, and to docker load it."""
    with tempfile.TemporaryDirectory() as directory:
        tarball = str(Path(directory) / "image.tar")
        # like the shell script, a failure here still gives a timing instead of stopping the run
        download = timed(lambda: run(["crane", "pull", "--platform", PLATFORM, image, tarball], check=False))
        load = timed(lambda: run(["docker", "load", "--quiet", "-i", tarball], check=False))
    return download, load


def measure(image: str, number: int, mode: str, split: bool, size: int | None) -> dict[str, Any]:
    """One run; `split` already includes whether crane is installed."""
    download: float | None = None
    load: float | None = None
    if mode == "cold":
        clear_local_images(image)
    pull = timed(lambda: run(["docker", "pull", "--quiet", image]))
    start = timed(lambda: run(["docker", "run", "--rm", "--entrypoint", "true", image], check=False))
    unpacked = uncompressed_bytes(image)
    if mode == "cold" and split:
        clear_local_images(image)
        download, load = split_download(image)
    return {
        "run": number,
        "pull_s": pull,
        "start_s": start,
        "download_s": download,
        "load_s": load,
        "compressed_bytes": size,
        "uncompressed_bytes": unpacked,
    }


def bench(image: str, runs: int, variant: str, runner: str, mode: str, out: Path, split: bool) -> list[dict[str, Any]]:
    size = compressed_bytes(image)
    split = split and have_crane()
    if mode == "warm":
        run(["docker", "pull", "--quiet", image])  # make sure the image is there; not measured
    rows = []
    for number in range(1, runs + 1):
        row = {"image": image, "variant": variant, "runner": runner, "mode": mode}
        row.update(measure(image, number, mode, split, size))
        text = json.dumps(row)
        print(text)
        with out.open("a") as handle:
            handle.write(text + "\n")
        rows.append(row)
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("runs_or_variant", help="RUNS (default 5), then VARIANT and RUNNER")
    ap.add_argument("more", nargs="*")
    ap.add_argument("--mode", choices=["cold", "warm"], default=os.environ.get("BENCH_MODE", "cold"))
    ap.add_argument("--out", default=os.environ.get("BENCH_OUT", "bench-results.jsonl"))
    ap.add_argument("--split", action="store_true", default=os.environ.get("BENCH_SPLIT") == "1")
    args = ap.parse_args(argv)

    positional = [args.runs_or_variant, *args.more]
    if positional[0].isdigit():
        runs, rest = int(positional[0]), positional[1:]
    else:
        runs, rest = 5, positional
    if len(rest) != 2:
        print("::error::usage: lintsmith bench IMAGE [RUNS] VARIANT RUNNER")
        return 2
    variant, runner = rest
    try:
        bench(args.image, runs, variant, runner, args.mode, Path(args.out), args.split)
    except BenchError as e:
        print(f"::error::{e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
