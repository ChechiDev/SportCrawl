#!/bin/sh
set -e

# Chrome >= 112 always binds --remote-debugging-port to 127.0.0.1 regardless
# of --remote-debugging-address. We start Chromium on internal port 9223 and
# proxy externally via socat so Docker port-mapping works.
#
# We use Xvfb (virtual framebuffer) instead of --headless so Cloudflare
# cannot detect headless mode via browser fingerprinting. Xvfb provides a
# real X display backed by memory — Chromium behaves identically to a
# headed browser from Cloudflare's perspective.

# Start virtual display
Xvfb :99 -screen 0 1920x1080x24 &
XVFB_PID=$!
export DISPLAY=:99

# Give Xvfb a moment to initialise
sleep 1

chromium \
  --no-sandbox \
  --disable-dev-shm-usage \
  --use-angle=swiftshader \
  --enable-webgl \
  --enable-webgl2 \
  --disable-blink-features=AutomationControlled \
  --user-data-dir=/tmp/chrome-profile \
  --window-size=1920,1080 \
  --remote-debugging-port=9223 \
  --load-extension=/opt/sportcrawl-chrome \
  &

# Wait until Chromium's CDP endpoint is up
echo "Waiting for Chromium CDP on 127.0.0.1:9223..."
until curl -sf http://127.0.0.1:9223/json/version > /dev/null 2>&1; do
  sleep 1
done
echo "Chromium ready (Xvfb display :99). Proxying 0.0.0.0:9222 -> 127.0.0.1:9223"

# Proxy external 9222 → internal 9223 so Docker port mapping works
exec socat TCP-LISTEN:9222,bind=0.0.0.0,fork,reuseaddr TCP:127.0.0.1:9223
