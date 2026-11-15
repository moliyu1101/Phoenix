#!/usr/bin/env python3
"""Regenerate SOURCE_MANIFEST.json + SOURCE_SHA256SUMS.txt and optionally a source tarball.

Source-only package: dependency/build/secret artifacts are excluded so the manifest
describes exactly the files needed to build and run Phoenix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INCLUDE_FILES = [
    ".dockerignore", ".env.example", ".gitignore", "CHANGELOG.md", "LICENSE",
    "NOTICE.md", "README.md", "README_ZH.md", "config.example.yaml",
    "config.swarm.example.yaml", "constraints-tested.txt", "pyproject.toml",
]
INCLUDE_DIRS = [
    "benchmarks", "docker", "docs", "examples", "frontend", "integrations",
    "licenses", "phoenix", "scripts", "tests",
]
EXCLUDE_DIR_NAMES = {
    "node_modules", ".next", ".venv", "venv", "__pycache__", ".git", "build",
    "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".turbo", "coverage",
    ".cache", ".idea", ".vscode",
}
EXCLUDE_FILE_NAMES = {
    "SOURCE_MANIFEST.json", "SOURCE_SHA256SUMS.txt", ".DS_Store",
    "tsconfig.tsbuildinfo", ".env", "config.yaml",
}
EXCLUDE_FILE_SUFFIXES = (".pyc", ".pyo", ".tsbuildinfo", ".log", ".egg-info")


def excluded_dir(name: str) -> bool:
    return name in EXCLUDE_DIR_NAMES or name.endswith(".egg-info")


def excluded_file(name: str) -> bool:
    return name in EXCLUDE_FILE_NAMES or name.endswith(EXCLUDE_FILE_SUFFIXES)


def version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("version"):
            return s.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("version not found in pyproject.toml")


def collect() -> list[dict]:
    paths: list[str] = []
    for name in INCLUDE_FILES:
        if (ROOT / name).is_file():
            paths.append(name)
    for top in INCLUDE_DIRS:
        base = ROOT / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not excluded_dir(d))
            for fn in sorted(filenames):
                if excluded_file(fn):
                    continue
                rel = (Path(dirpath) / fn).relative_to(ROOT).as_posix()
                paths.append(rel)
    files = []
    for rel in sorted(set(paths)):
        data = (ROOT / rel).read_bytes()
        files.append({"path": rel, "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tar", action="store_true", help="also write delivery/phoenix-<version>-source.tar.gz")
    args = ap.parse_args()

    ver = version()
    files = collect()
    validation = f"docs/VALIDATION-{ver}.md"
    if not (ROOT / validation).is_file():
        validation = "docs/VALIDATION.md"
    manifest = {
        "project": "Phoenix", "version": ver, "kind": "source-only",
        "validation": validation, "file_count_excluding_manifests": len(files),
        "files": files,
    }
    (ROOT / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "SOURCE_SHA256SUMS.txt").write_text(
        "".join(f"{f['sha256']}  {f['path']}\n" for f in files), encoding="utf-8")
    print(f"manifest {ver}: {len(files)} files, validation={validation}")

    if args.tar:
        out_dir = ROOT / "delivery"
        out_dir.mkdir(exist_ok=True)
        tar_path = out_dir / f"phoenix-{ver}-source.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            for f in files:
                tf.add(ROOT / f["path"], arcname=f["path"])
            tf.add(ROOT / "SOURCE_MANIFEST.json", arcname="SOURCE_MANIFEST.json")
            tf.add(ROOT / "SOURCE_SHA256SUMS.txt", arcname="SOURCE_SHA256SUMS.txt")
        print(f"tarball {tar_path} ({tar_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()