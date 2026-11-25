#!/bin/sh
# The engagement, unattended: a fresh project from material/, Claude Code with Morphogen's plugin and nothing
# else, then check.py on what it left. Nothing from engagement/ (the first run's results) or making/ (the
# generator, which knows the answers) is copied in.
#
#   demos/fernhill/run.sh WORKDIR [PLUGIN_DIR]
#
# PLUGIN_DIR: Morphogen's installed plugin (default: the newest copy under ~/.claude/plugins/cache/morphogen).
# Needs: git, python3, uv, Podman, Claude Code signed in. Spends a Claude Code session's usage (sonnet).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
work=${1:?usage: run.sh WORKDIR [PLUGIN_DIR]}
plugin=${2:-$(ls -d "$HOME"/.claude/plugins/cache/morphogen/morphogen/*/ | tail -1)}
mkdir -p "$work"
work=$(cd "$work" && pwd)
proj=$work/project
data=$work/data
[ -e "$proj" ] && { echo "$proj exists; use an empty WORKDIR" >&2; exit 1; }
mkdir -p "$proj" "$data"
cp -r "$here/material" "$proj/material"
cd "$proj"
git init -q -b main
git config user.name "Engagement"
git config user.email "engagement@example.invalid"
printf 'material/\nmorphogen.local.yaml\n__pycache__/\n' > .gitignore
git add .gitignore
git commit -qm "Engagement: start"
{ cat "$here/prompt.md"; printf '\nDATA (for held-out answers, outside the repository): %s\n' "$data"; } > "$work/prompt.txt"
claude -p --model sonnet --plugin-dir "$plugin" --permission-mode auto --add-dir "$data" \
  < "$work/prompt.txt" > "$work/session.txt" 2>&1 || echo "claude exited $?" >&2
python3 "$here/check.py" "$proj" "$plugin"
