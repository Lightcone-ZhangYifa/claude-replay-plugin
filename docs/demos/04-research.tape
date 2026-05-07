# Demo 4 — RESEARCH: structured event log for AI-agent behavior analysis.

Output docs/demos/04-research.gif
Set FontSize 16
Set Width 1100
Set Height 700
Set Theme "Dracula"
Set TypingSpeed 30ms
Set Padding 20
Set Margin 20

Hide
Type "cd /home/lightcone/claude-replay-plugin && clear"
Enter
Sleep 500ms
Show

Type "# Research mode -- structured event log for AI-agent behavior analysis."
Sleep 1500ms
Enter
Sleep 600ms

Type "claude-replay analyze --format stats 2>/dev/null | head -20"
Sleep 600ms
Enter
Sleep 4500ms

Type "# Per-tool failure rates, hot files, sub-agent split -- instantly visible."
Sleep 2000ms
Enter
Sleep 400ms

Type "# Pipe JSONL into jq for arbitrary slicing:"
Sleep 1200ms
Enter
Sleep 400ms

Type "bash docs/demos/research-demo.sh"
Sleep 600ms
Enter
Sleep 4500ms

Type "# Files where Edits failed most often -- a self-correction proxy."
Sleep 2500ms
Enter
Sleep 800ms
