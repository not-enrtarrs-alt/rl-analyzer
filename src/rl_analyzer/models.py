"""Shared, secret-free configuration models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Player:
    """A fixed player identified by normalized ballchasing platform ID."""

    id: str
    alias: str
