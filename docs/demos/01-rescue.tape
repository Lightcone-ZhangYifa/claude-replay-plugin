# Demo 1 — RESCUE MODE: forgot to commit, hundreds of files dangling
#
# Recorded on the live claude-replay-plugin repo using its own session JSONLs.

Output docs/demos/01-rescue.gif
Set FontSize 16
Set Width 1100
Set Height 700
Set Theme "Dracula"
Set TypingSpeed 30ms
Set PlaybackSpeed 1.0
Set Padding 20
Set Margin 20

Hide
Type "cd /home/lightcone/claude-replay-plugin && clear"
Enter
Sleep 500ms
Show

Type "# 🚑 Forgot to commit? Let's see what claude-replay can recover."
Sleep 800ms
Enter
Sleep 600ms

Type "claude-replay status"
Sleep 800ms
Enter
Sleep 3500ms

Type "# Found ops sitting in session JSONLs. Now propose a commit chain..."
Sleep 1200ms
Enter
Sleep 600ms

Type "claude-replay plan --strategy time-gap --gap-minutes 30"
Sleep 800ms
Enter
Sleep 4500ms

Type "# Boundaries derived from natural pauses. Now build (sandbox first)..."
Sleep 1500ms
Enter
Sleep 600ms

Type "claude-replay execute --verbose 2>&1 | tail -25"
Sleep 800ms
Enter
Sleep 5500ms

Type "# 0 byte-divergence vs working tree. Add --apply to rewrite the real HEAD."
Sleep 2500ms
Enter
Sleep 1000ms
