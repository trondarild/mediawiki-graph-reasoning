"""
Build and search a lightweight title→path index of local papers and books.

Usage:
    python mmx_local_index.py --build            # rebuild index from source dirs
    python mmx_local_index.py --search "keyword" # search index for title matches

The index file (local_sources.json) is gitignored — run --build on each machine.
Source directories are read from .env:
    MEMEX_LOCAL_ARTICLES, MEMEX_LOCAL_ZOTERO, MEMEX_LOCAL_BOOKS
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

INDEX_PATH = Path(__file__).parent / "local_sources.json"
READABLE_EXTENSIONS = {".pdf", ".epub", ".txt", ".md"}


def source_dirs():
    dirs = []
    for key in ("MEMEX_LOCAL_ARTICLES", "MEMEX_LOCAL_ZOTERO", "MEMEX_LOCAL_BOOKS"):
        val = os.environ.get(key)
        if val:
            dirs.append((key, Path(val).expanduser()))
    return dirs


def build_index():
    """
    Walk source directories and build a title→path index.
    For Zotero (opaque subdirs), walks one level deep into each subdir.
    Saves to local_sources.json.
    """
    index = []
    for env_key, base in source_dirs():
        if not base.exists():
            print(f"  Skipping {env_key}: {base} does not exist")
            continue

        is_zotero = "ZOTERO" in env_key

        if is_zotero:
            # Zotero: opaque subdirs, each containing one PDF
            for subdir in base.iterdir():
                if not subdir.is_dir():
                    continue
                for f in subdir.iterdir():
                    if f.suffix.lower() in READABLE_EXTENSIONS:
                        title = f.stem
                        index.append({"title": title, "path": str(f), "source": "zotero"})
        else:
            # Flat directory + one level of subdirectories
            label = "articles" if "ARTICLES" in env_key else "books"
            for f in base.rglob("*"):
                if f.suffix.lower() in READABLE_EXTENSIONS and f.is_file():
                    title = f.stem
                    index.append({"title": title, "path": str(f), "source": label})

    with open(INDEX_PATH, "w") as fh:
        json.dump(index, fh, indent=2)
    print(f"Index built: {len(index)} entries -> {INDEX_PATH}")
    return index


def load_index():
    if not INDEX_PATH.exists():
        print("Index not found. Run: python mmx_local_index.py --build")
        return []
    with open(INDEX_PATH) as fh:
        return json.load(fh)


def search(keyword, limit=10):
    """
    Return entries whose title contains the keyword (case-insensitive).
    """
    kw = keyword.lower()
    index = load_index()
    matches = [e for e in index if kw in e["title"].lower()]
    return matches[:limit]


def format_matches(matches):
    if not matches:
        return None
    lines = []
    for m in matches:
        lines.append(f"  [{m['source']}] {m['title']}")
        lines.append(f"    Path: {m['path']}")
    return "\n".join(lines)


if __name__ == "__main__":
    if "--build" in sys.argv:
        build_index()
    elif "--search" in sys.argv:
        idx = sys.argv.index("--search")
        if idx + 1 >= len(sys.argv):
            print("Usage: python mmx_local_index.py --search <keyword>")
            sys.exit(1)
        keyword = sys.argv[idx + 1]
        matches = search(keyword)
        if matches:
            print(f"Local source matches for '{keyword}':")
            print(format_matches(matches))
        else:
            print(f"No local sources found matching '{keyword}'.")
    else:
        print(__doc__)
