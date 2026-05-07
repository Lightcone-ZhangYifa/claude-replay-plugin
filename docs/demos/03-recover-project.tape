# Demo 3 — BACK FROM THE DEAD: rm -rf'd your project, only JSONLs remain.

Output docs/demos/03-recover-project.gif
Set FontSize 16
Set Width 1100
Set Height 700
Set Theme "Dracula"
Set TypingSpeed 30ms
Set Padding 20
Set Margin 20

Hide
Type "cd /tmp && rm -rf project-revival && clear"
Enter
Sleep 500ms
Show

Type "# Imagine: you accidentally rm -rf'd ~/myproject."
Sleep 1500ms
Enter
Type "# But ~/.claude/projects/ still has all the session JSONLs..."
Sleep 1500ms
Enter
Sleep 600ms

Type "ls ~/.claude/projects/ | head -3"
Sleep 600ms
Enter
Sleep 2500ms

Type "# Pick the deleted project's encoded name and recover everything:"
Sleep 1500ms
Enter
Sleep 400ms

Type "claude-replay recover-project \\"
Enter
Type "  --project-name -home-lightcone-claude-replay-plugin \\"
Enter
Type "  --output-dir /tmp/project-revival \\"
Enter
Type "  --git-init"
Sleep 600ms
Enter
Sleep 5500ms

Type "ls /tmp/project-revival && echo && git -C /tmp/project-revival log --oneline"
Sleep 600ms
Enter
Sleep 4000ms

Type "# Project resurrected from JSONLs, with git history bootstrapped."
Sleep 2500ms
Enter
Sleep 800ms
