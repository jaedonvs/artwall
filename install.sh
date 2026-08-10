#!/usr/bin/env bash
# Install both launchd agents, with paths resolved to this checkout.
#
#   fill   — weekly, does all the network work, stocks the backlog
#   rotate — daily, just moves one file backlog -> live -> archive
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LA="$HOME/Library/LaunchAgents"

chmod +x "$REPO/artwall.py"
mkdir -p "$LA" "$HOME/Pictures/Wallpapers" "$HOME/Pictures/artwall"

agent() {  # name, schedule-xml, args...
  local name="$1" schedule="$2"; shift 2
  local label="com.jaedon.artwall.$name" plist="$LA/com.jaedon.artwall.$name.plist"
  local argxml=""
  for a in "$@"; do argxml+="        <string>$a</string>"$'\n'; done

  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$label</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$REPO/artwall.py</string>
$argxml    </array>
    <key>StartCalendarInterval</key>
    $schedule
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/artwall.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/artwall.log</string>
</dict>
</plist>
PLIST

  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "  installed $label"
}

# Retire the old single-agent install, if present.
launchctl bootout "gui/$(id -u)/com.jaedon.artwall" 2>/dev/null || true
rm -f "$LA/com.jaedon.artwall.plist"

agent fill \
  '<dict><key>Weekday</key><integer>0</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>' \
  --add 7
agent rotate \
  '<dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>' \
  --rotate

cat <<EOF

  fill    Sundays 08:00   fetches 7 into the backlog (all the network work)
  rotate  daily 07:00     moves one file backlog -> live -> archive

Logs: ~/Library/Logs/artwall.log
Status: $REPO/artwall.py --list

One manual step, once:
  System Settings -> Wallpaper -> Add Folder -> ~/Pictures/Wallpapers
  then set 'Change picture: Every day' + 'Random order'

The live folder holds exactly one image on purpose: macOS shuffles the desktop
and lock screen independently, so a one-item folder is the only choice both
can land on.
EOF
