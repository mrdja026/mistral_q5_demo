from __future__ import annotations

import json
import os
import time
import threading
from typing import Optional, List

from textual.app import App, ComposeResult
import re
import textwrap
from textual.widgets import Header, Footer, Input, Static

# Compat: use TextLog if available, fallback to RichLog or Log
try:  # Textual >= version providing TextLog
    from textual.widgets import TextLog as TranscriptWidget  # type: ignore
    _TRANSCRIPT_KW = {"highlight": True, "markup": True, "wrap": True}
    _TRANSCRIPT_SUPPORTS_MARKUP = True
except Exception:
    try:  # Older Textual with RichLog
        from textual.widgets import RichLog as TranscriptWidget  # type: ignore
        _TRANSCRIPT_KW = {"highlight": True, "markup": True, "wrap": True}
        _TRANSCRIPT_SUPPORTS_MARKUP = True
    except Exception:  # Fallback to basic Log
        from textual.widgets import Log as TranscriptWidget  # type: ignore
        _TRANSCRIPT_KW = {"highlight": True}
        _TRANSCRIPT_SUPPORTS_MARKUP = False
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive

from .client import GameClient
from .commands import CommandRouter, CommandSpec


class Actions(Static):
    pass


class Context(Static):
    pass


class GameTUI(App):
    CSS = """
    Screen { layout: vertical; }
    #body { layout: horizontal; height: 1fr; }
    #actions { width: 30; border: solid gray; }
    #context { width: 36; border: solid gray; }
    #transcript { border: solid gray; padding: 0 1; }
    #bbar { dock: bottom; height: 4; }
    #status { height: 1; color: $text-muted; }
    #input { height: 3; border: solid $accent; background: $panel; color: $text; padding: 0 1; }
    """

    BINDINGS = [
        ("f1", "help", "Help"),
        ("f2", "toggle_left", "Left"),
        ("f3", "toggle_right", "Right"),
        ("f10", "palette", "Palette"),
        (":", "focus_input", "Cmd"),
        ("ctrl+i", "focus_input", "Focus input"),
        ("escape", "focus_input", "Focus input"),
        ("ctrl+c", "copy_to_clipboard", "Copy to clipboard"),
    ]

    last_tile: reactive[Optional[dict]] = reactive(None)
    hints_enabled: reactive[bool] = reactive(True)
    raw_enabled: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self.client = GameClient()
        self.router = CommandRouter()
        self._register_commands()
        self._last_command: Optional[str] = None
        # LLM settings
        self.llm_enabled: bool = True
        self.llm_model: str = os.getenv("OLLAMA_MODEL", "dnd-writer")
        # Keep a lightweight chat history for free-form messages
        self.chat_history: List[dict] = []

    def _register_commands(self) -> None:
        self.router.register(CommandSpec("start", "Start a new session", self._cmd_start, "Ctrl+N"))
        self.router.register(CommandSpec("end", "End active session", self._cmd_end, None))
        self.router.register(CommandSpec("reset", "Reset all sessions", self._cmd_reset, None))
        self.router.register(CommandSpec("move", "Move in a direction", self._cmd_move, "E/W/N/S"))
        self.router.register(CommandSpec("look", "Look around", self._cmd_look, "L"))
        self.router.register(CommandSpec("roll", "roll NdM or dM", self._cmd_roll, None))
        self.router.register(CommandSpec("spawn", "Spawn an NPC", self._cmd_spawn, None))
        self.router.register(CommandSpec("npc", "Show NPC by id", self._cmd_npc, None))
        self.router.register(CommandSpec("journal", "Show journal", self._cmd_journal, None))
        self.router.register(CommandSpec("sessions", "List sessions", self._cmd_sessions, None))
        self.router.register(CommandSpec("use", "Switch active session", self._cmd_use, None))
        self.router.register(CommandSpec("llm", "LLM mode on|off", self._cmd_llm, None))
        self.router.register(CommandSpec("raw", "Raw JSON on|off", self._cmd_raw, None))
        # Combat commands
        self.router.register(CommandSpec("generate", "generate encounter", self._cmd_generate, None))
        self.router.register(CommandSpec("attack", "attack \"weapon\" \"NdM\" [adv|dis]", self._cmd_attack, None))
        self.router.register(CommandSpec("combat", "combat status|end", self._cmd_combat, None))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            left = Actions(id="actions")
            try:
                left.can_focus = False
            except Exception:
                pass
            yield left
            # Enable rich markup and word wrapping if supported by the installed Textual
            self.transcript = TranscriptWidget(id="transcript", **_TRANSCRIPT_KW)
            try:
                self.transcript.can_focus = False
            except Exception:
                pass
            yield self.transcript
            right = Context(id="context")
            try:
                right.can_focus = False
            except Exception:
                pass
            yield right
        # Bottom bar with status+input above the footer
        with Vertical(id="bbar"):
            self.status = Static(id="status")
            yield self.status
            self.input = Input(placeholder="Message or :command …", id="input")
            yield self.input
        yield Footer()

    def on_mount(self) -> None:
        self._render_actions()
        self._render_context()
        llm_hint = " — LLM off (toggle with :llm on)" if not self.llm_enabled else " — LLM on"
        raw_hint = "; raw JSON hidden (enable with :raw on)" if not self.raw_enabled else "; raw JSON shown"
        self._info("Press F1 for help. Try :start or :look." + llm_hint + raw_hint)
        # Ensure typing goes straight to the input; schedule after first render
        try:
            self.call_after_refresh(lambda: self.set_focus(self.input))
        except Exception:
            self.set_focus(self.input)
        # Install a compatibility write wrapper to ensure wrapping/newlines even on older Textual
        try:
            original_write = self.transcript.write  # type: ignore[attr-defined]

            def _compat_write(msg: str) -> None:
                try:
                    width = max(20, (self.transcript.size.width or 80) - 2)  # type: ignore[attr-defined]
                except Exception:
                    width = 80
                text = str(msg)
                if not _TRANSCRIPT_SUPPORTS_MARKUP:
                    text = re.sub(r"\[[^\]]+\]", "", text)
                # Write each logical line wrapped to the current width
                lines = text.splitlines() or [""]
                for line in lines:
                    wrapped = textwrap.wrap(
                        line,
                        width=width,
                        replace_whitespace=False,
                        drop_whitespace=False,
                    ) or [""]
                    for w in wrapped:
                        original_write(w)

            # Override instance method to route through compatibility wrapper
            self.transcript.write = _compat_write  # type: ignore[assignment]
        except Exception:
            pass

    def action_focus_input(self) -> None:
        # Focus input and seed a colon for quick commands
        self.set_focus(self.input)
        if not self.input.value:
            self.input.value = ":"

    # ---------- Helpers ----------

    def _info(self, msg: str) -> None:
        # concise status near input, include last command if present
        if self._last_command:
            self.status.update(f"[bold]You:[/] {self._last_command}\n[bold cyan]ℹ️  {msg}[/]")
        else:
            self.status.update(f"[bold cyan]ℹ️  {msg}[/]")

    def _error(self, msg: str) -> None:
        if self._last_command:
            self.status.update(f"[bold]You:[/] {self._last_command}\n[bold red]❌ {msg}[/]")
        else:
            self.status.update(f"[bold red]❌ {msg}[/]")

    def _print_tile(self, payload: dict) -> None:
        pos = payload.get("position", {})
        exits = ", ".join(payload.get("exits", []))
        facts = "; ".join(payload.get("salient_facts", [])[:3])
        heading = payload.get("heading", "?")
        pos_str = f"({pos.get('x','?')}, {pos.get('y','?')}, {pos.get('z','?')})"
        self.transcript.write("")
        self.transcript.write(f"[b]🏰 {pos_str} facing {heading}[/]")
        self.transcript.write(f"📍 Exits: {exits}")
        self.transcript.write(f"📝 {facts}")
        self.transcript.write("")

    def _json_block(self, title: str, payload: dict) -> None:
        # pretty-print JSON payload in the center transcript
        try:
            dumped = json.dumps(payload, indent=2, ensure_ascii=False)
        except Exception:
            dumped = str(payload)
        # visual separation
        self.transcript.write("")
        self.transcript.write(f"[b]{title}[/]")
        for line in dumped.splitlines():
            self.transcript.write(f"  {line}")
        self.transcript.write("")

    def _print_narrative(self, text: str) -> None:
        # human-readable DM narrative in center panel
        self.transcript.write("")  # ensure separation from prior tool output
        self.transcript.write("[b]DM[/]")
        for line in (text or "").splitlines():
            self.transcript.write(line)
        self.transcript.write("")

    # ---------- LLM (Ollama) narrative ----------

    def _narrate_from_tile_async(self, payload: dict, event_id: Optional[int]) -> None:
        threading.Thread(target=self._narrate_from_tile, args=(payload, event_id), daemon=True).start()

    def _narrate_from_tile(self, payload: dict, event_id: Optional[int]) -> None:
        if not self.llm_enabled:
            return
        try:
            import ollama  # type: ignore
        except Exception as e:
            # Schedule UI update on main thread
            try:
                self.call_from_thread(self._error, f"LLM disabled — install ollama or set OLLAMA_MODEL. {e}")
            except Exception:
                pass
            return

        # Build a concise grounding prompt
        tile = payload.get("tile", {})
        pos = payload.get("position", {})
        exits = ", ".join(tile.get("exits", payload.get("exits", [])))
        entities = ", ".join([e.get("kind", e.get("name", "")) for e in tile.get("entities", [])])
        items = ", ".join([i.get("kind", "") for i in tile.get("items", [])])
        hazards = ", ".join(tile.get("hazards", []))
        facts = payload.get("salient_facts", [])
        brief_parts = []
        if exits:
            brief_parts.append(f"Exits: {exits}")
        if entities:
            brief_parts.append(f"Entities: {entities}")
        if items:
            brief_parts.append(f"Items: {items}")
        if hazards:
            brief_parts.append(f"Hazards: {hazards}")
        brief = "; ".join(brief_parts)

        max_words = int(payload.get("max_narrative_words", 500) or 500)
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a Dungeon Master. In up to {max_words} words, vividly describe what the player perceives at position {pos}. "
                    "Include the listed points of interest without inventing new exits/items/entities/hazards."
                ),
            },
            {
                "role": "user",
                "content": (
                    ("Environment: " + brief if brief else "Environment: (none)")
                    + "\nPoints of Interest:\n - "
                    + "\n - ".join(facts or [])
                ),
            },
        ]

        client = ollama.Client()
        start = time.time()
        try:
            resp = client.chat(
                model=self.llm_model,
                messages=messages,
                options={"num_predict": max(256, min(3072, max_words * 2)), "temperature": 0.8},
            )
            text = resp.get("message", {}).get("content", "")
            elapsed = int((time.time() - start) * 1000)
            # Schedule UI updates on the main thread
            try:
                self.call_from_thread(self._info, f"Narrative generated in {elapsed} ms")
                # add a blank line between tool output and LLM narrative and print readable text
                self.call_from_thread(self._print_narrative, text)
            except Exception:
                pass
            if event_id is not None:
                try:
                    self.client.log(text, event_id)
                except Exception:
                    pass
        except Exception as e:
            try:
                self.call_from_thread(self._error, f"LLM error: {e}")
            except Exception:
                pass

    # ---------- Free-form chat (LLM) ----------

    def _chat_from_text_async(self, user_text: str) -> None:
        threading.Thread(target=self._chat_from_text, args=(user_text,), daemon=True).start()

    def _chat_from_text(self, user_text: str) -> None:
        if not self.llm_enabled:
            try:
                self.call_from_thread(self._info, "LLM is OFF — enable with :llm on")
            except Exception:
                pass
            return
        try:
            import ollama  # type: ignore
        except Exception as e:
            try:
                self.call_from_thread(self._error, f"LLM disabled — install ollama or set OLLAMA_MODEL. {e}")
            except Exception:
                pass
            return

        # Build conversation with optional grounding from last_tile
        history = list(self.chat_history)
        history.append({"role": "user", "content": user_text})

        grounding = ""
        max_words = 500
        if self.last_tile:
            exits = ", ".join(self.last_tile.get("exits", []))
            facts = "; ".join(self.last_tile.get("salient_facts", [])[:3])
            grounding = (
                "Narrate vividly but stay consistent with tool facts. Current tile exits: "
                + exits
                + ". Salient facts: "
                + facts
                + "."
            )
            if isinstance(self.last_tile.get("max_narrative_words"), int):
                try:
                    max_words = int(self.last_tile.get("max_narrative_words") or 500)
                except Exception:
                    max_words = 500

        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a fantasy creative writer DM. Keep responses under {max_words} words and ground answers in provided tool facts when available."
                ),
            }
        ]
        if grounding:
            messages.append({"role": "system", "content": grounding})
        messages.extend(history)

        predict_tokens = int(max(256, min(2048, int(max_words * 1.6))))

        start = time.time()
        try:
            client = ollama.Client()  # type: ignore[name-defined]
            resp = client.chat(
                model=self.llm_model,
                messages=messages,
                options={"num_predict": predict_tokens, "temperature": 0.8},
            )
            text = resp.get("message", {}).get("content", "")
            elapsed = int((time.time() - start) * 1000)
            try:
                self.call_from_thread(self._info, f"Narrative generated in {elapsed} ms")
                self.call_from_thread(self._print_narrative, text)
            except Exception:
                pass
            # Persist chat history
            self.chat_history = history
            self.chat_history.append({"role": "assistant", "content": text})
        except Exception as e:
            try:
                self.call_from_thread(self._error, f"LLM error: {e}")
            except Exception:
                pass

    def _render_actions(self) -> None:
        lines: List[str] = ["[b]Actions[/]"]
        for spec in self.router.list_specs():
            kb = f" — {spec.shortcut}" if spec.shortcut else ""
            lines.append(f":{spec.name} — {spec.help}{kb}")
        self.query_one("#actions", Actions).update("\n".join(lines))

    def _render_context(self) -> None:
        if not self.last_tile:
            self.query_one("#context", Context).update("[b]Context[/]\n(no tile yet)\nTry :start or :look")
            return
        tile = self.last_tile.get("tile", {})
        ents = tile.get("entities", [])
        items = tile.get("items", [])
        ctx_lines = ["[b]Context[/]"]
        ctx_lines.append("[b]Tile[/]: " + tile.get("biome", "?") + ", " + tile.get("lighting", "?"))
        # Combat status summary if available
        combat = self.last_tile.get("combat") if isinstance(self.last_tile, dict) else None
        if combat and combat.get("active"):
            ctx_lines.append("[b]Combat[/]: Round " + str(combat.get("round", 1)))
            for e in combat.get("enemies", [])[:4]:
                ctx_lines.append(f" - {e.get('name', e.get('kind'))} HP {e.get('hp')}/{e.get('max_hp')} AC {e.get('armor_class')}")
        if ents:
            ctx_lines.append("[b]NPCs[/]:" )
            for e in ents[:5]:
                ctx_lines.append(f" - {e.get('name', e.get('kind'))} [{e.get('kind')}] {e.get('disposition','')}")
        if items:
            ctx_lines.append("[b]Items[/]:")
            for i in items[:5]:
                ctx_lines.append(f" - {i.get('kind')}")
        self.query_one("#context", Context).update("\n".join(ctx_lines))

    # ---------- Input handling ----------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.input.value = ""
        if not text:
            return
        # remember typed command for status area display
        self._last_command = text
        self.status.update(f"[bold]You:[/] {text}")
        # Dice shortcuts are handled here
        if text.startswith("!roll ") or text.startswith("!roll-a "):
            try:
                from tools.dnd_tools import roll_dice, roll_with_advantage
                if text.startswith("!roll-a "):
                    notation = text.split(" ", 1)[1]
                    adv = roll_with_advantage(notation)
                    msg = f" — {adv['message']}" if adv.get("message") else ""
                    self._info(f"Advantage {adv['notation']}: rolls={adv['rolls']} result={adv['result']}{msg}")
                else:
                    notation = text.split(" ", 1)[1]
                    res = roll_dice(notation)
                    self._info(f"Dice {res['notation']}: rolls={res['rolls']} total={res['total']}")
            except Exception as e:
                self._error(str(e))
            return

        try:
            handled = self.router.dispatch(text)
            if not handled:
                # Free-form chat: generate narrative via LLM and render in center transcript
                self._chat_from_text_async(text)
        except Exception as e:
            self._error(str(e))

    # ---------- Command handlers ----------

    def _cmd_start(self, _: str) -> None:
        payload = self.client.start()
        self.last_tile = payload
        self.chat_history = []
        self._info(f"Session started: {payload['session_id']}")
        self._print_tile(payload)
        if self.raw_enabled:
            self._json_block("Raw payload", payload)
        self._render_context()

    def _cmd_end(self, _: str) -> None:
        active = self.client.active()
        sid = active.get("session_id")
        if not sid:
            self._info("No active session")
            return
        res = self.client.end(sid)
        self._info(f"Ended session {res.get('ended')}")
        if self.raw_enabled:
            self._json_block("Raw payload", res)
        self.last_tile = None
        self.chat_history = []
        self._render_context()

    def _cmd_reset(self, _: str) -> None:
        self.client.reset()
        self._info("Reset all sessions")
        # no payload returned worth printing here
        self.last_tile = None
        self.chat_history = []
        self._render_context()

    def _cmd_move(self, arg: str) -> None:
        direction = (arg or "").strip()
        if not direction:
            self._error("Usage: :move <dir>")
            return
        payload = self.client.move(direction)
        self.last_tile = payload
        self._info(f"Move {direction} → event {payload.get('event_id')}")
        self._print_tile(payload)
        if self.raw_enabled:
            self._json_block("Raw payload", payload)
        self._render_context()
        # Kick off LLM narrative if enabled
        if self.llm_enabled:
            self._narrate_from_tile_async(payload, payload.get("event_id"))

    def _cmd_look(self, _: str) -> None:
        payload = self.client.look()
        self.last_tile = payload
        self._info("Look")
        self._print_tile(payload)
        if self.raw_enabled:
            self._json_block("Raw payload", payload)
        self._render_context()
        if self.llm_enabled:
            self._narrate_from_tile_async(payload, None)

    def _cmd_spawn(self, arg: str) -> None:
        parts = arg.split()
        name = parts[0] if len(parts) > 0 else None
        kind = parts[1] if len(parts) > 1 else None
        res = self.client.spawn(name, kind)
        npc = res["npc"]
        self._info(f"Spawned {npc['name']} (id={npc['id']}, kind={npc['kind']}, AC={npc['armor_class']})")
        if self.raw_enabled:
            self._json_block("Raw payload", res)
        # Refresh tile so context/transcript include new NPC and narrate about it
        try:
            payload = self.client.look()
            self.last_tile = payload
            self._print_tile(payload)
            self._render_context()
            if self.llm_enabled:
                self._narrate_from_tile_async(payload, res.get("event_id"))
        except Exception:
            # If look fails, still update context pane
            self._render_context()

    def _cmd_roll(self, arg: str) -> None:
        val = (arg or "").strip()
        if not val:
            self._error("Usage: :roll NdM or dM")
            return
        try:
            from tools.dnd_tools import roll_dice
            res = roll_dice(val)
            self._info(f"Dice {res['notation']}: rolls={res['rolls']} total={res['total']}")
        except Exception as e:
            self._error(str(e))

    def _cmd_generate(self, arg: str) -> None:
        # Accept: :generate encounter [name] [kind]
        parts = (arg or "").split()
        if len(parts) == 0 or parts[0] not in {"encounter", "encouter"}:
            self._error("Usage: :generate encounter [name] [kind]")
            return
        name = parts[1] if len(parts) > 1 else None
        kind = parts[2] if len(parts) > 2 else None
        try:
            payload = self.client.generate_encounter(name=name, kind=kind) if (name or kind) else self.client.generate_encounter()
        except Exception as e:
            self._error(str(e))
            return
        self.last_tile = payload
        self._info(payload.get("message", "Encounter generated"))
        self._print_tile(payload)
        if self.raw_enabled:
            self._json_block("Raw payload", payload)
        self._render_context()
        if self.llm_enabled:
            self._narrate_from_tile_async(payload, payload.get("event_id"))

    def _cmd_attack(self, arg: str) -> None:
        # Expect: "weapon" "NdM" [adv|dis]
        weapon = "attack"
        dmg = "1d6"
        adv = False
        dis = False
        s = arg.strip()
        try:
            if s.startswith('"'):
                idx = s.find('"', 1)
                weapon = s[1:idx]
                s = s[idx+1:].strip()
            parts = s.split()
            if parts:
                if parts[0].startswith('"'):
                    idx = s.find('"', 1)
                    dmg = s[1:idx]
                    rest = s[idx+1:].strip()
                else:
                    dmg = parts[0]
                    rest = " ".join(parts[1:]) if len(parts) > 1 else ""
                flag = (rest or "").lower()
                if flag in {"adv", "advantage"}: adv = True
                if flag in {"dis", "disadvantage"}: dis = True
        except Exception:
            pass
        try:
            payload = self.client.attack(weapon, dmg, advantage=adv, disadvantage=dis)
            msg = payload.get("message", "")
            # Status line summary
            self._info("Attack resolved")
            # Center transcript readable block
            self.transcript.write("")
            self.transcript.write("[b]🗡️  Attack[/]")
            if msg:
                for line in msg.splitlines():
                    self.transcript.write(line)
            # Print enemy HP summary if present
            combat = payload.get("combat") if isinstance(payload, dict) else None
            if combat and combat.get("enemies"):
                self.transcript.write("Enemies:")
                for e in combat.get("enemies", [])[:4]:
                    self.transcript.write(
                        f" - {e.get('name', e.get('kind'))} HP {e.get('hp')}/{e.get('max_hp')} AC {e.get('armor_class')}"
                    )
            self.transcript.write("")
            self.last_tile = payload
            if self.raw_enabled:
                self._json_block("Raw payload", payload)
            self._render_context()
        except Exception as e:
            self._error(str(e))
            # Also echo to transcript for visibility
            self.transcript.write("")
            self.transcript.write("[b]🗡️  Attack[/]")
            self.transcript.write(f"❌ {e}")
            self.transcript.write("")

    def _cmd_combat(self, arg: str) -> None:
        a = (arg or "").strip().lower()
        if a == "status":
            res = self.client.combat_status()
            self._info("Combat status")
            self._json_block("Combat", res)
            try:
                # Keep context pane in sync without losing other last_tile fields
                if isinstance(self.last_tile, dict):
                    self.last_tile["combat"] = res.get("combat")
                    self._render_context()
            except Exception:
                pass
            return
        if a == "end":
            res = self.client.combat_end()
            self._info(res.get("message", "The battle is finished."))
            try:
                if isinstance(self.last_tile, dict):
                    self.last_tile["combat"] = None
                    self._render_context()
            except Exception:
                pass
            return
        self._error("Usage: :combat status | :combat end")

    def _cmd_npc(self, arg: str) -> None:
        npc_id = arg.strip()
        if not npc_id:
            self._error("Usage: :npc <id>")
            return
        try:
            res = self.client.npc(npc_id)
            self._info(f"NPC {res['npc'].get('name')} — AC {res['npc'].get('armor_class')}")
            if self.raw_enabled:
                self._json_block("Raw payload", res)
        except Exception as e:
            self._error(str(e))

    def _cmd_journal(self, _: str) -> None:
        res = self.client.journal()
        lines = res.get("summary", [])
        if not lines:
            self._info("Journal is empty")
        else:
            self.transcript.write("")
            self.transcript.write("[b]📜 Journal[/]")
            for ln in lines:
                self.transcript.write(f" - {ln}")
            self.transcript.write("")
        if self.raw_enabled:
            self._json_block("Raw payload", res)

    def _cmd_sessions(self, _: str) -> None:
        res = self.client.sessions()
        self.transcript.write("")
        self.transcript.write("[b]🗂️  Sessions[/]")
        for s in res.get("sessions", []):
            mark = "*" if s.get("active") else " "
            pos = s.get("position", {})
            self.transcript.write(f" {mark} {s['session_id']} @ {pos} turn={s.get('turn')} heading={s.get('heading')}")
        self.transcript.write("")
        if self.raw_enabled:
            self._json_block("Raw payload", res)

    def _cmd_use(self, arg: str) -> None:
        sid = arg.strip()
        if not sid:
            self._error("Usage: :use <session_id>")
            return
        try:
            self.client.set_active(sid)
            self._info(f"Active session set: {sid}")
            if self.raw_enabled:
                self._json_block("Raw payload", {"active": sid})
        except Exception as e:
            self._error(str(e))

    def _cmd_llm(self, arg: str) -> None:
        val = (arg or "").strip().lower()
        if val in {"on", "true", "1"}:
            self.llm_enabled = True
            self._info(f"LLM mode ON (model={self.llm_model})")
        elif val in {"off", "false", "0"}:
            self.llm_enabled = False
            self._info("LLM mode OFF")
        else:
            self._info(f"LLM mode is {'ON' if self.llm_enabled else 'OFF'} — use :llm on|off")

    def _cmd_raw(self, arg: str) -> None:
        val = (arg or "").strip().lower()
        if val in {"on", "true", "1"}:
            self.raw_enabled = True
            self._info("Raw JSON ON")
        elif val in {"off", "false", "0"}:
            self.raw_enabled = False
            self._info("Raw JSON OFF")
        else:
            self._info(f"Raw JSON is {'ON' if self.raw_enabled else 'OFF'} — use :raw on|off")


if __name__ == "__main__":
    GameTUI().run()


