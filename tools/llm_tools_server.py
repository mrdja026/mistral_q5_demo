#!/usr/bin/env python3
"""
MCP stdio server for Cursor — exposes typed tools the model can call in chat/file loop.
Run with: python -m tools.llm_tools_server
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import logging
import os
import platform
import sys
import threading
import hashlib
import uuid
import time
import random

from mcp.server.fastmcp import FastMCP
from .dnd_tools import roll_dice, roll_with_advantage

mcp = FastMCP("llm-tools")  # server name as it will appear in Cursor


def _configure_logging() -> logging.Logger:
    """Configure logging to stderr so we don't interfere with stdio JSON-RPC.

    Set MCP_VERBOSE=1 for DEBUG verbosity.
    """
    level = logging.DEBUG if str(os.getenv("MCP_VERBOSE", "")).lower() in {"1", "true", "yes"} else logging.INFO
    logger = logging.getLogger("llm-tools")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    logger.debug("Logger initialized at level %s", logging.getLevelName(logger.level))
    return logger


logger = _configure_logging()
logger.info("Initializing llm-tools MCP server module")

# Declared tool names and aliases for discovery/help output
_TOOL_NAMES = [
    "summarize_file",
    "function_skeleton",
    "roll_dice_tool",
    "roll_with_advantage_tool",
    "start_session",
    "move",
    "look",
    "log_narrative",
    "journal",
    "get_active_session",
    "set_active_session",
    "list_sessions",
    "spawn_npc",
    "get_npc",
    "health",
    "ping",
    "echo",
]
_TOOL_ALIASES = [
    "startSession",
    "moveDir",
    "lookAround",
    "logNarrative",
    "journalSummary",
    "getActiveSession",
    "setActiveSession",
    "listSessions",
    "spawnNpc",
    "getNpc",
    "tools_help",
]

# ============================
# In-memory world state (authoritative)
# ============================

# Session store keyed by session_id
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_ACTIVE_SESSION_ID: Optional[str] = None

# Per-session locks to serialize state changes
_SESSION_LOCKS: Dict[str, threading.Lock] = {}

# Monotonic event id per server instance
_NEXT_EVENT_ID: int = 1

# Directions and movement deltas
_BASE_DIRECTIONS = {"north", "south", "east", "west", "up", "down"}
_DELTAS: Dict[str, Tuple[int, int, int]] = {
    "north": (0, 1, 0),
    "south": (0, -1, 0),
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 0, 1),
    "down": (0, 0, -1),
}

_DIR_ALIASES: Dict[str, str] = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "u": "up",
    "d": "down",
}

_TURN_JOURNAL_ROLLUP_INTERVAL = 8  # summarize periodically
_JOURNAL_MAX_ENTRIES = 32


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _coord_key(x: int, y: int, z: int) -> str:
    return f"{x},{y},{z}"


def _normalize_direction(direction: str, heading: str) -> Tuple[str, str]:
    """Normalize direction aliases and relative forms.

    Returns a tuple of (absolute_direction, new_heading).
    Relative forms: forward/back/left/right adjust using heading.
    """
    s = direction.strip().lower()
    # direct aliases
    if s in _DIR_ALIASES:
        s = _DIR_ALIASES[s]

    if s in _BASE_DIRECTIONS:
        # heading unchanged for cardinal/up/down moves
        if s in {"north", "south", "east", "west"}:
            return s, s  # face the way you moved
        return s, heading

    # relative forms
    compass = ["north", "east", "south", "west"]
    try:
        idx = compass.index(heading) if heading in compass else 0
    except ValueError:
        idx = 0
    if s in {"forward", "ahead"}:
        return compass[idx], compass[idx]
    if s in {"back", "backward", "reverse"}:
        return compass[(idx + 2) % 4], compass[(idx + 2) % 4]
    if s in {"left"}:
        return compass[(idx - 1) % 4], compass[(idx - 1) % 4]
    if s in {"right"}:
        return compass[(idx + 1) % 4], compass[(idx + 1) % 4]

    raise ValueError(
        "Unknown direction. Use north/south/east/west/up/down or forward/back/left/right."
    )


def _seed_for_tile(session_id: str, x: int, y: int, z: int) -> int:
    h = hashlib.sha256(f"{session_id}:{x},{y},{z}".encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def _generate_tile(session_id: str, x: int, y: int, z: int) -> Dict[str, Any]:
    seed = _seed_for_tile(session_id, x, y, z)
    rng = random.Random(seed)
    biomes = [
        "ruined_keep",
        "crypt",
        "cavern",
        "armory",
        "library",
        "underground_river",
    ]
    biome = rng.choice(biomes)
    lighting = rng.choice(["dark", "dim", "torchlit", "glimmering"])

    entities = []
    if rng.random() < 0.5:
        kind = rng.choice(["goblin", "skeleton", "bat", "kobold", "slime"]) 
        disposition = rng.choice(["hostile", "wary", "indifferent"]) 
        entities.append({
            "id": f"e_{kind}_{rng.randint(10, 999)}",
            "kind": kind,
            "disposition": disposition,
        })

    items = []
    if rng.random() < 0.5:
        kind = rng.choice(["scroll", "rusty_blade", "torch", "amulet", "potion"])
        items.append({
            "id": f"it_{kind}_{rng.randint(10, 999)}",
            "kind": kind,
        })

    exits = [d for d in ["north", "east", "south", "west"] if rng.random() < 0.7]
    if not exits:
        exits = [rng.choice(["north", "east", "south", "west"])]

    hazards = []
    if rng.random() < 0.3:
        hazards.append(rng.choice(["loose_stones", "slick_moss", "unstable_beam"]))

    salient_facts = []
    salient_facts.append({
        "text": f"{lighting.replace('_', ' ').title()} {biome.replace('_', ' ')}",
        "kind": "atmosphere",
    })
    if entities:
        salient_facts.append({
            "text": f"{entities[0]['kind'].title()} is {entities[0]['disposition']}",
            "kind": "entity",
        })
    if items:
        salient_facts.append({
            "text": f"Notable item: {items[0]['kind'].replace('_',' ')}",
            "kind": "item",
        })
    if hazards:
        salient_facts.append({
            "text": f"Hazard: {hazards[0].replace('_',' ')}",
            "kind": "hazard",
        })

    return {
        "seed": seed,
        "tile": {
            "biome": biome,
            "lighting": lighting,
            "entities": entities,
            "items": items,
            "exits": exits,
            "hazards": hazards,
        },
        "salient_facts": [sf["text"] for sf in salient_facts],
    }


def _ensure_tile(session: Dict[str, Any], x: int, y: int, z: int) -> Dict[str, Any]:
    key = _coord_key(x, y, z)
    tile = session["tiles"].get(key)
    if tile is None:
        tile = _generate_tile(session["session_id"], x, y, z)
        session["tiles"][key] = tile
    return tile


def _append_event(session: Dict[str, Any], event_type: str, payload: Dict[str, Any]) -> int:
    global _NEXT_EVENT_ID
    eid = _NEXT_EVENT_ID
    _NEXT_EVENT_ID += 1
    session["events"].append({
        "event_id": eid,
        "type": event_type,
        "ts": _now_iso(),
        "payload": payload,
    })
    # Bound events list growth (simple cap)
    if len(session["events"]) > 5000:
        session["events"] = session["events"][-4000:]
    return eid


def _rollup_journal(session: Dict[str, Any]) -> None:
    # Keep a rolling set of recent salient facts
    journal = session.setdefault("journal", [])
    pos = session["position"]
    tile = _ensure_tile(session, pos["x"], pos["y"], pos["z"])
    summary = \
        f"Turn {session['turn']}: at {_coord_key(pos['x'], pos['y'], pos['z'])} — " + \
        ", ".join(tile.get("salient_facts", [])[:3])
    journal.append(summary)
    if len(journal) > _JOURNAL_MAX_ENTRIES:
        del journal[: max(0, len(journal) - _JOURNAL_MAX_ENTRIES)]


def _with_session_lock(session_id: str):
    lock = _SESSION_LOCKS.setdefault(session_id, threading.Lock())
    return lock


def _new_session(theme: Optional[str], tone: Optional[str], max_words: int) -> Dict[str, Any]:
    session_id = f"s_{uuid.uuid4().hex[:12]}"
    state: Dict[str, Any] = {
        "session_id": session_id,
        "position": {"x": 0, "y": 0, "z": 0},
        "heading": "north",
        "turn": 0,
        "tiles": {},
        "events": [],
        "journal": [],
        "npcs": {},  # npc_id -> npc record
        "settings": {
            "theme": theme or "dungeon",
            "tone": tone or "moody",
            "max_narrative_words": int(max_words) if max_words else 80,
        },
    }
    # Ensure starting tile exists
    _ensure_tile(state, 0, 0, 0)
    # Register session
    _SESSIONS[session_id] = state
    _SESSION_LOCKS.setdefault(session_id, threading.Lock())
    # Event
    _append_event(state, "session_start", {"position": state["position"]})
    return state


def _public_tile_payload(session: Dict[str, Any]) -> Dict[str, Any]:
    pos = session["position"]
    tile = _ensure_tile(session, pos["x"], pos["y"], pos["z"])
    return {
        "turn": session["turn"],
        "position": pos,
        "tile": tile["tile"],
        "salient_facts": tile["salient_facts"],
        "exits": tile["tile"]["exits"],
        "heading": session["heading"],
        "session_id": session["session_id"],
        "max_narrative_words": session["settings"]["max_narrative_words"],
    }


def _slugify_name(name: str) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    return "_".join(filter(None, base.split("_"))) or "foe"


@mcp.tool()
def summarize_file(path: str, max_lines: int = 200) -> str:
    """Return a short summary of a text file (first N non-empty lines)."""
    logger.debug("summarize_file(path=%s, max_lines=%s)", path, max_lines)
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No such file: {p}")
    lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    head = lines[: max(0, int(max_lines))]
    return f"{p} — {len(lines)} total non-empty lines\n" + "\n".join(head)

@mcp.tool()
def function_skeleton(name: str, docstring: Optional[str] = None) -> str:
    """Generate a clean, typed Python function skeleton."""
    logger.debug("function_skeleton(name=%s, has_doc=%s)", name, bool(docstring))
    safe = "".join(ch for ch in name if ch.isidentifier() or ch == "_")
    ds = f'"""{docstring}"""' if docstring else '"""TODO: document me."""'
    return (
        f"def {safe}() -> None:\n"
        f"    {ds}\n"
        f"    # TODO: implement\n"
        f"    pass\n"
    )

@mcp.tool()
def roll_dice_tool(notation: str) -> dict:
    """Roll dice using NdM notation (e.g., '2d20')."""
    logger.debug("roll_dice_tool(notation=%s)", notation)
    return roll_dice(notation)

@mcp.tool()
def roll_with_advantage_tool(notation: str) -> dict:
    """Roll a single die with advantage using dM notation (e.g., 'd20').

    Rolls twice and takes the higher result. For d20, includes critical messages.
    """
    logger.debug("roll_with_advantage_tool(notation=%s)", notation)
    return roll_with_advantage(notation)


@mcp.tool()
def start_session(theme: Optional[str] = None, tone: Optional[str] = None, max_narrative_words: int = 80) -> Dict[str, Any]:
    """Create a new in-memory session and return initial tile info."""
    state = _new_session(theme, tone, max_narrative_words)
    global _ACTIVE_SESSION_ID
    _ACTIVE_SESSION_ID = state["session_id"]
    logger.info("start_session(session_id=%s, theme=%s, tone=%s, max_words=%s)", state["session_id"], theme, tone, max_narrative_words)
    return _public_tile_payload(state)


@mcp.tool()
def move(direction: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Move in a direction (north/south/east/west/up/down or forward/back/left/right). Returns tile info and an event_id.

    If session_id is omitted, uses the current active session.
    """
    sid = session_id or _ACTIVE_SESSION_ID
    if not sid or sid not in _SESSIONS:
        raise ValueError("No active session. Call start_session() or pass session_id explicitly.")
    logger.info("move(session_id=%s, direction=%s)", sid, direction)
    lock = _with_session_lock(sid)
    with lock:
        session = _SESSIONS[sid]
        heading_before = session["heading"]
        abs_dir, new_heading = _normalize_direction(direction, heading_before)
        dx, dy, dz = _DELTAS.get(abs_dir, (0, 0, 0))
        from_pos = dict(session["position"])  # copy
        session["position"] = {
            "x": from_pos["x"] + dx,
            "y": from_pos["y"] + dy,
            "z": from_pos["z"] + dz,
        }
        session["heading"] = new_heading
        session["turn"] += 1
        pos = session["position"]
        _ensure_tile(session, pos["x"], pos["y"], pos["z"])
        event_id = _append_event(
            session,
            "move",
            {"from": from_pos, "to": session["position"], "dir": abs_dir, "heading": new_heading},
        )
        if session["turn"] % _TURN_JOURNAL_ROLLUP_INTERVAL == 0:
            _rollup_journal(session)
        payload = _public_tile_payload(session)
        payload["event_id"] = event_id
        return payload


@mcp.tool()
def look(session_id: Optional[str] = None) -> Dict[str, Any]:
    """Return current tile info for the session without moving. Uses active session if none provided."""
    sid = session_id or _ACTIVE_SESSION_ID
    if not sid or sid not in _SESSIONS:
        raise ValueError("No active session. Call start_session() or pass session_id explicitly.")
    logger.info("look(session_id=%s)", sid)
    lock = _with_session_lock(sid)
    with lock:
        session = _SESSIONS[sid]
        return _public_tile_payload(session)


@mcp.tool()
def log_narrative(text: str, event_id: int, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Record the model's narrative for a prior event (e.g., move). Uses active session if none provided."""
    sid = session_id or _ACTIVE_SESSION_ID
    if not sid or sid not in _SESSIONS:
        raise ValueError("No active session. Call start_session() or pass session_id explicitly.")
    if not isinstance(event_id, int) or event_id <= 0:
        raise ValueError("event_id must be a positive integer")
    logger.info("log_narrative(session_id=%s, event_id=%s, text_len=%s)", sid, event_id, len(text or ""))
    lock = _with_session_lock(sid)
    with lock:
        session = _SESSIONS[sid]
        eid = _append_event(session, "narrative", {"event_id": event_id, "text": text})
        # Append a very short journal line based on narrative head
        snippet = (text or "").strip().splitlines()[0][:120]
        if snippet:
            session.setdefault("journal", []).append(f"Turn {session['turn']}: {snippet}")
            if len(session["journal"]) > _JOURNAL_MAX_ENTRIES:
                del session["journal"][: max(0, len(session["journal"]) - _JOURNAL_MAX_ENTRIES)]
        return {"ok": True, "logged_event_id": eid}


@mcp.tool()
def journal(session_id: Optional[str] = None) -> Dict[str, Any]:
    """Return a concise rolling summary of the session for context refresh. Uses active session if none provided."""
    sid = session_id or _ACTIVE_SESSION_ID
    if not sid or sid not in _SESSIONS:
        raise ValueError("No active session. Call start_session() or pass session_id explicitly.")
    logger.info("journal(session_id=%s)", sid)
    lock = _with_session_lock(sid)
    with lock:
        session = _SESSIONS[sid]
        lines = session.get("journal", [])[-_JOURNAL_MAX_ENTRIES :]
        return {"turn": session["turn"], "summary": lines}


@mcp.tool()
def spawn_npc(name: Optional[str] = None, kind: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Spawn an enemy NPC at the current tile. Returns npc details and a short message.

    - Armor class is random between 10 and 15 inclusive.
    - If name is omitted, a name is generated from kind and a short id.
    - Stored in session memory and included in tile entities next visit.
    """
    sid = session_id or _ACTIVE_SESSION_ID
    if not sid or sid not in _SESSIONS:
        raise ValueError("No active session. Call start_session() or pass session_id explicitly.")
    logger.info("spawn_npc(session_id=%s, name=%s, kind=%s)", sid, name, kind)
    lock = _with_session_lock(sid)
    with lock:
        session = _SESSIONS[sid]
        pos = session["position"]
        tile = _ensure_tile(session, pos["x"], pos["y"], pos["z"])
        rng = random.Random(_seed_for_tile(sid, pos["x"], pos["y"], pos["z"]) ^ int(time.time()))
        k = (kind or rng.choice(["goblin", "skeleton", "kobold", "bandit", "slime"]))
        nm = name or f"{k.title()} {_slugify_name(uuid.uuid4().hex[:4])}"
        armor_class = rng.randint(10, 15)
        npc_id = f"npc_{_slugify_name(nm)}_{uuid.uuid4().hex[:6]}"
        npc = {
            "id": npc_id,
            "name": nm,
            "kind": k,
            "armor_class": armor_class,
            "position": dict(pos),
            "disposition": "hostile",
        }
        session["npcs"][npc_id] = npc
        # Also reflect presence in current tile's entities list non-destructively
        ent = {"id": npc_id, "kind": k, "disposition": "hostile", "name": nm}
        # Avoid duplicate entity entries with same id
        entities = [e for e in tile["tile"].get("entities", []) if e.get("id") != npc_id]
        entities.append(ent)
        tile["tile"]["entities"] = entities

        event_id = _append_event(session, "spawn_npc", {"npc": npc})
        msg = f"{nm} stands before you, watching your every move. Armor Class: {armor_class}."
        logger.info("spawn_npc -> npc_id=%s, ac=%s, at=%s", npc_id, armor_class, _coord_key(pos["x"], pos["y"], pos["z"]))
        return {"npc": npc, "message": msg, "event_id": event_id}


@mcp.tool()
def get_npc(npc_id: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch an NPC by id from session memory."""
    sid = session_id or _ACTIVE_SESSION_ID
    if not sid or sid not in _SESSIONS:
        raise ValueError("No active session. Call start_session() or pass session_id explicitly.")
    logger.info("get_npc(session_id=%s, npc_id=%s)", sid, npc_id)
    lock = _with_session_lock(sid)
    with lock:
        session = _SESSIONS[sid]
        npc = session["npcs"].get(npc_id)
        if not npc:
            raise ValueError("Unknown npc_id")
        return {"npc": npc}


@mcp.tool()
def get_active_session() -> Dict[str, Any]:
    """Return the current active session_id and a brief status."""
    sid = _ACTIVE_SESSION_ID
    if not sid or sid not in _SESSIONS:
        return {"session_id": None, "status": "no_active_session"}
    s = _SESSIONS[sid]
    logger.info("get_active_session -> %s @ %s", sid, s["position"])
    return {"session_id": sid, "turn": s["turn"], "position": s["position"], "heading": s["heading"]}


@mcp.tool()
def set_active_session(session_id: str) -> Dict[str, Any]:
    """Set the active session_id for subsequent calls that omit session_id."""
    if session_id not in _SESSIONS:
        raise ValueError("Unknown session_id")
    global _ACTIVE_SESSION_ID
    _ACTIVE_SESSION_ID = session_id
    s = _SESSIONS[session_id]
    logger.info("set_active_session -> %s", session_id)
    return {"session_id": session_id, "turn": s["turn"], "position": s["position"], "heading": s["heading"]}


@mcp.tool()
def list_sessions() -> Dict[str, Any]:
    """List all session ids with brief statuses."""
    data = []
    for sid, s in _SESSIONS.items():
        data.append({
            "session_id": sid,
            "turn": s["turn"],
            "position": s["position"],
            "heading": s["heading"],
            "active": sid == _ACTIVE_SESSION_ID,
        })
    logger.info("list_sessions -> %s sessions (active=%s)", len(data), _ACTIVE_SESSION_ID)
    return {"sessions": data}


@mcp.tool()
def tools_help() -> str:
    """Human-friendly list of available tools and aliases with examples."""
    lines = [
        "Available tools:",
        "- start_session(theme?, tone?, max_narrative_words?) → {session_id, position, exits}",
        "- move(direction, session_id?) → {position, exits, event_id}",
        "- look(session_id?) → {position, exits}",
        "- log_narrative(text, event_id, session_id?) → {ok}",
        "- journal(session_id?) → {turn, summary[]}",
        "- spawn_npc(name?, kind?, session_id?) → {npc, message}",
        "- get_npc(npc_id, session_id?) → {npc}",
        "- get_active_session() / set_active_session(id) / list_sessions()",
        "- roll_dice_tool('2d20'), roll_with_advantage_tool('d20')",
        "Aliases:",
        "- startSession, moveDir, lookAround, logNarrative, journalSummary, getActiveSession, setActiveSession, listSessions, spawnNpc, getNpc",
        "Examples:",
        "- startSession()",
        "- moveDir('north')",
        "- lookAround()",
        "- spawnNpc('Gruk','goblin')",
        "- logNarrative('Your boots crunch mortar…', 42)",
    ]
    return "\n".join(lines)


# ---------- CamelCase alias tools (for nicer UX) ----------

@mcp.tool()
def startSession(theme: Optional[str] = None, tone: Optional[str] = None, maxNarrativeWords: int = 80) -> Dict[str, Any]:
    return start_session(theme=theme, tone=tone, max_narrative_words=maxNarrativeWords)


@mcp.tool()
def moveDir(direction: str, sessionId: Optional[str] = None) -> Dict[str, Any]:
    return move(direction=direction, session_id=sessionId)


@mcp.tool()
def lookAround(sessionId: Optional[str] = None) -> Dict[str, Any]:
    return look(session_id=sessionId)


@mcp.tool()
def logNarrative(text: str, eventId: int, sessionId: Optional[str] = None) -> Dict[str, Any]:
    return log_narrative(text=text, event_id=eventId, session_id=sessionId)


@mcp.tool()
def journalSummary(sessionId: Optional[str] = None) -> Dict[str, Any]:
    return journal(session_id=sessionId)


@mcp.tool()
def getActiveSession() -> Dict[str, Any]:
    return get_active_session()


@mcp.tool()
def setActiveSession(sessionId: str) -> Dict[str, Any]:
    return set_active_session(session_id=sessionId)


@mcp.tool()
def listSessions() -> Dict[str, Any]:
    return list_sessions()


@mcp.tool()
def spawnNpc(name: Optional[str] = None, kind: Optional[str] = None, sessionId: Optional[str] = None) -> Dict[str, Any]:
    return spawn_npc(name=name, kind=kind, session_id=sessionId)


@mcp.tool()
def getNpc(npcId: str, sessionId: Optional[str] = None) -> Dict[str, Any]:
    return get_npc(npc_id=npcId, session_id=sessionId)


@mcp.tool()
def health() -> dict:
    """Return a small status payload to confirm the server is responsive."""
    info = {
        "status": "ok",
        "server": "llm-tools",
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "tools": _TOOL_NAMES + _TOOL_ALIASES + ["tools_help"],
    }
    logger.debug("health() -> %s", info)
    return info


@mcp.tool()
def ping() -> str:
    """Simple liveness check. Returns 'pong'."""
    logger.debug("ping()")
    return "pong"


@mcp.tool()
def echo(text: str) -> str:
    """Echo the provided text. Useful to verify round-trip plumbing."""
    logger.debug("echo(text_len=%s)", len(text))
    return text

if __name__ == "__main__":
    # FastMCP handles the stdio transport + JSON-RPC handshake for you.
    logger.info(
        "Starting llm-tools MCP stdio server (PID %s, Python %s)", os.getpid(), sys.version.split()[0]
    )
    logger.info("Tools available: %s", ", ".join(_TOOL_NAMES))
    logger.info("Aliases available: %s", ", ".join(_TOOL_ALIASES + ["tools_help"]))
    mcp.run()
