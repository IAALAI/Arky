#!/usr/bin/env bash
# Start the existing native ARM Waydroid environment used for game debugging.
set -euo pipefail
ARK_ROOT=/home/iaalai/player/Ark
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export WAYLAND_DISPLAY=wayland-arka
sudo -v
sudo systemctl start arknights.service nginx
if ! pgrep -f '^weston .*--socket=wayland-arka( |$)' >/dev/null; then
  nohup weston --backend=headless-backend.so --socket=wayland-arka --idle-time=0 \
    --width=1280 --height=720 --config="$ARK_ROOT/client/weston.ini" \
    > "$ARK_ROOT/newVersion/reports/weston.log" 2>&1 </dev/null &
  sleep 1
fi
if ! waydroid status | grep -q 'Wayland display:.*wayland-arka'; then
  waydroid session stop || true
  nohup waydroid session start > "$ARK_ROOT/newVersion/reports/waydroid-session.log" 2>&1 </dev/null &
fi
for attempt in $(seq 1 60); do
  if sudo waydroid shell -- getprop sys.boot_completed 2>/dev/null | tr -d '\r' | grep -qx 1; then
    break
  fi
  sleep 1
done
sudo waydroid container unfreeze
sudo waydroid shell -- setprop persist.waydroid.suspend false
sudo waydroid shell -- setprop service.adb.tcp.port 5555
sudo waydroid shell -- stop adbd
sudo waydroid shell -- start adbd
guest_ip="$(waydroid status | awk '/IP address:/ {print $3}')"
adb connect "$guest_ip:5555"
waydroid app launch com.hypergryph.arknights
printf 'Waydroid client started on %s; use adb for screenshots/input.\n' "$WAYLAND_DISPLAY"
