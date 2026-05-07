# Demo 2 — LIFELINE: Claude deleted an important file. Get it back.

Output docs/demos/02-recover-file.gif
Set FontSize 16
Set Width 1100
Set Height 700
Set Theme "Dracula"
Set TypingSpeed 30ms
Set Padding 20
Set Margin 20

Hide
Type "cd /tmp && rm -rf recover-demo && mkdir recover-demo && cd recover-demo && clear"
Enter
Sleep 500ms
Show

Type "# Imagine we just lost an important file:"
Sleep 800ms
Enter
Sleep 400ms

Type "ls /home/lightcone/claude-replay-plugin/scripts/"
Sleep 600ms
Enter
Sleep 1500ms

Type "# Pretend replay_engine.py was deleted. Can we get it back?"
Sleep 1200ms
Enter
Sleep 600ms

Type "claude-replay recover-file \\"
Enter
Type "  --file /home/lightcone/claude-replay-plugin/scripts/replay_engine.py \\"
Enter
Type "  --list-versions"
Sleep 600ms
Enter
Sleep 4500ms

Type "# 10 historical versions. Reconstruct the latest:"
Sleep 1500ms
Enter
Sleep 400ms

Type "claude-replay recover-file \\"
Enter
Type "  --file /home/lightcone/claude-replay-plugin/scripts/replay_engine.py \\"
Enter
Type "  --output-dir ."
Sleep 600ms
Enter
Sleep 2500ms

Type "ls -la replay_engine.py && head -3 replay_engine.py"
Sleep 600ms
Enter
Sleep 3500ms

Type "# File restored, byte-perfect, from session JSONLs alone."
Sleep 2500ms
Enter
Sleep 800ms
