#!/usr/bin/env bash
# Install the weekly launchd agent, with paths resolved to this checkout.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.jaedon.artwall"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

chmod +x "$REPO/artwall.py"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Pictures/Wallpapers"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$REPO/artwall.py</string>
        <string>--add</string>
        <string>1</string>
        <string>--keep</string>
        <string>1</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>7</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/artwall.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/artwall.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed $LABEL -> $REPO/artwall.py"
echo "Runs daily at 07:00, swapping the single image. Logs: ~/Library/Logs/artwall.log"
echo
echo "One manual step remains:"
echo "  System Settings -> Wallpaper -> Add Folder -> ~/Pictures/Wallpapers"
echo "  then set 'Change picture: Every day' + 'Random order'"
echo
echo "Keeping exactly one image is what makes the desktop and lock screen agree:"
echo "macOS shuffles them independently, so a one-item folder is the only choice"
echo "both can land on."
