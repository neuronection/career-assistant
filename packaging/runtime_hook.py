import os
import sys

_is_frozen = getattr(sys, "frozen", False)

if _is_frozen and sys.platform.startswith("linux"):
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        typelibs = os.path.join(meipass, "gi_typelibs")
        if os.path.isdir(typelibs):
            os.environ["GI_TYPELIB_PATH"] = (
                typelibs + os.pathsep + os.environ.get("GI_TYPELIB_PATH", "")
            ).rstrip(os.pathsep)
        schemas = os.path.join(meipass, "share", "glib-2.0", "schemas")
        if os.path.isfile(os.path.join(schemas, "gschemas.compiled")):
            os.environ["GSETTINGS_SCHEMA_DIR"] = schemas

if _is_frozen and (sys.stdout is None or sys.stderr is None):
    log_path = os.path.join(os.path.expanduser("~"), ".local", "share")
    try:
        target = os.path.join(log_path, "CareerAssistant", "logs")
        os.makedirs(target, exist_ok=True)
        log = open(os.path.join(target, "stdout.log"), "a", buffering=1, errors="replace")
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log
    except OSError:
        class _Null:
            def write(self, *_args):
                return None

            def flush(self):
                return None

        if sys.stdout is None:
            sys.stdout = _Null()
        if sys.stderr is None:
            sys.stderr = _Null()
