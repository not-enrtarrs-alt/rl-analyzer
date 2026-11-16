"""Shared SQL predicate for matching any known replay match identifier."""


def identity_where(match_key: str, match_guid: str | None = None,
                   rocket_league_id: str | None = None) -> tuple[str, list[str]]:
    """Match canonical keys and same-kind identifiers, ignoring hex-ID case."""
    clauses = ["match_key = ? COLLATE NOCASE"]
    values = [match_key]
    for column, value in (("match_guid", match_guid), ("rocket_league_id", rocket_league_id)):
        if isinstance(value, str) and value.strip():
            value = value.strip()
            clauses.extend([f"{column} = ? COLLATE NOCASE", "match_key = ? COLLATE NOCASE"])
            values.extend([value, value])
    return "(" + " OR ".join(clauses) + ")", values
