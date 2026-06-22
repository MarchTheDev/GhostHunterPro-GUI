from __future__ import annotations

# Delisted / hard-to-find games whose public Steam search may fail,
# return nothing, or return the wrong application.
#
# Keep this file separate so aliases stay easy to maintain without
# cluttering the main app logic.
DELISTED_GAME_ALIASES: dict[str, str] = {
    "f1 2021": "1134570",
    "f12021": "1134570",
    "rocket league": "252950",
    "rocketleague": "252950",
    "fall guys": "1097150",
    "fallguys": "1097150",
    "fall guys ultimate knockout": "1097150",
}

# Canonical names used if Steam metadata is unavailable for these appids.
DELISTED_GAME_METADATA: dict[str, dict[str, str]] = {
    "1134570": {"name": "F1 2021"},
    "252950": {"name": "Rocket League"},
    "1097150": {"name": "Fall Guys"},
}
