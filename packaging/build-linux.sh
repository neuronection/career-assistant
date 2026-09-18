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

# PDF engine (plan 76): the playwright package must be importable when the
# spec runs (its node driver rides as package data), and the Chromium headless
# shell lands next to the executable where _bundled_browsers_path() finds it.
echo "==> Installing the PDF engine into the build venv"
"$VENV_PY" -m pip install -q -r "$ROOT/backend/requirements-pdf.txt"

echo "==> PyInstaller onedir (version $VERSION)"
"$VENV_PY" -m PyInstaller --clean --noconfirm \
  --distpath "$ROOT/backend/dist" --workpath "$WORK" \
  "$ROOT/packaging/career-assistant.spec"

echo "==> Bundling the Chromium headless shell (PDF page-count truth)"
PLAYWRIGHT_BROWSERS_PATH="$BUNDLE/ms-playwright" "$ROOT/backend/venv/bin/playwright" \
  install chromium --only-shell

echo "==> Smoke test: frozen enginecheck (bundled browser must print 1 page)"
"$BUNDLE/careerassistant" enginecheck

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

  # The .deb runs against the SYSTEM GTK stack (see Depends below).
  # PyInstaller collects the build host's GLib/GTK binaries, typelibs and
  # GIO modules next to the executable, and a bundled old GLib hijacks
  # newer hosts: the system webkit/gudev then fail with undefined symbols
  # (g_once_init_enter_pointer, webkit_get_major_version) and pygobject
  # dies at boot. Strip the stack so every GI/symbol resolution falls
  # back to the system libraries the control file guarantees — the smoke
  # in release.yml boots this exact stage under xvfb. The AppImage keeps
  # its self-contained, internally consistent 22.04 stack instead.
  INTERNAL="$STAGE/usr/lib/$APP/_internal"
  rm -f "$INTERNAL"/libglib-2.0.so.* "$INTERNAL"/libgobject-2.0.so.* \
    "$INTERNAL"/libgio-2.0.so.* "$INTERNAL"/libgmodule-2.0.so.* \
    "$INTERNAL"/libgthread-2.0.so.* \
    "$INTERNAL"/libgtk-3.so.* "$INTERNAL"/libgdk-3.so.* \
    "$INTERNAL"/libgdk_pixbuf-2.0.so.* \
    "$INTERNAL"/libgirepository-1.0.so.* \
    "$INTERNAL"/libpango-1.0.so.* "$INTERNAL"/libpangocairo-1.0.so.* \
    "$INTERNAL"/libpangoft2-1.0.so.* \
    "$INTERNAL"/libcairo.so.* "$INTERNAL"/libcairo-gobject.so.*
  # The text stack rides the same rule: a bundled old harfbuzz hijacks
  # newer hosts' system pango (undefined hb_ot_color_has_paint on
  # Ubuntu 24.04 / Mint 22 — pango 1.52 is built against harfbuzz 8).
  # System freetype/graphite/png resolve through the control file's
  # libwebkit2gtk-4.1 depends.
  rm -f "$INTERNAL"/libharfbuzz*.so.* "$INTERNAL"/libgraphite2*.so.* \
    "$INTERNAL"/libfreetype*.so.* "$INTERNAL"/libpng16*.so.* \
    "$INTERNAL"/libbrotli*.so.*
  # Orphans of the stripped GTK stack (pulled in as cairo/pixman/glib
  # deps on the build host): a bundled 22.04 libxcb/libXau/libmount can
  # hijack the system X/GL stack of a newer host and break WebKit's
  # display init in driver-specific ways. Everything here resolves to
  # system equivalents via the GTK depends.
  rm -f "$INTERNAL"/libxcb*.so.* "$INTERNAL"/libXau*.so.* \
    "$INTERNAL"/libXdmcp*.so.* "$INTERNAL"/libmount*.so.* \
    "$INTERNAL"/libblkid*.so.* "$INTERNAL"/libselinux*.so.* \
    "$INTERNAL"/libpcre2*.so.* "$INTERNAL"/libffi*.so.*
  rm -rf "$INTERNAL/gio_modules" "$INTERNAL/gi_typelibs" \
    "$INTERNAL/share/glib-2.0"

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
Depends: libgtk-3-0, libwebkit2gtk-4.1-0, libglib2.0-0, libgirepository-1.0-1, libnss3, libnspr4, libasound2, libgbm1, libxkbcommon0
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

    # PDF engine (plan 76): the bundled Chromium headless shell brings its
    # own ELF deps (nss, alsa, gbm, …). Queue only its DEPENDENCIES — the
    # browser itself already lives inside the bundle. Core glibc family is
    # never copied (it would hijack the loader on the target system).
    local exclude='^(libc\.so|libm\.so|libdl\.so|libpthread\.so|ld-linux|librt\.so|libnsl\.so|libresolv\.so|libcrypt\.so)'
    while IFS= read -r dep; do
      dep_base="$(basename "$dep")"
      [[ -z "$dep" ]] && continue
      [[ "$dep_base" =~ $exclude ]] && continue
      [[ -n "${bundled[$dep_base]:-}" || -n "${copied[$dep_base]:-}" ]] && continue
      queue+=("$dep")
    done < <(find "$APPDIR/usr/lib/$APP/ms-playwright" -type f 2>/dev/null \
      | xargs -r file \
      | awk -F: '$2 ~ /ELF/ {print $1}' \
      | xargs -r -n1 ldd \
      | awk '/=> \// {print $3} /^\// {print $1}' \
      | sort -u)

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
