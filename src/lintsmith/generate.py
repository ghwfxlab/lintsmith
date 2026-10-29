"""Generate a lean Super-Linter image build context from VALIDATE_* flags.

Usage:
    lintsmith generate --env base/opinionated.env --env toolchains/python.env \\
        --upstream-tag v9.0.0 --upstream-dockerfile path/to/upstream/Dockerfile \\
        --out build/python

Writes into --out:
    Dockerfile               overlay image, pinned to the upstream release
    prune-node-modules.js    helper used by the Dockerfile
    checks.sh                runs inside the built image to verify every tool
    plan.json                what was selected (also names the baseline variant)

Everything is configurable. The base and the toolchains are only env files, so
any combination works: leave the base out, add several toolchains, drop single
flags with --exclude, or add tools Super-Linter does not ship with --extra-apk,
--extra-npm and --extra-pip (and --extra-check to verify them). The same can be
written in an env file: EXTRA_APK="..." EXTRA_NPM="..." EXTRA_PIP="..."
EXTRA_CHECK="...".

Prints the upstream baseline variant ("slim" or "standard") to compare against.
"""

import argparse
import json
import re
import shlex
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from lintsmith import config as slconfig

HERE = Path(__file__).resolve().parent / "data"
UPSTREAM_REPO = "ghcr.io/super-linter/super-linter"
FIXTURES = r"""mkdir -p /tmp/fx && cd /tmp/fx
printf '# Title\n\nHello world.\n' > t.md
printf -- '---\na: 1\n' > t.yml
printf '{}\n' > t.json
printf 'const a = 1;\n\nexport default a;\n' > t.js
printf 'const a: number = 1;\n\nexport default a;\n' > t.ts
printf 'a {\n  color: red;\n}\n' > t.css
printf '<!doctype html>\n<html lang="en">\n  <head>\n    <title>t</title>\n  </head>\n  <body></body>\n</html>\n' > t.html
cd /
"""
CHECK_FUNC = r"""fail=0
run_check() {
    local out rc
    out="$(eval "$1" 2>&1)"; rc=$?
    if [ "$rc" -ge 126 ] && [ "$rc" -le 127 ] \
        || printf '%s' "$out" | grep -qiE 'cannot find (module|package)|can.t locate|MODULE_NOT_FOUND|ERR_MODULE_NOT_FOUND|error while loading shared|no such file or directory' \
        || printf '%s' "$out" | grep -qE ': not found$'; then
        echo "FAIL ($rc): $1"; printf '%s\n' "$out" | head -5 | sed 's/^/    /'; fail=1
    else
        echo "ok: $1"
    fi
}
"""


def read_flags(paths: Iterable[str | Path]) -> list[str]:
    flags = []
    for p in paths:
        for line in Path(p).read_text().splitlines():
            m = re.match(r"\s*VALIDATE_([A-Z0-9_]+)\s*=\s*true\s*$", line)
            if m and m.group(1) not in flags and m.group(1) != "ALL_CODEBASE":
                flags.append(m.group(1))
    return flags


def read_extras(paths: Iterable[str | Path]) -> dict[str, list[str]]:
    """EXTRA_APK, EXTRA_NPM, EXTRA_PIP (space separated) and EXTRA_CHECK (one
    command per line, repeatable) from env files."""
    out: dict[str, list[str]] = {"APK": [], "NPM": [], "PIP": [], "CHECK": []}
    for p in paths:
        for line in Path(p).read_text().splitlines():
            m = re.match(r'\s*EXTRA_(APK|NPM|PIP|CHECK)\s*=\s*"?(.*?)"?\s*$', line)
            if not m:
                continue
            if m.group(1) == "CHECK":
                out["CHECK"].append(m.group(2))
            else:
                out[m.group(1)] += m.group(2).split()
    return out


def python_base(dockerfile: str | Path) -> str:
    m = re.search(r"^FROM\s+(python:\S+)\s+AS\s+python-base", Path(dockerfile).read_text(), re.M)
    if not m:
        sys.exit("could not find 'FROM python:... AS python-base' in the upstream Dockerfile")
    return m.group(1)


def uniq[T](seq: Iterable[T]) -> list[T]:
    return list(dict.fromkeys(seq))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", action="append", default=[], help="env file with VALIDATE_*=true lines (repeatable)")
    ap.add_argument("--upstream-tag", required=True, help="e.g. v9.0.0")
    ap.add_argument("--upstream-dockerfile", required=True, help="the upstream Dockerfile at that tag")
    ap.add_argument(
        "--workflow",
        action="append",
        default=[],
        metavar="FILE",
        help="read VALIDATE_* from the super-linter step of a workflow (repeatable); "
        "follows upstream semantics: only the linters set to true, or all except those set to false",
    )
    ap.add_argument(
        "--all", action="store_true", help="select every flag in the mapping (used to verify the whole mapping)"
    )
    ap.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="FLAG",
        help="drop a flag selected by the env files, e.g. NATURAL_LANGUAGE (repeatable)",
    )
    ap.add_argument(
        "--extra-apk", action="append", default=[], metavar="PKG", help="extra Alpine package to install (repeatable)"
    )
    ap.add_argument(
        "--extra-npm",
        action="append",
        default=[],
        metavar="PKG",
        help="extra npm package, installed from the registry at build time, e.g. left-pad@1.3.0 (repeatable)",
    )
    ap.add_argument(
        "--extra-pip",
        action="append",
        default=[],
        metavar="PKG",
        help="extra pip package, installed from PyPI at build time, e.g. yq==3.4.3 (repeatable)",
    )
    ap.add_argument(
        "--extra-check",
        action="append",
        default=[],
        metavar="CMD",
        help="command that must succeed in the built image to verify an extra (repeatable)",
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--mapping", default=str(HERE / "linters.json"))
    args = ap.parse_args(argv)

    mapping = json.loads(Path(args.mapping).read_text())
    table = mapping["linters"]
    if not args.env and not args.all and not args.workflow:
        sys.exit("give at least one --env file or --workflow, or --all")
    flags = read_flags(args.env)
    if args.workflow:
        wenv = {}
        try:
            for w in args.workflow:
                wenv.update(slconfig.parse_workflow(w))
            flags = uniq(flags + slconfig.effective_flags(wenv, list(table)))
        except slconfig.ConfigError as e:
            sys.exit(f"{e}")
    if args.all:
        flags = uniq(flags + [f for f in table if f != "ALL_CODEBASE"])
    excluded = [e.removeprefix("VALIDATE_") for e in args.exclude]
    flags = [f for f in flags if f not in excluded]
    if not flags:
        sys.exit("no linters selected")
    unknown = [f for f in flags if f not in table]
    if unknown:
        sys.exit(
            "no mapping for: "
            + ", ".join(unknown)
            + "\nadd them to the bundled linters.json (and check the upstream Dockerfile for paths)"
        )

    sel = [table[f] for f in flags]
    bins = uniq(p for s in sel for p in s.get("bins", []))
    dirs = uniq(p for s in sel for p in s.get("dirs", []))
    venvs = uniq(v for s in sel for v in s.get("venvs", []))
    groups = uniq(g for s in sel for g in s.get("npm", []))
    npm_roots = uniq(p for g in groups for p in mapping["npm_groups"][g])
    extras = read_extras(args.env)
    extra_apk = uniq(extras["APK"] + args.extra_apk)
    extra_npm = uniq(extras["NPM"] + args.extra_npm)
    extra_pip = uniq(extras["PIP"] + args.extra_pip)
    extra_check = extras["CHECK"] + args.extra_check
    apk = uniq(
        mapping["base_apk"]
        + [p for s in sel for p in s.get("apk", [])]
        + extra_apk
        + (["nodejs-current"] if extra_npm else [])
        + (["nodejs-current"] if npm_roots else [])
    )
    path_extra = uniq(
        [f"/venvs/{v}/bin" for v in venvs]
        + (["/opt/extras/npm/node_modules/.bin"] if extra_npm else [])
        + (["/opt/extras/pip/bin"] if extra_pip else [])
        + (["/node_modules/.bin"] if npm_roots else [])
        + [p for s in sel for p in s.get("path", [])]
    )
    links = uniq(tuple(link) for s in sel for link in s.get("links", []))
    env_extra = {}
    for s in sel:
        env_extra.update(s.get("env", {}))
    upstream_variant = "standard" if any(s.get("upstream") == "standard" for s in sel) else "slim"
    baseline = (
        "standard" if any(s.get("baseline") == "standard" or s.get("upstream") == "standard" for s in sel) else "slim"
    )
    base = python_base(args.upstream_dockerfile)

    def image_tag(variant: str) -> str:
        # slim images are tagged slim-<tag>; standard images are just <tag>
        return f"slim-{args.upstream_tag}" if variant == "slim" else args.upstream_tag

    upstream_image = f"{UPSTREAM_REPO}:{image_tag(upstream_variant)}"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "prune-node-modules.js").write_text((HERE / "prune-node-modules.js").read_text())

    out_lines = [
        "# syntax=docker/dockerfile:1",
        f"# Generated by lintsmith generate. Upstream: {upstream_image}",
        f"# Flags: {' '.join(flags)}",
        f"ARG UPSTREAM_IMAGE={upstream_image}",
        "FROM ${UPSTREAM_IMAGE} AS upstream",
        "",
    ]
    if npm_roots:
        out_lines += [
            "FROM upstream AS npm-prune",
            "COPY prune-node-modules.js /prune-node-modules.js",
            "RUN node /prune-node-modules.js /node_modules /pruned " + " ".join(shlex.quote(r) for r in npm_roots),
            "",
        ]
    # Each category is collected in its own stage and copied as its own layer,
    # so registries and Docker can download layers in parallel. cp -a --parents
    # keeps symlinks and permissions. A path that does not exist upstream prints
    # a warning instead of failing the build; the tool checks catch real gaps.
    for name, items in (
        ("bins", bins),
        ("venvs", [f"/venvs/{v}" for v in venvs]),
        ("dirs", dirs),
        ("action", ["/action"]),
    ):
        if not items:
            continue
        out_lines += [
            f"FROM upstream AS {name}-src",
            "RUN mkdir /out; for p in " + " ".join(shlex.quote(i) for i in items) + "; do \\",
            '      if [ -e "$p" ] || [ -L "$p" ]; then cp -a --parents "$p" /out; \\',
            '      else echo "WARNING: missing upstream path: $p" >&2; fi; done',
            f"FROM scratch AS {name}",
            f"COPY --from={name}-src /out /",
            "",
        ]
    if extra_npm:
        out_lines += [
            f"FROM {base} AS extra-npm",
            "RUN apk add --no-cache nodejs-current npm",
            "RUN mkdir -p /opt/extras/npm && cd /opt/extras/npm && npm install --no-audit --no-fund --ignore-scripts "
            + " ".join(shlex.quote(x) for x in extra_npm),
            "",
        ]
    if extra_pip:
        out_lines += [
            f"FROM {base} AS extra-pip",
            "RUN apk add --no-cache gcc linux-headers musl-dev python3-dev",
            "RUN python -m venv /opt/extras/pip && /opt/extras/pip/bin/pip install --no-cache-dir "
            + " ".join(shlex.quote(x) for x in extra_pip),
            "",
        ]
    out_lines += [
        f"FROM {base}",
        "RUN apk add --no-cache \\",
        "  " + " \\\n  ".join(apk),
        "",
        'SHELL ["/bin/bash", "-o", "errexit", "-o", "nounset", "-o", "pipefail", "-c"]',
        "",
    ]
    out_lines += ["COPY --from=bins / /"] if bins else []
    out_lines += ["COPY --from=venvs / /"] if venvs else []
    out_lines += ["COPY --from=dirs / /"] if dirs else []
    out_lines += ["COPY --from=npm-prune /pruned /node_modules"] if npm_roots else []
    out_lines += ["COPY --from=extra-npm /opt/extras/npm /opt/extras/npm"] if extra_npm else []
    out_lines += ["COPY --from=extra-pip /opt/extras/pip /opt/extras/pip"] if extra_pip else []
    out_lines += ["COPY --from=action / /", ""]
    for target, link in links:
        out_lines.append(f"RUN [ -e {shlex.quote(link)} ] || ln -s {shlex.quote(target)} {shlex.quote(link)}")
    out_lines += [""] if links else []
    out_lines += [f'ENV PATH="${{PATH}}:{":".join(path_extra)}"'] if path_extra else []
    out_lines += [
        'ENV VERSION_FILE="/action/linterVersions.txt"',
        'ENV IMAGE="lean"',
        'ENV RENOVATE_X_IGNORE_RE2="true"',
        'ENV ARM_TTK_PSD1="/usr/lib/microsoft/arm-ttk/arm-ttk.psd1"',
        'ENV HOME="/github/home"',
        # linter.sh runs with `set -u` and reads these, as upstream's release build sets them
        f"ARG BUILD_VERSION={args.upstream_tag.removeprefix('v')}",
        "ARG BUILD_REVISION=unknown",
        "ARG BUILD_DATE=unknown",
        "ENV BUILD_VERSION=$BUILD_VERSION BUILD_REVISION=$BUILD_REVISION BUILD_DATE=$BUILD_DATE",
    ]
    out_lines += [f'ENV {k}="{v}"' for k, v in env_extra.items()]
    out_lines += [
        "",
        'RUN mkdir -p "${HOME}" && git config --system --add safe.directory "*"',
        "WORKDIR /",
        'ENTRYPOINT ["/action/lib/linter.sh"]',
        "",
    ]
    (out / "Dockerfile").write_text("\n".join(out_lines))

    checks = uniq([c for s in sel for c in s.get("check", [])] + extra_check)
    (out / "checks.sh").write_text(
        "#!/usr/bin/env bash\n"
        + FIXTURES
        + CHECK_FUNC
        + "\n".join(f"run_check {shlex.quote(c)}" for c in checks)
        + '\nexit "$fail"\n'
    )
    (out / "plan.json").write_text(
        json.dumps(
            {
                "flags": flags,
                "upstream_tag": args.upstream_tag,
                "upstream_image": upstream_image,
                "baseline_variant": baseline,
                "baseline_image": f"{UPSTREAM_REPO}:{image_tag(baseline)}",
                "python_base": base,
                "links": links,
                "bins": bins,
                "dirs": dirs,
                "venvs": venvs,
                "npm_roots": npm_roots,
                "apk": apk,
                "extras": {"apk": extra_apk, "npm": extra_npm, "pip": extra_pip, "check": extra_check},
            },
            indent=2,
        )
        + "\n"
    )
    print(baseline)
    return 0


if __name__ == "__main__":
    main()
