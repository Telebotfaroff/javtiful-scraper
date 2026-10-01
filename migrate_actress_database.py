#!/usr/bin/env python3
"""Migrate actress database folders into A-Z buckets."""

import json
import os
import shutil
import tempfile
from pathlib import Path


ROOT = Path("database")
ACTRESS_ROOT = ROOT / "actress"
INDEX_PATH = ROOT / "index" / "indexactress.json"


def load_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".json-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def category_for(name, slug):
    value = str(name or slug or "").strip()
    first = value[:1].upper()
    return first if first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else "OTHER"


def merge_actress_dirs(source, destination):
    """Move an actress directory, merging an already-existing destination safely."""
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return

    source_file = source / "videos.json"
    destination_file = destination / "videos.json"

    source_data = load_json(source_file, {"total": 0, "videos": {}})
    destination_data = load_json(destination_file, {"total": 0, "videos": {}})

    source_videos = source_data.get("videos", {})
    destination_videos = destination_data.get("videos", {})

    if isinstance(source_videos, dict) and isinstance(destination_videos, dict):
        destination_videos.update(source_videos)
        destination_data["videos"] = destination_videos
        destination_data["total"] = len(destination_videos)
        write_json(destination_file, destination_data)

    # Preserve any unexpected files from the old directory.
    for child in source.iterdir():
        if child.name == "videos.json":
            continue
        target = destination / child.name
        if target.exists() and child.is_dir():
            # Merge nested directories conservatively.
            for nested in child.rglob("*"):
                if nested.is_file():
                    relative = nested.relative_to(child)
                    target_file = target / relative
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    if not target_file.exists():
                        shutil.copy2(nested, target_file)
        elif not target.exists():
            shutil.move(str(child), str(target))

    shutil.rmtree(source)


def main():
    if not ACTRESS_ROOT.exists():
        print("[actress-migration] no database/actress directory; nothing to do")
        return

    index = load_json(INDEX_PATH, {"actresses": {}})
    actresses = index.get("actresses", {})
    moved = 0
    skipped = 0

    # Only process legacy top-level actress folders. Existing A-Z/OTHER buckets
    # are left untouched, making this script safe to run on every crawl.
    for source in sorted(ACTRESS_ROOT.iterdir()):
        if not source.is_dir() or source.name in {"A", "B", "C", "D", "E", "F",
                                                  "G", "H", "I", "J", "K", "L",
                                                  "M", "N", "O", "P", "Q", "R",
                                                  "S", "T", "U", "V", "W", "X",
                                                  "Y", "Z", "OTHER"}:
            continue

        slug = source.name.lower()
        entry = actresses.get(slug, {})
        name = entry.get("name") if isinstance(entry, dict) else None
        category = category_for(name, slug)
        destination = ACTRESS_ROOT / category / source.name

        merge_actress_dirs(source, destination)
        moved += 1
        print(f"[actress-migration] {source.name} -> {category}/{source.name}", flush=True)

    print(f"[actress-migration] complete | moved={moved} skipped={skipped}", flush=True)


if __name__ == "__main__":
    main()
