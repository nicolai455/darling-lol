"""Shared host-side destinations for configured runtime installers."""
import os
from pathlib import Path


def runtime_paths(config):
    prefix = Path(os.environ.get("DPREFIX") or config["prefix"])
    guest_home = Path(os.environ.get("RIOT_GUEST_HOME") or
                      str(prefix / config["guest_home"].lstrip("/")))
    if not prefix.is_absolute() or not guest_home.is_absolute():
        raise ValueError("Runtime paths must be absolute host paths")
    if ".." in guest_home.parts or not guest_home.is_relative_to(prefix) or guest_home == prefix:
        raise ValueError("RIOT_GUEST_HOME must be inside DPREFIX")
    return prefix, guest_home
