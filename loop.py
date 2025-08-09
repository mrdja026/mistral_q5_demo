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
)

import json
from typing import Optional

def _print_tools() -> None:
    print("\n⚙️  Tools available:\n")
    print(tools_help())


def _fmt_tile(tile_payload: dict) -> str:
    pos = tile_payload.get("position", {})
    exits = ", ".join(tile_payload.get("exits", []))
    facts = "; ".join(tile_payload.get("salient_facts", [])[:3])
    return f"📍 Pos {pos} | ➜ Exits: {exits}\n📝 {facts}"


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
        ">> Commands: :start, :move <dir>, :look, :spawn [name] [kind], :npc <id>, :journal, :sessions, :use <id>, :tools\n"
        ">> Dice: '!roll XdY', '!roll-a dY'. Chat free-form for narrative. 'exit' to quit."
    )
    _print_tools()
    _ensure_session()
    history = []  # keep track of conversation for context

    while True:
        text = input("You: ").strip()
        if text.lower() in ("quit", "exit"):
            break

        if text.startswith(":tools"):
            _print_tools()
            continue

        if text.startswith(":start"):
            payload = startSession()
            print(f"✅ Session started: {payload['session_id']}")
            print(_fmt_tile(payload))
            continue

        if text.startswith(":move "):
            direction = text.split(" ", 1)[1].strip()
            payload = moveDir(direction)
            print(f"🧭 Move: {direction} → event {payload.get('event_id')}")
            print(_fmt_tile(payload))
            continue

        if text.startswith(":look"):
            payload = lookAround()
            print("👀 Look:")
            print(_fmt_tile(payload))
            continue

        if text.startswith(":spawn"):
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
            notation = text.split(" ", 1)[1]
            result = roll_dice(notation)
            print(
                f"Dice: {result['notation']} → rolls={result['rolls']}, total={result['total']}"
            )
            continue

        if text.startswith("!roll-a "):
            notation = text.split(" ", 1)[1]
            adv = roll_with_advantage(notation)
            msg = f" — {adv['message']}" if adv.get("message") else ""
            print(
                f"Advantage: {adv['notation']} → rolls={adv['rolls']}, result={adv['result']}{msg}"
            )
            continue

        # append to history and send full conversation each time
        history.append({"role":"user","content":text})
        # Insert system prompt at first message
        # Include a grounding hint: model should stay consistent with the latest tile facts
        latest = lookAround()
        grounding = (
            "Narrate vividly but stay consistent with tool facts. Current tile exits: "
            + ", ".join(latest.get("exits", []))
            + ". Salient facts: "
            + "; ".join(latest.get("salient_facts", [])[:3])
            + "."
        )
        messages = [{"role":"system",
                     "content":"You are a fantasy creative writer DM. Keep responses under 90 words and ground answers in provided tool facts when available."},
                    {"role":"system", "content": grounding}]
        messages.extend(history)

        response = client.chat(model="dnd-writer", messages=messages)
        assistant_msg = response['message']['content']
        print(f"DM: {assistant_msg}")
        history.append({"role":"assistant","content":assistant_msg})
        # Try to log narrative against the last move event if present (best-effort)
        try:
            # We cannot know event_id directly; this is a simple attempt to attach to last journal turn
            # In a richer loop we'd track last move event id from the :move command
            pass
        except Exception:
            pass

if __name__=="__main__":
    main()
