#!/bin/bash
# Screenshot homeplate pages at a true phone-width viewport, light and dark (dev tool).
# usage: [WIDTH=375] [BASE=http://localhost:8000] scripts/shots.sh OUT_DIR [path ...]   (paths default to /ask /settings /login)
# Needs the local stack: app on :8000, Mealie test admin. Writes OUT_DIR/<name>-light.png and -dark.png
set -euo pipefail
OUT=${1:?out dir}; shift || true
PATHS=("$@"); [ ${#PATHS[@]} -eq 0 ] && PATHS=(/ask /settings /login)
BASE=${BASE:-http://localhost:8000}
W=${WIDTH:-375}
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
mkdir -p "$OUT"; JAR="$OUT/jar.txt"; rm -f "$JAR"
curl -s -o /dev/null -c "$JAR" -d 'username=changeme@example.com' -d 'password=MyPassword' "$BASE/login"
curl -s "$BASE/static/app.css" > "$OUT/app.css"
# dark variant: make every dark-scheme media block apply unconditionally
sed -e 's/@media *(prefers-color-scheme: *dark)/@media all/g' "$OUT/app.css" > "$OUT/app-dark.css"
# light variant: switch the dark blocks off, whatever the machine's own appearance is
sed -e 's/@media *(prefers-color-scheme: *dark)/@media not all/g' "$OUT/app.css" > "$OUT/app-light.css"
for p in "${PATHS[@]}"; do
  n=$(echo "$p" | sed -e 's#^/$#home#' -e 's#^/##' -e 's#[/?=&]#_#g')
  if [ "$p" = /login ] || [[ "$p" == /s/* ]] || [[ "$p" == /join/* ]]; then curl -s "$BASE$p" > "$OUT/$n.raw"; else curl -s -b "$JAR" "$BASE$p" > "$OUT/$n.raw"; fi
  for mode in light dark; do
    css=app-light.css; [ $mode = dark ] && css=app-dark.css
    # local stylesheet copy, absolute base for images, htmx removed (it would redirect a cookieless file:// page)
    sed -e "s#<head>#<head><base href=\"$BASE/\">#" -e "s#/static/app.css#file://$OUT/$css#" -e '/htmx.min.js/d' "$OUT/$n.raw" > "$OUT/$n-$mode.html"
    printf '<body style="margin:0;background:#888"><iframe src="%s-%s.html" style="width:%spx;height:1500px;border:0;display:block"></iframe></body>' "$n" "$mode" "$W" > "$OUT/wrap-$n-$mode.html"
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files --window-size=$W,1500 \
      --screenshot="$OUT/$n-$mode.png" "file://$OUT/wrap-$n-$mode.html" >/dev/null 2>&1
    echo "$OUT/$n-$mode.png"
  done
done
