# chat_with_wrapper.py

from ollama import Client
from tools.dnd_tools import roll_dice, roll_with_advantage
from tools.llm_tools_server import (
    startSession,
    moveDir,
    lookAround,
    logNarrative,
    journalSummary,
    getActiveSession,
    setActiveSession,
    listSessions,
    spawnNpc,
    getNpc,
    tools_help,
    endSession,
    resetAll,
)

import json
from typing import Optional, List


def _narrate_from_tile(client: Client, tile_payload: dict, event_id: Optional[int] = None) -> None:
    max_words = int(tile_payload.get("max_narrative_words", 500) or 500)
    pos = tile_payload.get("position", {})
    tile = tile_payload.get("tile", {})
    facts = tile_payload.get("salient_facts", [])
    exits = ", ".join(tile.get("exits", tile_payload.get("exits", [])))
    entities = ", ".join([e.get("kind", e.get("name", "")) for e in tile.get("entities", [])])
    items = ", ".join([i.get("kind", "") for i in tile.get("items", [])])
    hazards = ", ".join(tile.get("hazards", []))

    brief = [
        f"Exits: {exits}" if exits else "",
        f"Entities: {entities}" if entities else "",
        f"Items: {items}" if items else "",
        f"Hazards: {hazards}" if hazards else "",
    ]
    brief = "; ".join([b for b in brief if b])

    # Build mandatory points of interest the narrative MUST include
    points_of_interest = []
    for f in facts or []:
        points_of_interest.append(f)
    if items:
        points_of_interest.append(f"Notable items present: {items}")
    if entities:
        points_of_interest.append(f"Entities present: {entities}")
    if hazards:
        points_of_interest.append(f"Hazards: {hazards}")

    messages = [
        {
            "role": "system",
            "content": (
                f"You are a Dungeon Master. In up to {max_words} words, vividly describe what the player perceives at position {pos}. "
                "The narrative MUST include all Points of Interest listed by the user as explicit details (weave them naturally but do not omit). "
                "Do not invent exits, items, entities, or hazards beyond what is provided."
            ),
        },
        {
            "role": "user",
            "content": (
                "Environment summary: " + (brief if brief else "(none)") +
                "\nPoints of Interest (must include all):\n - " + "\n - ".join(points_of_interest or [])
            ),
        },
    ]

    predict_tokens = int(max(256, min(3072, max_words * 2)))
    resp = client.chat(
        model="dnd-writer",
        messages=messages,
        options={
            "num_predict": predict_tokens,
            "temperature": 0.8,
        },
    )
    text = resp["message"]["content"]
    print(f"DM: {text}")
    if event_id is not None:
        try:
            logNarrative(text=text, eventId=event_id)
        except Exception:
            pass

def _print_tools() -> None:
    print("\n⚙️  Tools available:\n")
    print(tools_help())


def _fmt_tile(tile_payload: dict) -> str:
    pos = tile_payload.get("position", {})
    exits = ", ".join(tile_payload.get("exits", []))
    facts = "; ".join(tile_payload.get("salient_facts", [])[:3])
    heading = tile_payload.get("heading", "?")
    header = f"🏰 D&D Journey | {pos} facing {heading}"
    status = f"📍 Pos {pos} | ➜ Exits: {exits}"
    facts_ln = f"📝 {facts}" if facts else "📝"
    return f"{header}\n{status}\n{facts_ln}"


def _list_suggestions(tile_payload: Optional[dict]) -> List[str]:
    if not tile_payload:
        return [":start", ":look", ":move north", "!roll d20", ":help"]
    exits = tile_payload.get("exits", [])
    tile = tile_payload.get("tile", {})
    items = [i.get("kind") for i in tile.get("items", [])]
    sugg: List[str] = []
    # movement
    for d in exits[:3]:
        sugg.append(f":move {d}")
    # quick look
    sugg.append(":look")
    # items
    if items:
        sugg.append(f":take {items[0]}")
    # dice
    sugg.append("!roll d20")
    # encourage spawn usage explicitly via colon syntax
    sugg.append(":spawn [name] goblin")
    return sugg[:6]


def _parse_legacy_call_args(text: str) -> List[str]:
    """Parse simple function-style arguments like "('Gruk','goblin')" into ["Gruk","goblin"].

    This is a forgiving parser for our legacy inputs; it does not handle nested
    or escaped quotes and is intentionally simple for CLI ergonomics.
    """
    if "(" not in text or ")" not in text:
        return []
    inner = text[text.find("(") + 1 : text.rfind(")")]
    parts = [p.strip() for p in inner.split(",") if p.strip()]
    cleaned: List[str] = []
    for p in parts:
        if (p.startswith("\"") and p.endswith("\"")) or (p.startswith("'") and p.endswith("'")):
            cleaned.append(p[1:-1])
        else:
            cleaned.append(p)
    return cleaned


def _ensure_session() -> dict:
    active = getActiveSession()
    if not active.get("session_id"):
        payload = startSession()
        print(f"✅ Session started: {payload['session_id']}")
        print(_fmt_tile(payload))
        return payload
    return lookAround()


def main():
    client = Client()

    # Ensure model is ready
    try:
        client.create("dnd-writer")
    except:
        pass

    print(
        ">> Commands: :start, :end, :reset, :move <dir>, :look, :spawn [name] [kind], :npc <id>, :journal, :sessions, :use <id>, :tools, :help, :hints on|off, :suggest\n"
        ">> Prefer colon commands. Legacy function calls like spawnNpc('Gruk','goblin') are supported but normalized.\n"
        ">> Aliases: 'go <dir>', 'move <dir>', 'look' (same as :look).\n"
        ">> Dice: '!roll XdY', '!roll-a dY'. Chat free-form for narrative. 'exit' to quit."
    )
    _print_tools()
    _ensure_session()
    history = []  # keep track of conversation for context
    last_tile: Optional[dict] = None
    hints_enabled: bool = True

    while True:
        text = input("You: ").strip()
        if text.lower() in ("quit", "exit"):
            break

        if text.startswith(":tools"):
            _print_tools()
            continue

        if text.startswith(":help"):
            print(
                "\nCommands:\n"
                ":start | :end | :reset | :move <north|south|east|west|up|down|forward|back|left|right> | :look | :spawn [name] [kind] | :npc <id> | :journal | :sessions | :use <id> | :tools | :help | :hints on|off | :suggest\n"
                "Aliases: 'go <dir>', 'move <dir>', 'look'.\n"
                "Examples: go west | :move forward | :spawn Gruk goblin | !roll d20\n"
            )
            continue

        if text.startswith(":hints"):
            arg = text.split(" ", 1)[1].strip().lower() if " " in text else ""
            if arg in {"on", "off"}:
                hints_enabled = arg == "on"
                print(f"💡 Hints {'enabled' if hints_enabled else 'disabled'}")
            else:
                print(f"💡 Hints are {'on' if hints_enabled else 'off'} — use :hints on|off")
            continue

        if text.startswith(":suggest"):
            suggestions = _list_suggestions(last_tile)
            if suggestions:
                print("👉 Try:", " | ".join(suggestions))
            continue

        # --- Legacy function-style inputs; normalize to colon commands ---
        lower = text.lower()
        if lower.startswith("spawnnpc("):
            args = _parse_legacy_call_args(text)
            name = args[0] if len(args) > 0 else None
            kind = args[1] if len(args) > 1 else None
            res = spawnNpc(name=name, kind=kind)
            npc = res["npc"]
            print(f"⚔️  Spawned {npc['name']} (id={npc['id']}, kind={npc['kind']}, AC={npc['armor_class']})")
            print(res["message"])
            if hints_enabled and last_tile:
                print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
            continue
        if lower.startswith("movedir("):
            args = _parse_legacy_call_args(text)
            direction = args[0] if args else ""
            if direction:
                payload = moveDir(direction)
                print(f"🧭 Move: {direction} → event {payload.get('event_id')}")
                print(_fmt_tile(payload))
                last_tile = payload
                _narrate_from_tile(client, payload, event_id=payload.get("event_id"))
                if hints_enabled:
                    print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
                continue
        if lower.startswith("lookaround("):
            payload = lookAround()
            print("👀 Look:")
            print(_fmt_tile(payload))
            last_tile = payload
            _narrate_from_tile(client, payload)
            if hints_enabled:
                print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
            continue
        if lower.startswith("startsession(") or lower == "startsession":
            payload = startSession()
            print(f"✅ Session started: {payload['session_id']}")
            print(_fmt_tile(payload))
            last_tile = payload
            continue

        if text.startswith(":start"):
            payload = startSession()
            print(f"✅ Session started: {payload['session_id']}")
            print(_fmt_tile(payload))
            last_tile = payload
            continue

        if text.startswith(":end"):
            active = getActiveSession()
            sid = active.get("session_id")
            if not sid:
                print("ℹ️  No active session")
            else:
                res = endSession(sid)
                print(f"🛑 Ended session: {res.get('ended')}")
            last_tile = None
            continue

        if text.startswith(":reset"):
            resetAll()
            print("🧹 Reset all sessions")
            last_tile = None
            continue

        if text.startswith(":move "):
            direction = text.split(" ", 1)[1].strip()
            payload = moveDir(direction)
            print(f"🧭 Move: {direction} → event {payload.get('event_id')}")
            print(_fmt_tile(payload))
            last_tile = payload
            _narrate_from_tile(client, payload, event_id=payload.get("event_id"))
            if hints_enabled:
                print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
            continue

        if text.startswith(":look"):
            payload = lookAround()
            print("👀 Look:")
            print(_fmt_tile(payload))
            last_tile = payload
            _narrate_from_tile(client, payload)
            if hints_enabled:
                print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
            continue

        if text.startswith(":spawn") or text.lower().startswith("spawn "):
            parts = text.split()
            name: Optional[str] = parts[1] if len(parts) > 1 else None
            kind: Optional[str] = parts[2] if len(parts) > 2 else None
            res = spawnNpc(name=name, kind=kind)
            npc = res["npc"]
            print(f"⚔️  Spawned {npc['name']} (id={npc['id']}, kind={npc['kind']}, AC={npc['armor_class']})")
            print(res["message"])
            continue

        if text.startswith(":npc "):
            npc_id = text.split(" ", 1)[1].strip()
            try:
                res = getNpc(npc_id)
                print("📇 NPC:")
                print(json.dumps(res["npc"], indent=2))
            except Exception as e:
                print(f"❌ {e}")
            continue

        if text.startswith(":journal"):
            res = journalSummary()
            print("📜 Journal:")
            for ln in res.get("summary", []):
                print(f" - {ln}")
            continue

        if text.startswith(":sessions"):
            res = listSessions()
            print("🗂️  Sessions:")
            for s in res.get("sessions", []):
                mark = "*" if s.get("active") else " "
                print(f" {mark} {s['session_id']} @ {s['position']} turn={s['turn']} heading={s['heading']}")
            continue

        if text.startswith(":use "):
            sid = text.split(" ", 1)[1].strip()
            try:
                setActiveSession(sid)
                print(f"✅ Active session set: {sid}")
            except Exception as e:
                print(f"❌ {e}")
            continue

        if text.startswith("!roll "):
            notation = text.split(" ", 1)[1].strip()
            try:
                result = roll_dice(notation)
                print(
                    f"Dice: {result['notation']} → rolls={result['rolls']}, total={result['total']}"
                )
                if hints_enabled and last_tile:
                    print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
            except Exception as e:
                print(f"❌ {e}. Try '!roll 1d20' or '!roll 2d6'.")
            continue

        if text.startswith("!roll-a "):
            notation = text.split(" ", 1)[1].strip()
            try:
                adv = roll_with_advantage(notation)
                msg = f" — {adv['message']}" if adv.get("message") else ""
                print(
                    f"Advantage: {adv['notation']} → rolls={adv['rolls']}, result={adv['result']}{msg}"
                )
                if hints_enabled and last_tile:
                    print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
            except Exception as e:
                print(f"❌ {e}. Try '!roll-a d20'.")
            continue

        # Natural language command aliases (no colon)
        if text.lower().startswith("go ") or text.lower().startswith("move "):
            direction = text.split(" ", 1)[1].strip()
            payload = moveDir(direction)
            print(f"🧭 Move: {direction} → event {payload.get('event_id')}")
            print(_fmt_tile(payload))
            last_tile = payload
            _narrate_from_tile(client, payload, event_id=payload.get("event_id"))
            if hints_enabled:
                print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
            continue

        if text.lower() in {"look", "look around"}:
            payload = lookAround()
            print("👀 Look:")
            print(_fmt_tile(payload))
            last_tile = payload
            _narrate_from_tile(client, payload)
            if hints_enabled:
                print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
            continue

        # append to history and send full conversation each time
        history.append({"role":"user","content":text})
        # Insert system prompts; ground only if we have a cached tile from explicit tool calls
        grounding = ""
        if last_tile:
            grounding = (
                "Narrate vividly but stay consistent with tool facts. Current tile exits: "
                + ", ".join(last_tile.get("exits", []))
                + ". Salient facts: "
                + "; ".join(last_tile.get("salient_facts", [])[:3])
                + "."
            )
        max_words = 500
        if last_tile and isinstance(last_tile.get("max_narrative_words"), int):
            max_words = int(last_tile["max_narrative_words"]) or 500
        messages = [{"role":"system",
                     "content":f"You are a fantasy creative writer DM. Keep responses under {max_words} words and ground answers in provided tool facts when available."}]
        if grounding:
            messages.append({"role":"system", "content": grounding})
        messages.extend(history)

        # Allow longer completions by raising token limit
        predict_tokens = int((max_words if 'max_words' in locals() else 500) * 1.6)
        response = client.chat(
            model="dnd-writer",
            messages=messages,
            options={
                "num_predict": max(256, min(2048, predict_tokens)),
                "temperature": 0.8,
            },
        )
        assistant_msg = response['message']['content']
        print(f"DM: {assistant_msg}")
        history.append({"role":"assistant","content":assistant_msg})
        if hints_enabled and last_tile:
            print("👉 Try:", " | ".join(_list_suggestions(last_tile)))
        # Try to log narrative against the last move event if present (best-effort)
        try:
            # We cannot know event_id directly; this is a simple attempt to attach to last journal turn
            # In a richer loop we'd track last move event id from the :move command
            pass
        except Exception:
            pass

if __name__=="__main__":
    main()
