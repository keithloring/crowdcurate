#!/usr/bin/env python3

"""
Create a directory of symlinks to images selected by digiKam tags.

Designed for digiKam 7.x SQLite databases.

The digiKam database is ALWAYS opened read-only.

Default behavior:
    NORMAL files     -> symlinked
    TRASH files      -> reported, but NOT symlinked
    MISSING files    -> reported
    UNRESOLVED files -> reported

Use --include-trash if trashed images should also be symlinked.

Example:

    ./digikam_symlinks.py \
        --db "/media/keith/November/data/scans/Documents/digikam4.db" \
        --tag "People/Linda Loring [Hopkins, Moore]" \
        --output "/media/keith/proj/crowdcurate/slidemovielinks/Linda" \
        --dry-run

Then remove --dry-run to create the links.

"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ImageResult:
    image_id: int
    name: str
    file_size: int | None
    unique_hash: str | None
    status: str
    path: Path | None
    detail: str = ""


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def open_database(db_path: Path) -> sqlite3.Connection:
    """Open digiKam database read-only."""

    if not db_path.is_file():
        raise FileNotFoundError(
            f"Database not found: {db_path}"
        )

    uri = f"file:{db_path}?mode=ro"

    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row

    return connection


# ---------------------------------------------------------------------------
# digiKam tags
# ---------------------------------------------------------------------------

def load_tags(
    connection: sqlite3.Connection,
) -> list[tuple[int, str]]:
    """Return (tag_id, full_hierarchical_path)."""

    rows = connection.execute(
        """
        SELECT id, pid, name
        FROM Tags
        ORDER BY pid, name
        """
    ).fetchall()

    tags_by_id = {
        int(row["id"]): row
        for row in rows
    }

    def make_path(tag_id: int) -> str:
        parts: list[str] = []
        current = tag_id
        seen: set[int] = set()

        while current and current in tags_by_id:
            if current in seen:
                raise RuntimeError(
                    f"Cycle in digiKam tag hierarchy at tag {current}"
                )

            seen.add(current)

            row = tags_by_id[current]
            parts.append(row["name"])
            current = row["pid"]

        parts.reverse()

        return "/".join(parts)

    result = [
        (tag_id, make_path(tag_id))
        for tag_id in tags_by_id
    ]

    result.sort(key=lambda x: x[1].lower())

    return result


def find_matching_tag(
    connection: sqlite3.Connection,
    requested: str,
) -> int:
    """
    Find an exact hierarchical tag.

    For example:

        People/Linda Loring [Hopkins, Moore]

    must match that complete tag path.

    A bare tag name is accepted only when it uniquely identifies
    one tag.
    """

    requested = requested.strip().strip("/")

    tags = load_tags(connection)

    exact = [
        tag_id
        for tag_id, path in tags
        if path.casefold() == requested.casefold()
    ]

    if len(exact) == 1:
        return exact[0]

    if len(exact) > 1:
        raise RuntimeError(
            f"Multiple exact matches found for tag {requested!r}"
        )

    # If the user supplied only a leaf name, allow it if unique.
    leaf_matches = [
        tag_id
        for tag_id, path in tags
        if path.rsplit("/", 1)[-1].casefold()
        == requested.casefold()
    ]

    if len(leaf_matches) == 1:
        return leaf_matches[0]

    if not leaf_matches:
        raise RuntimeError(
            f"No digiKam tag found matching {requested!r}"
        )

    paths = dict(tags)

    message = (
        f"Tag {requested!r} is ambiguous. "
        "Use the complete hierarchical path:\n"
    )

    for tag_id in leaf_matches:
        message += f"    {paths[tag_id]}\n"

    raise RuntimeError(message)


# ---------------------------------------------------------------------------
# Image IDs associated with tags
# ---------------------------------------------------------------------------

def get_image_ids_for_tag(
    connection: sqlite3.Connection,
    tag_id: int,
) -> set[int]:

    rows = connection.execute(
        """
        SELECT imageid
        FROM ImageTags
        WHERE tagid = ?
        """,
        (tag_id,),
    ).fetchall()

    return {
        int(row["imageid"])
        for row in rows
    }


# ---------------------------------------------------------------------------
# digiKam album information
# ---------------------------------------------------------------------------

def load_albums(
    connection: sqlite3.Connection,
) -> dict[int, sqlite3.Row]:

    rows = connection.execute(
        """
        SELECT id, albumRoot, relativePath
        FROM Albums
        """
    ).fetchall()

    return {
        int(row["id"]): row
        for row in rows
    }


def load_album_roots(
    connection: sqlite3.Connection,
) -> dict[int, sqlite3.Row]:

    rows = connection.execute(
        """
        SELECT id, identifier, specificPath
        FROM AlbumRoots
        """
    ).fetchall()

    return {
        int(row["id"]): row
        for row in rows
    }


# ---------------------------------------------------------------------------
# Trash handling
# ---------------------------------------------------------------------------

def build_trash_index(
    trash_directory: Path,
) -> dict[str, list[Path]]:
    """
    Build an index of files in digiKam's .dtrash/files directory.

    The key is the filename.

    We retain all candidates because duplicate trash names are possible.
    """

    index: dict[str, list[Path]] = {}

    if not trash_directory.is_dir():
        return index

    print(f"Scanning digiKam trash: {trash_directory}")

    count = 0

    for path in trash_directory.rglob("*"):

        if not path.is_file():
            continue

        index.setdefault(
            path.name.casefold(),
            [],
        ).append(path)

        count += 1

    print(f"Trash files indexed: {count}")

    return index


def trash_candidates(
    original_name: str,
    file_size: int | None,
    trash_index: dict[str, list[Path]],
) -> list[Path]:
    """
    Find likely digiKam-trash versions of an original filename.

    For:

        IMG_20250512_0004.jpg

    digiKam may have:

        IMG_20250512_0004-d6860729.jpg

    We therefore look for:

        exact filename
        filename + '-' + suffix
    """

    result: list[Path] = []

    key = original_name.casefold()

    # Exact name.
    for path in trash_index.get(key, []):
        if file_size is None or path.stat().st_size == file_size:
            result.append(path)

    # digiKam-generated names normally append a '-' suffix.
    prefix = key.rsplit(".", 1)

    if len(prefix) == 2:
        stem, extension = prefix
        prefix_text = f"{stem}-"

        for candidate_name, paths in trash_index.items():

            if not candidate_name.startswith(prefix_text):
                continue

            if not candidate_name.endswith(
                "." + extension
            ):
                continue

            for path in paths:
                try:
                    size = path.stat().st_size
                except OSError:
                    continue

                if file_size is None or size == file_size:
                    result.append(path)

    # Remove duplicates while retaining order.
    seen: set[Path] = set()
    unique: list[Path] = []

    for path in result:
        if path not in seen:
            seen.add(path)
            unique.append(path)

    return unique


# ---------------------------------------------------------------------------
# Resolve an image
# ---------------------------------------------------------------------------

def resolve_image(
    row: sqlite3.Row,
    collection_root: Path,
    albums: dict[int, sqlite3.Row],
    album_roots: dict[int, sqlite3.Row],
    trash_index: dict[str, list[Path]],
) -> ImageResult:

    image_id = int(row["id"])
    name = row["name"]
    file_size = row["fileSize"]
    unique_hash = row["uniqueHash"]
    album_value = row["album"]

    # ---------------------------------------------------------------
    # Normal digiKam album
    # ---------------------------------------------------------------

    if album_value is not None:

        try:
            album_id = int(album_value)
        except (TypeError, ValueError):

            album_id = None

        if album_id is not None:

            album = albums.get(album_id)

            if album is not None:

                root_value = album["albumRoot"]

                if root_value is not None:

                    try:
                        root_id = int(root_value)
                    except (TypeError, ValueError):

                        root_id = None

                    if root_id is not None:

                        root = album_roots.get(root_id)

                        if root is not None:

                            relative_path = (
                                album["relativePath"] or ""
                            )

                            # The database's AlbumRoots.specificPath
                            # is /data/scans/Documents in this case,
                            # while the actual mounted filesystem root
                            # is /media/keith/November/data/scans/Documents.
                            #
                            # Therefore use the directory containing
                            # digikam4.db as the actual collection root.

                            relative_path = (
                                relative_path
                                .lstrip("/")
                            )

                            path = (
                                collection_root
                                / relative_path
                                / name
                            )

                            if path.is_file():

                                return ImageResult(
                                    image_id=image_id,
                                    name=name,
                                    file_size=file_size,
                                    unique_hash=unique_hash,
                                    status="NORMAL",
                                    path=path,
                                    detail="valid digiKam album",
                                )

                            return ImageResult(
                                image_id=image_id,
                                name=name,
                                file_size=file_size,
                                unique_hash=unique_hash,
                                status="MISSING",
                                path=None,
                                detail=(
                                    "digiKam album path does not "
                                    f"exist: {path}"
                                ),
                            )

    # ---------------------------------------------------------------
    # album=NULL or otherwise unresolved:
    # look in digiKam trash.
    # ---------------------------------------------------------------

    candidates = trash_candidates(
        original_name=name,
        file_size=file_size,
        trash_index=trash_index,
    )

    if len(candidates) == 1:

        return ImageResult(
            image_id=image_id,
            name=name,
            file_size=file_size,
            unique_hash=unique_hash,
            status="TRASH",
            path=candidates[0],
            detail="matching file found in digiKam trash",
        )

    if len(candidates) > 1:

        return ImageResult(
            image_id=image_id,
            name=name,
            file_size=file_size,
            unique_hash=unique_hash,
            status="TRASH",
            path=None,
            detail=(
                "multiple matching files found in digiKam trash: "
                + "; ".join(str(p) for p in candidates)
            ),
        )

    # ---------------------------------------------------------------
    # Nothing found.
    # ---------------------------------------------------------------

    return ImageResult(
        image_id=image_id,
        name=name,
        file_size=file_size,
        unique_hash=unique_hash,
        status="UNRESOLVED",
        path=None,
        detail=(
            "album is NULL and no matching file was found "
            "in digiKam trash"
        ),
    )


# ---------------------------------------------------------------------------
# Symlink handling
# ---------------------------------------------------------------------------

def unique_destination(
    destination: Path,
) -> Path:

    if not destination.exists() and not destination.is_symlink():
        return destination

    stem = destination.stem
    suffix = destination.suffix

    counter = 2

    while True:

        candidate = destination.with_name(
            f"{stem}__{counter}{suffix}"
        )

        if (
            not candidate.exists()
            and not candidate.is_symlink()
        ):
            return candidate

        counter += 1


def create_symlinks(
    results: list[ImageResult],
    output: Path,
    dry_run: bool,
    include_trash: bool,
) -> tuple[int, int]:

    if not dry_run:
        output.mkdir(
            parents=True,
            exist_ok=True,
        )

    created = 0
    skipped = 0

    for result in results:

        if result.status == "NORMAL":
            pass

        elif (
            result.status == "TRASH"
            and include_trash
            and result.path is not None
        ):
            pass

        else:
            skipped += 1
            continue

        source = result.path

        if source is None:
            skipped += 1
            continue

        destination = output / result.name

        original_destination = destination

        if (
            destination.exists()
            or destination.is_symlink()
        ):
            destination = unique_destination(
                destination
            )

            print(
                f"COLLISION: {original_destination.name}"
                f" -> {destination.name}"
            )

        try:
            relative_source = os.path.relpath(
                source,
                output,
            )
        except ValueError:
            relative_source = str(source)

        print(
            f"LINK: {destination.name} -> "
            f"{relative_source}"
        )

        if not dry_run:

            destination.symlink_to(
                relative_source
            )

        created += 1

    return created, skipped


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    report_path: Path,
    results: list[ImageResult],
) -> None:

    counts: dict[str, int] = {}

    for result in results:
        counts[result.status] = (
            counts.get(result.status, 0) + 1
        )

    with report_path.open(
        "w",
        encoding="utf-8",
    ) as f:

        f.write("digiKam Symlink Report\n")
        f.write("=" * 80 + "\n\n")

        f.write("Summary\n")
        f.write("-" * 80 + "\n")

        for status in (
            "NORMAL",
            "TRASH",
            "MISSING",
            "UNRESOLVED",
        ):
            f.write(
                f"{status:12}: "
                f"{counts.get(status, 0)}\n"
            )

        f.write("\n")

        for status in (
            "TRASH",
            "MISSING",
            "UNRESOLVED",
        ):

            matching = [
                r
                for r in results
                if r.status == status
            ]

            if not matching:
                continue

            f.write("\n")
            f.write(status)
            f.write("\n")
            f.write("-" * 80)
            f.write("\n")

            for result in matching:

                f.write(
                    f"\nID:       {result.image_id}\n"
                )

                f.write(
                    f"Filename: {result.name}\n"
                )

                f.write(
                    f"Size:     {result.file_size}\n"
                )

                f.write(
                    f"Hash:     {result.unique_hash}\n"
                )

                if result.path:
                    f.write(
                        f"Path:     {result.path}\n"
                    )

                f.write(
                    f"Detail:   {result.detail}\n"
                )


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Create symlinks to digiKam-tagged images "
            "without modifying digiKam."
        )
    )

    parser.add_argument(
        "--db",
        required=True,
        type=Path,
        help="Path to digiKam digikam4.db",
    )

    parser.add_argument(
        "--tag",
        action="append",
        required=True,
        help=(
            "digiKam tag. Can be specified more than once."
        ),
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "With multiple --tag arguments, require "
            "images to have ALL tags."
        ),
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination directory for symlinks.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show what would happen without creating "
            "directories or symlinks."
        ),
    )

    parser.add_argument(
        "--include-trash",
        action="store_true",
        help=(
            "Also symlink images found in digiKam's "
            ".dtrash/files directory."
        ),
    )

    parser.add_argument(
        "--list-tags",
        action="store_true",
        help="List digiKam tags and exit.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:

    args = parse_arguments()

    db_path = args.db.resolve()

    # Your database is:
    #
    # /media/keith/November/data/scans/Documents/digikam4.db
    #
    # Therefore the actual mounted collection root is the
    # directory containing digikam4.db.

    collection_root = db_path.parent

    trash_directory = (
        collection_root
        / ".dtrash"
        / "files"
    )

    print()
    print("digiKam Symlink Utility")
    print("=" * 60)
    print(f"Database:       {db_path}")
    print(f"Collection:     {collection_root}")
    print(f"Trash:          {trash_directory}")
    print()

    try:
        connection = open_database(db_path)
    except Exception as exc:
        print(
            f"ERROR opening database: {exc}",
            file=sys.stderr,
        )
        return 1

    try:

        # -----------------------------------------------------------
        # List tags
        # -----------------------------------------------------------

        if args.list_tags:

            for tag_id, path in load_tags(connection):
                print(f"{tag_id:6}  {path}")

            return 0

        # -----------------------------------------------------------
        # Resolve requested tags
        # -----------------------------------------------------------

        tag_ids: list[int] = []

        for requested in args.tag:

            try:
                tag_id = find_matching_tag(
                    connection,
                    requested,
                )
            except RuntimeError as exc:

                print(
                    f"ERROR: {exc}",
                    file=sys.stderr,
                )

                return 2

            tag_ids.append(tag_id)

        # -----------------------------------------------------------
        # Find image IDs
        # -----------------------------------------------------------

        image_sets = [
            get_image_ids_for_tag(
                connection,
                tag_id,
            )
            for tag_id in tag_ids
        ]

        if args.all:
            image_ids = set.intersection(
                *image_sets
            )
        else:
            image_ids = set.union(
                *image_sets
            )

        print(
            "Tags:"
        )

        for requested, tag_id in zip(
            args.tag,
            tag_ids,
        ):
            print(
                f"    {requested} "
                f"(tag ID {tag_id})"
            )

        print()
        print(
            "Selection: "
            + (
                "ALL specified tags"
                if args.all
                else "ANY specified tag"
            )
        )

        print(
            f"Tagged image records: {len(image_ids)}"
        )

        print(
            f"Output directory: {args.output}"
        )

        print(
            "Mode: "
            + (
                "DRY RUN"
                if args.dry_run
                else "CREATE SYMLINKS"
            )
        )

        print(
            "Include trash: "
            + ("YES" if args.include_trash else "NO")
        )

        print()

        # -----------------------------------------------------------
        # Load database relationships
        # -----------------------------------------------------------

        albums = load_albums(connection)
        album_roots = load_album_roots(connection)

        placeholders = ",".join(
            "?" for _ in image_ids
        )

        if not image_ids:
            print("No matching images.")
            return 0

        rows = connection.execute(
            f"""
            SELECT
                id,
                album,
                name,
                status,
                category,
                modificationDate,
                fileSize,
                uniqueHash,
                manualOrder
            FROM Images
            WHERE id IN ({placeholders})
            ORDER BY name
            """,
            sorted(image_ids),
        ).fetchall()

        # -----------------------------------------------------------
        # Build trash index
        # -----------------------------------------------------------

        trash_index = build_trash_index(
            trash_directory
        )

        print()

        # -----------------------------------------------------------
        # Resolve each image
        # -----------------------------------------------------------

        results: list[ImageResult] = []

        for row in rows:

            result = resolve_image(
                row=row,
                collection_root=collection_root,
                albums=albums,
                album_roots=album_roots,
                trash_index=trash_index,
            )

            results.append(result)

        # -----------------------------------------------------------
        # Summary
        # -----------------------------------------------------------

        counts: dict[str, int] = {}

        for result in results:
            counts[result.status] = (
                counts.get(result.status, 0) + 1
            )

        print("=" * 60)
        print("Resolution summary")
        print("=" * 60)

        for status in (
            "NORMAL",
            "TRASH",
            "MISSING",
            "UNRESOLVED",
        ):
            print(
                f"{status:12}: "
                f"{counts.get(status, 0)}"
            )

        print()

        # -----------------------------------------------------------
        # Create report
        # -----------------------------------------------------------

        report_path = args.output.parent / (
            args.output.name + "_report.txt"
        )

        write_report(
            report_path,
            results,
        )

        print(
            f"Report: {report_path}"
        )

        print()

        # -----------------------------------------------------------
        # Create symlinks
        # -----------------------------------------------------------

        created, skipped = create_symlinks(
            results=results,
            output=args.output,
            dry_run=args.dry_run,
            include_trash=args.include_trash,
        )

        print()
        print("=" * 60)
        print("Symlink summary")
        print("=" * 60)
        print(f"Links created/would create: {created}")
        print(f"Skipped:                    {skipped}")

        if args.dry_run:
            print()
            print(
                "DRY RUN: no directories or symlinks "
                "were created."
            )

        return 0

    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())