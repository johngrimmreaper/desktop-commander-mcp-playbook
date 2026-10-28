#!/usr/bin/python3
"""Atomically select a complete root-owned release; caller must stop the unit first."""
import argparse
import os
from pathlib import Path
import re
import stat
import sys

PREFIX = Path("/opt/desktop-commander-mcp")


def select(release_id, user):
    if (os.geteuid() != 0
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,180}", release_id)
            or not re.fullmatch(r"[a-z_][a-z0-9_-]*", user)):
        raise ValueError("invalid caller, account or release ID")
    target = PREFIX / "releases" / release_id
    for path in (PREFIX, PREFIX / "releases", target, target / "release.json"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("release ownership or permissions invalid")
    if not target.is_dir() or not (target / "release.json").is_file():
        raise ValueError("release is incomplete")
    instance = PREFIX / "instances" / user
    for path in (PREFIX / "instances", instance):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0 or info.st_mode & 0o022):
            raise ValueError("instance directory ownership or permissions invalid")
    current = instance / "current"
    if current.exists() and not current.is_symlink():
        raise ValueError("current is not a managed symbolic link")
    temporary = instance / (".current." + str(os.getpid()))
    try:
        temporary.symlink_to(target)
        os.replace(temporary, current)
        descriptor = os.open(instance, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("release_id")
    parser.add_argument("user", help="Account owning this instance")
    args = parser.parse_args()
    try:
        select(args.release_id, args.user)
    except (OSError, ValueError):
        print("Release selection failed; check the installed release and ownership.", file=sys.stderr)
        sys.exit(1)
