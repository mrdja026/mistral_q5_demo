# Feature Combat

- Create a command called generate encouter that will call spawn tool, to reuse code
- All custom commands that needs to be createw will need to be in the dnd_tools.py and then impoted to llm_tools.server.py to leverage the MCP history, since encouter should be there.

- UI should not call any tool directly

- I can free talk whenever i want 
- keep the track of enemy state and print it after every action in readable format
- devise a system for fight
  -  i need to roll d20 via :roll d20 to see if i hit, we have that tool reuse it
  - then if it hits, i need to call :attack "weapon" "2d6" with optional advantage and disadvantage
  roll tool should be reused weapon is a placeholder and just a name, 
  "2d6" is a placeholder it should be the same format as roll tool
  - write the outcome of that action
  - then the enemy does those actions on its own automaticlyu
-Combat is active until :combat end
- After the encounter end it shold clear that memory frtom MCP server
- UI must remain the same
- Output should be readable
- Cursor rules should be used
- Reuse much of the code you can
-After custom toolkit :combat end is executed output should be the battle is finished
- I can perform any tool action again or free form in any variation
- All other features must be preserved

