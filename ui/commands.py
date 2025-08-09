from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any, List


@dataclass
class CommandSpec:
    name: str
    help: str
    handler: Callable[[str], None]
    shortcut: Optional[str] = None


class CommandRouter:
    """Parse and dispatch colon-prefixed commands.

    Supports both ":move east" and natural aliases like "go east".
    """

    def __init__(self) -> None:
        self._commands: Dict[str, CommandSpec] = {}

    def register(self, spec: CommandSpec) -> None:
        self._commands[spec.name] = spec

    def list_specs(self) -> List[CommandSpec]:
        return list(self._commands.values())

    def dispatch(self, raw: str) -> bool:
        s = (raw or "").strip()
        if not s:
            return False
        # Normalize natural aliases
        if s.lower().startswith("go "):
            s = ":move " + s.split(" ", 1)[1]
        if s.lower().startswith("move ") and not s.startswith(":"):
            s = ":" + s

        if not s.startswith(":") and not s.startswith("!roll"):
            return False

        if s.startswith("!roll-a ") or s.startswith("!roll "):
            # handled outside (dice helpers)
            return False

        body = s[1:]
        cmd, *rest = body.split(" ", 1)
        arg = rest[0] if rest else ""
        spec = self._commands.get(cmd)
        if not spec:
            raise ValueError(f"Unknown command: :{cmd}")
        spec.handler(arg)
        return True


