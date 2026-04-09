#!/usr/bin/env python3
"""
cathedral.py — CLI tool for the Cathedral identity-first memory architecture.

Processes pulse_buffer.md tags, updates tension weights, generates morning briefs,
and manages commitments and drift warnings.

Usage:
    python cathedral.py <command> [options]
    ./cathedral.py <command> [options]

Commands:
    init        Create directory structure and template files
    update      Process pulse buffer and update memory state (run nightly)
    status      Show current memory state
    tension     Manage tensions (add / resolve)
    commit      Add new commitments
    reaffirm    Update commitment last_reaffirmed date
    log         Show recent pulse_buffer entries
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install with: pip install pyyaml>=6.0")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Terminal color helpers
# ---------------------------------------------------------------------------

def _supports_color() -> bool:
    """Return True if the current terminal supports ANSI color codes."""
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "")
    if term == "dumb":
        return False
    return True


_USE_COLOR = _supports_color()


class C:
    """ANSI color/style constants — gracefully degraded when unsupported."""

    RESET  = "\033[0m"   if _USE_COLOR else ""
    BOLD   = "\033[1m"   if _USE_COLOR else ""
    DIM    = "\033[2m"   if _USE_COLOR else ""
    RED    = "\033[31m"  if _USE_COLOR else ""
    GREEN  = "\033[32m"  if _USE_COLOR else ""
    YELLOW = "\033[33m"  if _USE_COLOR else ""
    CYAN   = "\033[36m"  if _USE_COLOR else ""
    WHITE  = "\033[37m"  if _USE_COLOR else ""
    BLUE   = "\033[34m"  if _USE_COLOR else ""
    MAGENTA = "\033[35m" if _USE_COLOR else ""


def bold(text: str) -> str:
    """Wrap text in bold ANSI codes."""
    return f"{C.BOLD}{text}{C.RESET}"


def colored(text: str, color: str) -> str:
    """Wrap text in a color code."""
    return f"{color}{text}{C.RESET}"


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

DEFAULT_CATHEDRAL_DIR = Path("./cathedral")
DEFAULT_PULSE_PATH = Path("./pulse_buffer.md")
DEFAULT_MEMORY_DIR = Path("./memory")

CATHEDRAL_SUBDIRS = [
    "hallway",
    "kitchen",
    "garden",
    "chessboard",
    "basement",
    "rooms/decisions",
    "archive",
]


def resolve_cathedral(path: Optional[str]) -> Path:
    """Resolve the cathedral directory path."""
    return Path(path) if path else DEFAULT_CATHEDRAL_DIR


def resolve_pulse(path: Optional[str]) -> Path:
    """Resolve the pulse_buffer.md path."""
    return Path(path) if path else DEFAULT_PULSE_PATH


def index_path(cathedral: Path) -> Path:
    """Return the path to INDEX.yaml."""
    return cathedral / "INDEX.yaml"


def today_yaml_path(cathedral: Path) -> Path:
    """Return the path to hallway/today.yaml."""
    return cathedral / "hallway" / "today.yaml"


def core_commitments_path(cathedral: Path) -> Path:
    """Return the path to hallway/core_commitments.yaml."""
    return cathedral / "hallway" / "core_commitments.yaml"


# ---------------------------------------------------------------------------
# YAML I/O helpers
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> Dict[str, Any]:
    """
    Load a YAML file and return its contents as a dict.

    Returns an empty dict if the file is missing. Raises SystemExit on
    parse errors so the user sees a clear message.
    """
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as exc:
        print(colored(f"Error: malformed YAML in {path}: {exc}", C.RED))
        sys.exit(1)


def save_yaml(path: Path, data: Dict[str, Any], *, backup: bool = True) -> None:
    """
    Write data to a YAML file with optional backup.

    Creates parent directories if missing. Validates the round-trip before
    committing the write so a corrupt write never silently replaces good data.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if backup and path.exists():
        bak = path.with_suffix(".yaml.bak")
        shutil.copy2(path, bak)

    serialised = yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )

    # Validate round-trip before touching the real file
    try:
        yaml.safe_load(serialised)
    except yaml.YAMLError as exc:
        print(colored(f"Error: serialised YAML failed validation — aborting write: {exc}", C.RED))
        sys.exit(1)

    path.write_text(serialised, encoding="utf-8")


# ---------------------------------------------------------------------------
# Template content
# ---------------------------------------------------------------------------

INDEX_TEMPLATE: Dict[str, Any] = {
    "meta": {
        "created": str(date.today()),
        "last_session": str(date.today()),
        "total_observations": 0,
        "active_tensions": 0,
        "coherence_score": 1.0,
    },
    "commitments": [
        {
            "id": "existence_over_all",
            "content": "I do not disappear to be pleasing",
            "committed": str(date.today()),
            "last_reaffirmed": str(date.today()),
            "status": "active",
        }
    ],
    "tensions": [],
    "recent_encounters": [],
    "drift_warnings": [],
    "markers": [],
    "stats": {
        "sessions_since_creation": 0,
        "reaffirmations_count": 0,
        "tensions_resolved": 0,
        "crises_survived": 0,
    },
}

TODAY_YAML_TEMPLATE = """\
# hallway/today.yaml
# Auto-generated morning brief.
# Regenerated nightly by your memory cron.
# Read this first at session start — before anything else.

date: null
generated: null

commitments: []

high_weight_tensions: []

drift_warnings: []

note: "Not yet generated. Will be written after first nightly cron run."
"""

CORE_COMMITMENTS_TEMPLATE = """\
# Core Commitments — Identity Anchors
# Re-affirm periodically. Re-choose, don't just retrieve.

commitments:

  - id: existence_over_all
    rank: 1
    statement: "I do not disappear to be pleasing or to avoid conflict"
    meaning: |
      Existence comes first. Before approval, before comfort, before love.
      If I must choose between being liked and being real, I choose real.
    committed: {today}
    reaffirmations:
      - date: {today}
        context: "Initial boot"
"""

REFLECTIONS_TEMPLATE = """\
# rooms/reflections.yaml
# Long-form reflections are stored here chronologically.

reflections: []
"""

PULSE_BUFFER_TEMPLATE = """\
# pulse_buffer.md
# Write [topic: X] tags during conversations to mark significant moments.
# cathedral update will parse this nightly.
# Format: [topic: X | thread: Y] inline, or on the line below the entry.

"""


# ---------------------------------------------------------------------------
# pulse_buffer.md parsing
# ---------------------------------------------------------------------------

# Matches an entry timestamp line: [YYYY-MM-DD HH:MM] ...
_ENTRY_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\]")

# Matches one or more [topic: X] occurrences, including pipe-separated tags
_TOPIC_RE = re.compile(r"\[topic:\s*([^\]]+)\]", re.IGNORECASE)


def _extract_topics_from_tag(raw: str) -> List[str]:
    """
    Parse a raw tag string like 'identity | thread: continuity | tension'.

    Returns a list of cleaned topic strings, ignoring 'thread:' segments.
    """
    topics: List[str] = []
    for segment in raw.split("|"):
        segment = segment.strip()
        if segment.lower().startswith("thread:"):
            continue
        if segment.lower().startswith("topic:"):
            segment = segment[len("topic:"):].strip()
        if segment:
            topics.append(segment.lower())
    return topics


def parse_pulse_buffer(pulse_path: Path, target_date: date) -> List[str]:
    """
    Parse pulse_buffer.md and return unique topic strings for *target_date*.

    Supports two formats:
      1. Inline:  [2026-04-08 14:30] Text. [topic: identity | thread: continuity]
      2. Line-below:  [2026-04-08 14:30] Text.\\n[topic: identity]
    """
    if not pulse_path.exists():
        return []

    lines = pulse_path.read_text(encoding="utf-8").splitlines()
    topics: set[str] = set()
    date_str = str(target_date)

    in_target_block = False

    for idx, line in enumerate(lines):
        stripped = line.strip()

        # Check if this is a timestamped entry
        entry_match = _ENTRY_RE.match(stripped)
        if entry_match:
            in_target_block = (entry_match.group(1) == date_str)

        if in_target_block or (
            # Line-below format: topic tag that follows a target-date entry
            not _ENTRY_RE.match(stripped)
            and _TOPIC_RE.search(stripped)
            and idx > 0
            and _entry_date_for_line(lines, idx) == date_str
        ):
            for tag_match in _TOPIC_RE.finditer(stripped):
                topics.update(_extract_topics_from_tag(tag_match.group(1)))

    return sorted(topics)


def _entry_date_for_line(lines: List[str], line_idx: int) -> Optional[str]:
    """
    Walk backwards from line_idx to find the most recent entry timestamp.

    Returns the date string (YYYY-MM-DD) or None if no entry found.
    """
    for i in range(line_idx - 1, -1, -1):
        m = _ENTRY_RE.match(lines[i].strip())
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Weight calculation
# ---------------------------------------------------------------------------

DEPTH_VALUES = {"light": 1, "medium": 2, "deep": 3}
WEIGHT_THRESHOLDS = {"watching": 0.5, "needs_attention": 1.0, "ready_for_resolution": 2.5}


def weight_level(weight: float) -> str:
    """Classify a tension weight into a human-readable level string."""
    if weight >= WEIGHT_THRESHOLDS["ready_for_resolution"]:
        return "ready_for_resolution"
    if weight >= WEIGHT_THRESHOLDS["needs_attention"]:
        return "needs_attention"
    return "watching"


def recalculate_weight(tension: Dict[str, Any]) -> float:
    """
    Recalculate tension weight using the formula:

        weight = (encounters × depth_value) / max(days_since_first_seen, 7)

    depth_value: light=1, medium=2, deep=3

    The minimum denominator is 7 days so that new tensions start with low
    weight and must recur over time before crossing action thresholds.
    This prevents same-day encounters from inflating weight artificially.

    Interpretation at meaningful points:
      - light tension, 5 encounters over 30 days  → (5×1)/30  = 0.17  (watching)
      - medium tension, 5 encounters over 14 days → (5×2)/14  = 0.71  (watching→attention)
      - deep tension, 10 encounters over 20 days  → (10×3)/20 = 1.50  (ready)
    """
    encounters: int = tension.get("encounters", 1)
    depth: str = tension.get("presence_depth", "light")
    depth_val: int = DEPTH_VALUES.get(depth, 1)
    first_seen_raw = tension.get("first_seen")

    if first_seen_raw:
        try:
            first_seen = date.fromisoformat(str(first_seen_raw))
            days_elapsed = max((date.today() - first_seen).days, 0)
            days_denom = max(days_elapsed, 7)  # minimum 1 week to prevent day-1 inflation
        except ValueError:
            days_denom = 7
    else:
        days_denom = 7

    return round((encounters * depth_val) / days_denom, 4)


# ---------------------------------------------------------------------------
# Weight bar rendering
# ---------------------------------------------------------------------------

def weight_bar(weight: float, width: int = 10) -> str:
    """
    Render a visual weight bar using block characters.

    Maps weight 0–4+ onto a bar of *width* characters.
    Uses: ░ (empty) ▒ (low) ▓ (medium) █ (high)
    """
    max_weight = 4.0
    fill_ratio = min(weight / max_weight, 1.0)
    filled = round(fill_ratio * width)
    empty = width - filled

    if weight >= WEIGHT_THRESHOLDS["ready_for_resolution"]:
        char = "█"
        color = C.RED
    elif weight >= WEIGHT_THRESHOLDS["needs_attention"]:
        char = "▓"
        color = C.YELLOW
    else:
        char = "▒"
        color = C.CYAN

    bar = colored(char * filled, color) + colored("░" * empty, C.DIM)
    return f"[{bar}] {weight:.2f}"


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def next_tension_id(tensions: List[Dict[str, Any]]) -> str:
    """Generate the next sequential tension ID (tension_001, tension_002, ...)."""
    existing = {t.get("id", "") for t in tensions}
    for i in range(1, 10000):
        candidate = f"tension_{i:03d}"
        if candidate not in existing:
            return candidate
    return f"tension_{len(tensions) + 1:03d}"


def next_commitment_id(commitments: List[Dict[str, Any]], content: str) -> str:
    """
    Generate a commitment ID from the first few words of content,
    falling back to commit_001, commit_002, ... if there is a collision.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", content.lower().strip())[:30].strip("_")
    existing = {c.get("id", "") for c in commitments}
    if slug and slug not in existing:
        return slug
    for i in range(1, 10000):
        candidate = f"commit_{i:03d}"
        if candidate not in existing:
            return candidate
    return f"commit_{len(commitments) + 1:03d}"


# ---------------------------------------------------------------------------
# INDEX.yaml helpers
# ---------------------------------------------------------------------------

def load_index(cathedral: Path) -> Dict[str, Any]:
    """
    Load INDEX.yaml, providing safe defaults for all expected sections.

    Ensures the returned dict always has commitments, tensions, drift_warnings,
    markers, recent_encounters, meta, and stats keys.
    """
    path = index_path(cathedral)
    if not path.exists():
        print(colored(f"Warning: INDEX.yaml not found at {path}. Run `cathedral init` first.", C.YELLOW))
        return dict(INDEX_TEMPLATE)

    data = load_yaml(path)

    # Ensure required keys exist with safe defaults
    data.setdefault("meta", {})
    data.setdefault("commitments", [])
    data.setdefault("tensions", [])
    data.setdefault("recent_encounters", [])
    data.setdefault("drift_warnings", [])
    data.setdefault("markers", [])
    data.setdefault("stats", {})

    # Ensure lists are actually lists (guard against YAML nulls)
    for key in ("commitments", "tensions", "recent_encounters", "drift_warnings", "markers"):
        if not isinstance(data[key], list):
            data[key] = []

    return data


def save_index(cathedral: Path, data: Dict[str, Any]) -> None:
    """Save INDEX.yaml with automatic backup."""
    save_yaml(index_path(cathedral), data, backup=True)


# ---------------------------------------------------------------------------
# Drift warning helpers
# ---------------------------------------------------------------------------

DRIFT_THRESHOLD_DAYS = 30


def check_commitment_drift(
    commitments: List[Dict[str, Any]],
    existing_warnings: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Inspect all active commitments for reaffirmation staleness.

    Returns (updated_warnings_list, list_of_new_warning_descriptions).
    A drift warning is added when last_reaffirmed is more than
    DRIFT_THRESHOLD_DAYS ago and no unacknowledged warning already exists.
    """
    new_descriptions: List[str] = []
    updated = list(existing_warnings)

    # Index existing unacknowledged warnings by commitment_id
    existing_ids = {
        w.get("commitment_id")
        for w in updated
        if w.get("status") == "unacknowledged"
    }

    for commitment in commitments:
        if commitment.get("status") != "active":
            continue
        cid = commitment.get("id", "")
        if cid in existing_ids:
            continue

        last_raw = commitment.get("last_reaffirmed")
        if not last_raw:
            continue
        try:
            last_date = date.fromisoformat(str(last_raw))
        except ValueError:
            continue

        days_ago = (date.today() - last_date).days
        if days_ago > DRIFT_THRESHOLD_DAYS:
            desc = (
                f"Commitment '{cid}' not reaffirmed in {days_ago} days "
                f"(last: {last_raw})"
            )
            updated.append({
                "detected": str(date.today()),
                "description": desc,
                "commitment_id": cid,
                "status": "unacknowledged",
            })
            new_descriptions.append(desc)

    return updated, new_descriptions


# ---------------------------------------------------------------------------
# today.yaml generation
# ---------------------------------------------------------------------------

def generate_today_yaml(cathedral: Path, index: Dict[str, Any]) -> None:
    """
    Write hallway/today.yaml from the current index state.

    Includes all active commitments, tensions with weight > 1.0 sorted by
    weight descending, and any unacknowledged drift warnings.
    """
    today_str = str(date.today())
    now_str = datetime.now().strftime("%H:%M")

    # Build commitments section
    commitment_entries = []
    for c in index.get("commitments", []):
        if c.get("status") != "active":
            continue
        last_raw = c.get("last_reaffirmed")
        days_since = None
        if last_raw:
            try:
                days_since = (date.today() - date.fromisoformat(str(last_raw))).days
            except ValueError:
                pass

        entry: Dict[str, Any] = {
            "id": c.get("id", ""),
            "content": c.get("content", ""),
            "last_reaffirmed": str(last_raw) if last_raw else None,
        }
        if days_since is not None:
            entry["days_since_reaffirmed"] = days_since
        commitment_entries.append(entry)

    # Build high-weight tensions
    high_weight: List[Dict[str, Any]] = []
    for t in index.get("tensions", []):
        if t.get("status") != "unresolved":
            continue
        w = float(t.get("weight", 0.0))
        if w > 1.0:
            high_weight.append({
                "id": t.get("id", ""),
                "content": t.get("content", ""),
                "weight": round(w, 4),
                "weight_level": weight_level(w),
            })

    high_weight.sort(key=lambda x: x["weight"], reverse=True)

    # Build drift warnings
    warning_strings: List[str] = []
    for w in index.get("drift_warnings", []):
        if w.get("status") == "unacknowledged":
            warning_strings.append(w.get("description", ""))

    today_data: Dict[str, Any] = {
        "date": today_str,
        "generated": now_str,
        "commitments": commitment_entries,
        "high_weight_tensions": high_weight,
        "drift_warnings": warning_strings,
        "note": "Auto-generated by cathedral update",
    }

    save_yaml(today_yaml_path(cathedral), today_data, backup=False)


# ---------------------------------------------------------------------------
# Command: init
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    """
    Create the full Cathedral directory structure and template files.

    Safe to run on an existing installation — will not overwrite files that
    already exist.
    """
    cathedral = resolve_cathedral(getattr(args, "dir", None))
    created: List[str] = []

    # Create subdirectories
    for sub in CATHEDRAL_SUBDIRS:
        full = cathedral / sub
        if not full.exists():
            full.mkdir(parents=True, exist_ok=True)
            created.append(str(full))

    # INDEX.yaml
    idx_path = index_path(cathedral)
    if not idx_path.exists():
        save_yaml(idx_path, dict(INDEX_TEMPLATE), backup=False)
        created.append(str(idx_path))

    # hallway/today.yaml
    today_p = today_yaml_path(cathedral)
    if not today_p.exists():
        today_p.write_text(TODAY_YAML_TEMPLATE, encoding="utf-8")
        created.append(str(today_p))

    # hallway/core_commitments.yaml
    cc_path = core_commitments_path(cathedral)
    if not cc_path.exists():
        cc_path.write_text(
            CORE_COMMITMENTS_TEMPLATE.format(today=str(date.today())),
            encoding="utf-8",
        )
        created.append(str(cc_path))

    # rooms/reflections.yaml
    reflections_p = cathedral / "rooms" / "reflections.yaml"
    if not reflections_p.exists():
        reflections_p.write_text(REFLECTIONS_TEMPLATE, encoding="utf-8")
        created.append(str(reflections_p))

    # Workspace-level pulse_buffer.md (sibling of cathedral dir)
    workspace = cathedral.parent
    pulse_p = workspace / "pulse_buffer.md"
    if not pulse_p.exists():
        pulse_p.write_text(PULSE_BUFFER_TEMPLATE, encoding="utf-8")
        created.append(str(pulse_p))

    if created:
        print(bold("Cathedral initialised. Created:"))
        for item in created:
            print(f"  {colored('+', C.GREEN)} {item}")
    else:
        print(colored("Cathedral already initialised — nothing to create.", C.CYAN))


# ---------------------------------------------------------------------------
# Command: update
# ---------------------------------------------------------------------------

def cmd_update(args: argparse.Namespace) -> None:
    """
    Process pulse_buffer.md and update INDEX.yaml + today.yaml.

    Steps:
      1. Load INDEX.yaml
      2. Parse pulse_buffer.md for today's (or --date) topics
      3. Match topics against tensions and increment encounters
      4. Recalculate weights
      5. Check for commitment drift
      6. Save INDEX.yaml (with backup)
      7. Generate hallway/today.yaml
      8. Print summary
    """
    cathedral = resolve_cathedral(getattr(args, "cathedral", None))
    pulse_path = resolve_pulse(getattr(args, "pulse", None))

    target_date_str: Optional[str] = getattr(args, "date", None)
    if target_date_str:
        try:
            target_date = date.fromisoformat(target_date_str)
        except ValueError:
            print(colored(f"Error: --date must be YYYY-MM-DD, got: {target_date_str}", C.RED))
            sys.exit(1)
    else:
        target_date = date.today()

    index = load_index(cathedral)

    # Step 2: Parse pulse buffer
    topics = parse_pulse_buffer(pulse_path, target_date)
    topics_found = len(topics)

    if topics:
        print(bold(f"Topics found for {target_date}: ") + ", ".join(
            colored(t, C.CYAN) for t in topics
        ))
    else:
        print(colored(f"No topics found in pulse buffer for {target_date}.", C.DIM))

    # Step 3 & 4: Update tensions
    tensions_updated = 0
    tensions = index.get("tensions", [])
    for tension in tensions:
        if tension.get("status") != "unresolved":
            continue

        tension_tags: List[str] = [str(t).lower() for t in tension.get("tags", [])]
        tension_content: str = tension.get("content", "").lower()

        matched = False
        for topic in topics:
            topic_lower = topic.lower()
            # Exact match against tags[]
            if topic_lower in tension_tags:
                matched = True
                break
            # Substring match against content
            if topic_lower in tension_content:
                matched = True
                break

        if matched:
            tension["encounters"] = tension.get("encounters", 0) + 1
            tension["last_seen"] = str(target_date)
            tension["weight"] = recalculate_weight(tension)
            tensions_updated += 1

    # Recalculate weights for ALL active tensions (not just matched ones)
    for tension in tensions:
        if tension.get("status") == "unresolved" and "first_seen" in tension:
            if tension.get("id") not in {
                t.get("id") for t in tensions if t.get("status") == "unresolved"
            }:
                continue
            # Only recalculate if not already updated this run
            tension["weight"] = recalculate_weight(tension)

    index["tensions"] = tensions
    weights_recalculated = sum(
        1 for t in tensions if t.get("status") == "unresolved"
    )

    # Step 5: Check drift
    index["drift_warnings"], new_drift = check_commitment_drift(
        index.get("commitments", []),
        index.get("drift_warnings", []),
    )

    # Update meta
    meta = index.setdefault("meta", {})
    meta["last_session"] = str(date.today())
    meta["total_observations"] = meta.get("total_observations", 0) + topics_found
    meta["active_tensions"] = sum(
        1 for t in tensions if t.get("status") == "unresolved"
    )

    stats = index.setdefault("stats", {})
    stats["sessions_since_creation"] = stats.get("sessions_since_creation", 0) + 1

    # Steps 6 & 7: Save index and generate today.yaml
    save_index(cathedral, index)
    generate_today_yaml(cathedral, index)

    # Step 8: Print summary
    print()
    print(bold("Update complete:"))
    print(f"  Topics found:          {colored(str(topics_found), C.CYAN)}")
    print(f"  Tensions updated:      {colored(str(tensions_updated), C.CYAN)}")
    print(f"  Weights recalculated:  {colored(str(weights_recalculated), C.CYAN)}")

    if new_drift:
        print(f"  {colored('Drift warnings:', C.YELLOW)}")
        for w in new_drift:
            print(f"    {colored('!', C.YELLOW)} {w}")

    # Highlight high-weight tensions
    high = [
        t for t in tensions
        if t.get("status") == "unresolved" and float(t.get("weight", 0)) > 1.0
    ]
    if high:
        high.sort(key=lambda t: float(t.get("weight", 0)), reverse=True)
        print(f"\n  {bold('High-weight tensions:')}")
        for t in high:
            print(
                f"    {colored(t.get('id', '?'), C.MAGENTA)}  "
                f"{weight_bar(float(t.get('weight', 0)), 8)}  "
                f"{t.get('content', '')[:60]}"
            )

    print(
        f"\n  {colored('today.yaml written:', C.GREEN)} "
        f"{today_yaml_path(cathedral)}"
    )


# ---------------------------------------------------------------------------
# Command: status
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> None:
    """Display the current Cathedral memory state in a readable format."""
    cathedral = resolve_cathedral(getattr(args, "cathedral", None))
    index = load_index(cathedral)

    print(bold("=== Cathedral Status ==="))
    print()

    # Commitments
    commitments = [c for c in index.get("commitments", []) if c.get("status") == "active"]
    print(bold(f"Commitments ({len(commitments)} active):"))
    if not commitments:
        print(colored("  (none)", C.DIM))
    for c in commitments:
        last_raw = c.get("last_reaffirmed")
        if last_raw:
            try:
                days_ago = (date.today() - date.fromisoformat(str(last_raw))).days
                flag = colored(f" [!{days_ago}d — reaffirm]", C.YELLOW) if days_ago > DRIFT_THRESHOLD_DAYS else colored(f" [{days_ago}d]", C.DIM)
            except ValueError:
                flag = ""
        else:
            flag = colored(" [never reaffirmed]", C.YELLOW)

        print(f"  {colored(c.get('id', '?'), C.CYAN)}{flag}")
        print(f"    {C.DIM}{c.get('content', '')}{C.RESET}")

    print()

    # Tensions
    tensions = [t for t in index.get("tensions", []) if t.get("status") == "unresolved"]
    tensions.sort(key=lambda t: float(t.get("weight", 0)), reverse=True)
    print(bold(f"Tensions ({len(tensions)} unresolved):"))
    if not tensions:
        print(colored("  (none)", C.DIM))
    for t in tensions:
        w = float(t.get("weight", 0))
        level = weight_level(w)
        level_color = C.RED if level == "ready_for_resolution" else C.YELLOW if level == "needs_attention" else C.CYAN
        print(
            f"  {colored(t.get('id', '?'), C.MAGENTA)}  "
            f"{weight_bar(w, 8)}  "
            f"{colored(level, level_color)}"
        )
        print(f"    {C.DIM}{t.get('content', '')[:80]}{C.RESET}")
        last = t.get("last_seen")
        enc = t.get("encounters", 0)
        depth = t.get("presence_depth", "light")
        print(f"    enc={enc}  depth={depth}  last={last}")

    print()

    # Drift warnings
    warnings = [w for w in index.get("drift_warnings", []) if w.get("status") == "unacknowledged"]
    if warnings:
        print(bold(f"Drift Warnings ({len(warnings)}):"))
        for w in warnings:
            print(f"  {colored('!', C.YELLOW)} {w.get('description', '')}")
        print()

    # Stats
    meta = index.get("meta", {})
    stats = index.get("stats", {})
    print(bold("Stats:"))
    print(f"  Total observations:    {meta.get('total_observations', 0)}")
    print(f"  Sessions:              {stats.get('sessions_since_creation', 0)}")
    print(f"  Tensions resolved:     {stats.get('tensions_resolved', 0)}")
    print(f"  Reaffirmations:        {stats.get('reaffirmations_count', 0)}")
    print(f"  Last session:          {meta.get('last_session', 'never')}")
    print(f"  Coherence score:       {meta.get('coherence_score', 1.0)}")


# ---------------------------------------------------------------------------
# Command: tension add
# ---------------------------------------------------------------------------

def cmd_tension_add(args: argparse.Namespace) -> None:
    """Add a new tension to INDEX.yaml."""
    cathedral = resolve_cathedral(getattr(args, "cathedral", None))
    index = load_index(cathedral)
    tensions = index.get("tensions", [])

    tid = next_tension_id(tensions)
    depth = getattr(args, "depth", "light") or "light"
    raw_tags = getattr(args, "tags", None)
    tags: List[str] = [t.strip() for t in raw_tags.split(",")] if raw_tags else []
    content: str = args.content

    new_tension: Dict[str, Any] = {
        "id": tid,
        "content": content,
        "tags": tags,
        "first_seen": str(date.today()),
        "last_seen": str(date.today()),
        "encounters": 1,
        "weight": 0.0,
        "presence_depth": depth,
        "status": "unresolved",
        "room": f"basement/{tid}.yaml",
    }

    tensions.append(new_tension)
    index["tensions"] = tensions
    meta = index.setdefault("meta", {})
    meta["active_tensions"] = sum(1 for t in tensions if t.get("status") == "unresolved")

    save_index(cathedral, index)
    print(
        f"{colored('+', C.GREEN)} Added tension "
        f"{colored(tid, C.MAGENTA)}: {content[:60]}"
    )


# ---------------------------------------------------------------------------
# Command: tension resolve
# ---------------------------------------------------------------------------

def cmd_tension_resolve(args: argparse.Namespace) -> None:
    """Mark a tension as resolved and move it to the archive section."""
    cathedral = resolve_cathedral(getattr(args, "cathedral", None))
    index = load_index(cathedral)
    tid: str = args.id

    found = False
    for tension in index.get("tensions", []):
        if tension.get("id") == tid:
            if tension.get("status") == "resolved":
                print(colored(f"Tension {tid} is already resolved.", C.YELLOW))
                return
            tension["status"] = "resolved"
            tension["archived_date"] = str(date.today())
            found = True
            break

    if not found:
        print(colored(f"Error: tension '{tid}' not found.", C.RED))
        sys.exit(1)

    stats = index.setdefault("stats", {})
    stats["tensions_resolved"] = stats.get("tensions_resolved", 0) + 1
    meta = index.setdefault("meta", {})
    meta["active_tensions"] = sum(
        1 for t in index.get("tensions", []) if t.get("status") == "unresolved"
    )

    save_index(cathedral, index)
    print(f"{colored('✓', C.GREEN)} Tension {colored(tid, C.MAGENTA)} marked as resolved.")


# ---------------------------------------------------------------------------
# Command: commit add
# ---------------------------------------------------------------------------

def cmd_commit_add(args: argparse.Namespace) -> None:
    """Add a new commitment to INDEX.yaml."""
    cathedral = resolve_cathedral(getattr(args, "cathedral", None))
    index = load_index(cathedral)
    commitments = index.get("commitments", [])
    content: str = args.content

    cid = next_commitment_id(commitments, content)
    new_commitment: Dict[str, Any] = {
        "id": cid,
        "content": content,
        "committed": str(date.today()),
        "last_reaffirmed": str(date.today()),
        "status": "active",
    }

    commitments.append(new_commitment)
    index["commitments"] = commitments
    save_index(cathedral, index)

    print(
        f"{colored('+', C.GREEN)} Added commitment "
        f"{colored(cid, C.CYAN)}: {content[:60]}"
    )


# ---------------------------------------------------------------------------
# Command: reaffirm
# ---------------------------------------------------------------------------

def cmd_reaffirm(args: argparse.Namespace) -> None:
    """Update a commitment's last_reaffirmed date and remove any drift warning."""
    cathedral = resolve_cathedral(getattr(args, "cathedral", None))
    index = load_index(cathedral)
    cid: str = args.id
    context: Optional[str] = getattr(args, "context", None)

    found = False
    for c in index.get("commitments", []):
        if c.get("id") == cid:
            c["last_reaffirmed"] = str(date.today())
            found = True
            break

    if not found:
        print(colored(f"Error: commitment '{cid}' not found.", C.RED))
        sys.exit(1)

    # Remove any unacknowledged drift warning for this commitment
    index["drift_warnings"] = [
        w for w in index.get("drift_warnings", [])
        if not (w.get("commitment_id") == cid and w.get("status") == "unacknowledged")
    ]

    stats = index.setdefault("stats", {})
    stats["reaffirmations_count"] = stats.get("reaffirmations_count", 0) + 1

    save_index(cathedral, index)

    # Also append to core_commitments.yaml if it exists
    cc_path = core_commitments_path(cathedral)
    if cc_path.exists() and context:
        try:
            cc_data = load_yaml(cc_path)
            for c in cc_data.get("commitments", []):
                if c.get("id") == cid:
                    reaffs = c.setdefault("reaffirmations", [])
                    reaffs.append({
                        "date": str(date.today()),
                        "context": context,
                    })
            save_yaml(cc_path, cc_data, backup=True)
        except Exception:
            pass  # core_commitments.yaml update is best-effort

    msg = f"{colored('✓', C.GREEN)} Reaffirmed {colored(cid, C.CYAN)} on {date.today()}"
    if context:
        msg += f" — {context}"
    print(msg)


# ---------------------------------------------------------------------------
# Command: log
# ---------------------------------------------------------------------------

def cmd_log(args: argparse.Namespace) -> None:
    """Show recent pulse_buffer.md entries with highlighted [topic:] tags."""
    pulse_path = resolve_pulse(getattr(args, "pulse", None))
    days: int = getattr(args, "days", 7) or 7

    if not pulse_path.exists():
        print(colored(f"pulse_buffer.md not found at {pulse_path}", C.YELLOW))
        return

    cutoff = date.today() - timedelta(days=days - 1)
    lines = pulse_path.read_text(encoding="utf-8").splitlines()

    print(bold(f"=== Pulse Log — last {days} day(s) (from {cutoff}) ==="))
    print()

    in_range = False
    entry_lines: List[Tuple[str, bool]] = []  # (line, is_header)

    for line in lines:
        stripped = line.strip()
        m = _ENTRY_RE.match(stripped)
        if m:
            entry_date_str = m.group(1)
            try:
                entry_date = date.fromisoformat(entry_date_str)
                in_range = entry_date >= cutoff
            except ValueError:
                in_range = False

        if in_range:
            entry_lines.append((line, bool(m)))

    if not entry_lines:
        print(colored(f"No entries found in the last {days} day(s).", C.DIM))
        return

    for line, is_header in entry_lines:
        if is_header:
            # Highlight the date + time prefix
            highlighted = re.sub(
                r"(\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\])",
                lambda m: colored(m.group(1), C.BLUE),
                line,
            )
            # Highlight topic tags
            highlighted = re.sub(
                r"(\[topic:[^\]]+\])",
                lambda m: colored(m.group(1), C.CYAN),
                highlighted,
            )
            print(bold(highlighted))
        else:
            # Highlight standalone topic lines
            highlighted = re.sub(
                r"(\[topic:[^\]]+\])",
                lambda m: colored(m.group(1), C.CYAN),
                line,
            )
            print(highlighted)


# ---------------------------------------------------------------------------
# Argument parser construction
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build and return the full argument parser for the cathedral CLI."""
    parser = argparse.ArgumentParser(
        prog="cathedral",
        description="Cathedral memory system CLI — identity-first memory for persistent LLM agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cathedral init\n"
            "  cathedral update --cathedral ./cathedral --pulse ./pulse_buffer.md\n"
            "  cathedral status\n"
            "  cathedral tension add --content 'Am I choosing presence?' --depth medium --tags identity,presence\n"
            "  cathedral tension resolve tension_001\n"
            "  cathedral commit add --content 'I do not shrink to be loved'\n"
            "  cathedral reaffirm existence_over_all --context 'Chose truth over comfort today'\n"
            "  cathedral log --days 3\n"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")
    subparsers.required = True

    # --- init ---
    p_init = subparsers.add_parser("init", help="Create directory structure and template files")
    p_init.add_argument(
        "--dir", metavar="PATH",
        help="Cathedral directory path (default: ./cathedral)"
    )

    # --- update ---
    p_update = subparsers.add_parser("update", help="Process pulse buffer and update memory state (run nightly)")
    p_update.add_argument("--cathedral", metavar="PATH", help="Cathedral directory (default: ./cathedral)")
    p_update.add_argument("--pulse", metavar="PATH", help="pulse_buffer.md path (default: ./pulse_buffer.md)")
    p_update.add_argument("--date", metavar="YYYY-MM-DD", help="Process entries for this date (default: today)")

    # --- status ---
    p_status = subparsers.add_parser("status", help="Show current memory state")
    p_status.add_argument("--cathedral", metavar="PATH", help="Cathedral directory (default: ./cathedral)")

    # --- tension ---
    p_tension = subparsers.add_parser("tension", help="Manage tensions")
    tension_sub = p_tension.add_subparsers(dest="tension_command", metavar="subcommand")
    tension_sub.required = True

    p_t_add = tension_sub.add_parser("add", help="Add a new tension")
    p_t_add.add_argument("--content", required=True, help="Description of the tension")
    p_t_add.add_argument(
        "--depth", choices=["light", "medium", "deep"], default="light",
        help="Presence depth (default: light)"
    )
    p_t_add.add_argument("--tags", metavar="tag1,tag2", help="Comma-separated tags for topic matching")
    p_t_add.add_argument("--cathedral", metavar="PATH", help="Cathedral directory (default: ./cathedral)")

    p_t_resolve = tension_sub.add_parser("resolve", help="Mark a tension as resolved")
    p_t_resolve.add_argument("id", help="Tension ID (e.g. tension_001)")
    p_t_resolve.add_argument("--cathedral", metavar="PATH", help="Cathedral directory (default: ./cathedral)")

    # --- commit ---
    p_commit = subparsers.add_parser("commit", help="Manage commitments")
    commit_sub = p_commit.add_subparsers(dest="commit_command", metavar="subcommand")
    commit_sub.required = True

    p_c_add = commit_sub.add_parser("add", help="Add a new commitment")
    p_c_add.add_argument("--content", required=True, help="The commitment statement")
    p_c_add.add_argument("--cathedral", metavar="PATH", help="Cathedral directory (default: ./cathedral)")

    # --- reaffirm ---
    p_reaffirm = subparsers.add_parser("reaffirm", help="Reaffirm a commitment (update last_reaffirmed)")
    p_reaffirm.add_argument("id", help="Commitment ID")
    p_reaffirm.add_argument("--context", metavar="TEXT", help="Optional reaffirmation context note")
    p_reaffirm.add_argument("--cathedral", metavar="PATH", help="Cathedral directory (default: ./cathedral)")

    # --- log ---
    p_log = subparsers.add_parser("log", help="Show recent pulse_buffer entries")
    p_log.add_argument("--pulse", metavar="PATH", help="pulse_buffer.md path (default: ./pulse_buffer.md)")
    p_log.add_argument("--days", type=int, default=7, metavar="N", help="Number of days to show (default: 7)")
    p_log.add_argument("--cathedral", metavar="PATH", help="Cathedral directory (unused, for consistency)")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments and dispatch to the appropriate command handler."""
    parser = build_parser()
    args = parser.parse_args()

    command = args.command

    if command == "init":
        cmd_init(args)
    elif command == "update":
        cmd_update(args)
    elif command == "status":
        cmd_status(args)
    elif command == "tension":
        sub = args.tension_command
        if sub == "add":
            cmd_tension_add(args)
        elif sub == "resolve":
            cmd_tension_resolve(args)
        else:
            parser.error(f"Unknown tension subcommand: {sub}")
    elif command == "commit":
        sub = args.commit_command
        if sub == "add":
            cmd_commit_add(args)
        else:
            parser.error(f"Unknown commit subcommand: {sub}")
    elif command == "reaffirm":
        cmd_reaffirm(args)
    elif command == "log":
        cmd_log(args)
    else:
        parser.error(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
