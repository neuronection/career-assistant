#!/usr/bin/env bash
# Build Linux packages for Career Assistant: PyInstaller onedir + optional .deb / .AppImage.
# Usage: packaging/build-linux.sh [bundle|deb|appimage|all] [version]
#   bundle   only the PyInstaller onedir tree (backend/dist/careerassistant)
#   deb      bundle + .deb (needs dpkg-deb; runtime needs libwebkit2gtk-4.1)
#   appimage bundle + AppImage (needs appimagetool; fully self-contained)
#   all      bundle + deb + appimage (default)
# Env: APPIMAGETOOL=/path/to/appimagetool (auto-detected on PATH),
#      CA_ONEFILE=0 is forced for Linux bundles.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="careerassistant"
TARGET="${1:-all}"
VERSION="${2:-}"
BUNDLE="$ROOT/backend/dist/$APP"
WORK="$ROOT/packaging/_build"
VENV_PY="$ROOT/backend/venv/bin/python"

if [[ -z "$VERSION" ]]; then
  VERSION="$(cd "$ROOT/backend" && "$VENV_PY" -c 'import app; print(app.__version__)')"
fi

if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
  echo "==> frontend/dist missing, building"
  (cd "$ROOT/frontend" && npm ci && npm run build)
fi

echo "==> PyInstaller onedir (version $VERSION)"
"$VENV_PY" -m PyInstaller --clean --noconfirm \
  --distpath "$ROOT/backend/dist" --workpath "$WORK" \
  "$ROOT/packaging/career-assistant.spec"

if [[ "$TARGET" == "bundle" ]]; then
  echo "==> Done: $BUNDLE"
  exit 0
fi

install_bundle() {
  local dest="$1"
  rm -rf "$dest"
  mkdir -p "$dest"
  cp -r "$BUNDLE/." "$dest/"
}

ICON="$ROOT/assets/icon-light.svg"

if [[ "$TARGET" == "deb" || "$TARGET" == "all" ]]; then
  STAGE="$ROOT/packaging/_deb"
  echo "==> Assembling .deb tree"
  rm -rf "$STAGE"
  mkdir -p "$STAGE/usr/lib/$APP" "$STAGE/usr/bin" \
    "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/scalable/apps" \
    "$STAGE/DEBIAN"
  install_bundle "$STAGE/usr/lib/$APP"

  cat > "$STAGE/usr/bin/$APP" <<EOF
#!/usr/bin/env bash
exec /usr/lib/$APP/$APP "\$@"
EOF
  chmod +x "$STAGE/usr/bin/$APP"

  cat > "$STAGE/usr/share/applications/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Career Assistant
Comment=AI-guided career discovery for students
Exec=$APP
Icon=$APP
Terminal=false
Categories=Education;Office;
Keywords=career;jobs;university;matching;students;
StartupWMClass=$APP
EOF

  cp "$ICON" "$STAGE/usr/share/icons/hicolor/scalable/apps/$APP.svg"

  cat > "$STAGE/DEBIAN/control" <<EOF
Package: $APP
Version: $VERSION
Section: education
Priority: optional
Architecture: amd64
Maintainer: Neuronection <dev@neuronection.com>
Depends: libgtk-3-0, libwebkit2gtk-4.1-0, libglib2.0-0, libgirepository-1.0-1
Description: AI-guided career discovery for students
 Self-hosted career-discovery platform: structured job catalog, deep student
 profiles, AI + human matching and university pathway intake. Runs fully
 locally; AI calls go to the provider you configure (cloud or local).
EOF

  DEB="$ROOT/packaging/${APP}_${VERSION}_amd64.deb"
  dpkg-deb --build --root-owner-group "$STAGE" "$DEB"
  echo "==> Done: $DEB"
fi

if [[ "$TARGET" == "appimage" || "$TARGET" == "all" ]]; then
  APPDIR="$ROOT/packaging/_appimage/AppDir"
  EXTRA="$APPDIR/usr/lib/ca-extra"
  echo "==> Assembling AppDir"
  rm -rf "$APPDIR"
  mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps"
  install_bundle "$APPDIR/usr/lib/$APP"

  collect_libs() {
    mkdir -p "$EXTRA"
    local -a queue=()
    local f dep dep_base target
    while IFS= read -r f; do queue+=("$f"); done < <(find "$APPDIR/usr/lib/$APP" -type f \( -name '*.so' -o -name '*.so.*' \))
    local name path
    for name in libwebkit2gtk-4.1.so.0 libjavascriptcoregtk-4.1.so.0 libgtk-3.so.0 \
      libgdk_pixbuf-2.0.so.0 libgirepository-1.0.so.1 libstdc++.so.6; do
      path="$(ldconfig -p | awk -v n="$name" '$1==n {print $NF; exit}')"
      [[ -n "$path" ]] && queue+=("$path")
    done

    local -A copied=()
    local -A bundled=()
    while IFS= read -r f; do bundled["$(basename "$f")"]=1; done < <(find "$APPDIR/usr/lib/$APP" -type f \( -name '*.so' -o -name '*.so.*' \))

    local exclude='^(ld-linux|libc\.|libm\.|libdl\.|libpthread\.|librt\.|libresolv\.|libnss_|libnsl|libcrypt|libutil\.|libanl\.|libBrokenLocale|libSegFault|libcidn|libSrpc|linux-vdso)'
    local -a pending=("${queue[@]}")
    while [[ ${#pending[@]} -gt 0 ]]; do
      f="${pending[0]}"; pending=("${pending[@]:1}")
      [[ -z "$f" || ! -f "$f" ]] && continue
      dep_base="$(basename "$f")"
      if [[ ! "$dep_base" =~ $exclude && -z "${bundled[$dep_base]:-}" && -z "${copied[$dep_base]:-}" ]]; then
        cp -L "$f" "$EXTRA/$dep_base"
        copied["$dep_base"]=1
        pending+=("$EXTRA/$dep_base")
      fi
      while IFS= read -r dep; do
        dep_base="$(basename "$dep")"
        [[ -z "$dep" ]] && continue
        if [[ "$dep_base" =~ $exclude ]]; then continue; fi
        if [[ -n "${bundled[$dep_base]:-}" || -n "${copied[$dep_base]:-}" ]]; then continue; fi
        target="$EXTRA/$dep_base"
        cp -L "$dep" "$target"
        copied["$dep_base"]=1
        pending+=("$target")
      done < <(ldd "$f" 2>/dev/null | awk '/=> \// {print $3} /^\// {print $1}')
    done
  }
  collect_libs

  local_loader_dir=""
  for d in /usr/lib/x86_64-linux-gnu /usr/lib64 /usr/lib; do
    for ld in "$d"/gdk-pixbuf-2.0/*/loaders; do
      [[ -d "$ld" ]] && local_loader_dir="$ld" && break 2
    done
  done
  # gdk-pixbuf-query-loaders is often not on PATH (Ubuntu ships it inside
  # the multiarch libdir), so resolve it from its known locations as well.
  query_loaders="$(command -v gdk-pixbuf-query-loaders || true)"
  if [[ -z "$query_loaders" ]]; then
    for q in /usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders \
             /usr/lib/*/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders \
             /usr/lib64/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders; do
      [[ -x "$q" ]] && query_loaders="$q" && break
    done
  fi
  if [[ -n "$local_loader_dir" && -n "$query_loaders" ]]; then
    mkdir -p "$EXTRA/pixbuf/loaders"
    cp -L "$local_loader_dir"/*.so "$EXTRA/pixbuf/loaders/" 2>/dev/null || true
    GDK_PIXBUF_MODULEDIR="$EXTRA/pixbuf/loaders" "$query_loaders" \
      | sed "s|$EXTRA|@APPDIR@/usr/lib/ca-extra|g" > "$EXTRA/pixbuf/loaders.cache.in"
  fi

  cp "$ICON" "$APPDIR/usr/share/icons/hicolor/scalable/apps/$APP.svg"
  cp "$ICON" "$APPDIR/$APP.svg"
  cat > "$APPDIR/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Career Assistant
Comment=AI-guided career discovery for students
Exec=AppRun
Icon=$APP
Terminal=false
Categories=Education;Office;
Keywords=career;jobs;university;matching;students;
StartupWMClass=$APP
EOF

  cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_LIBRARY_PATH="$APPDIR/usr/lib/ca-extra${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cache_src="$APPDIR/usr/lib/ca-extra/pixbuf/loaders.cache.in"
if [[ -f "$cache_src" ]]; then
  cache_gen="$(mktemp)"
  sed "s|@APPDIR@|$APPDIR|g" "$cache_src" > "$cache_gen"
  export GDK_PIXBUF_MODULE_FILE="$cache_gen"
fi
exec "$APPDIR/usr/lib/careerassistant/careerassistant" "$@"
EOF
  chmod +x "$APPDIR/AppRun"

  APPIMAGETOOL_BIN="${APPIMAGETOOL:-appimagetool}"
  if [[ ! -x "$APPIMAGETOOL_BIN" ]] && ! command -v "$APPIMAGETOOL_BIN" >/dev/null; then
    echo "appimagetool not found; set APPIMAGETOOL=/path/to/appimagetool" >&2
    exit 1
  fi
  TOOL_ARGS=()
  if file "$APPIMAGETOOL_BIN" 2>/dev/null | grep -qi "appimage"; then
    TOOL_ARGS=(--appimage-extract-and-run)
  fi
  OUT="$ROOT/packaging/CareerAssistant-$VERSION-x86_64.AppImage"
  "$APPIMAGETOOL_BIN" "${TOOL_ARGS[@]}" "$APPDIR" "$OUT"
  echo "==> Done: $OUT"
fi
