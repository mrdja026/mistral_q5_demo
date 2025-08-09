Textual TUI (three-pane) for mistra-instruct-dnd

Run:

```
python -m ui.tui
```

- Left: Actions (shows colon commands and shortcuts)
- Center: Transcript (output and your input)
- Right: Context (tile, NPCs, items)

Keybindings: F1 Help, F2/F3 toggle panes (reserved), F10 Command Palette (reserved).

Notes:
- Chat LLM narrative is still handled by `loop.py`. This TUI currently focuses on tool-driven actions (:start/:end/:reset/:move/:look/:spawn/:journal/:sessions/:use, dice).
- Uses your existing tools from `tools/llm_tools_server.py`.

