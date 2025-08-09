from __future__ import annotations

from typing import Optional, Dict, Any

# Reuse existing tool wrappers from the server module
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
    endSession,
    resetAll,
)


class GameClient:
    """Thin, synchronous facade over tool functions used by the TUI."""

    def start(self) -> Dict[str, Any]:
        return startSession()

    def end(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        return endSession(session_id)

    def reset(self) -> Dict[str, Any]:
        return resetAll()

    def move(self, direction: str) -> Dict[str, Any]:
        return moveDir(direction)

    def look(self) -> Dict[str, Any]:
        return lookAround()

    def journal(self) -> Dict[str, Any]:
        return journalSummary()

    def active(self) -> Dict[str, Any]:
        return getActiveSession()

    def set_active(self, session_id: str) -> Dict[str, Any]:
        return setActiveSession(session_id)

    def sessions(self) -> Dict[str, Any]:
        return listSessions()

    def spawn(self, name: Optional[str], kind: Optional[str]) -> Dict[str, Any]:
        return spawnNpc(name=name, kind=kind)

    def npc(self, npc_id: str) -> Dict[str, Any]:
        return getNpc(npc_id)

    def log(self, text: str, event_id: int) -> Dict[str, Any]:
        return logNarrative(text=text, eventId=event_id)


