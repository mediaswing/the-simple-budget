"""Self-update: check GitHub Releases for a newer build and, when running as
a frozen PyInstaller build, download and swap the running app in place.

Running from source (``python budget_app.py``) never self-updates -- only
``check_latest_release`` is useful there, so the caller can show a "here's
what's new, go get it" message instead of a download button.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass

GITHUB_REPO = "mediaswing/the-simple-budget"
APP_NAME = "TheSimpleBudget"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

_ASSET_BY_PLATFORM = {
    "darwin": f"{APP_NAME}-macos.zip",
    "win32": f"{APP_NAME}-windows.zip",
    "linux": f"{APP_NAME}-linux.zip",
}


@dataclass
class ReleaseInfo:
    version: str             # "0.6.0"
    version_tuple: tuple
    notes: str
    asset_url: str | None    # None if this platform has no matching asset


def parse_version(text: str) -> tuple:
    """"v1.2.3" -> (1, 2, 3). Non-numeric trailing bits (rc1, etc) are dropped."""
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _compare_versions(a: tuple, b: tuple) -> int:
    """-1/0/1, like the old cmp(). Pads the shorter tuple with zeros first so
    "1.3" and "1.3.0" compare equal instead of the shorter one always
    losing."""
    length = max(len(a), len(b))
    a = a + (0,) * (length - len(a))
    b = b + (0,) * (length - len(b))
    return (a > b) - (a < b)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def check_latest_release(current_version: str, timeout: int = 5) -> ReleaseInfo | None:
    """Return a ReleaseInfo if a newer version is published, else None.

    Any failure (offline, rate-limited, no releases yet, bad JSON) is
    swallowed and returns None -- callers decide whether to surface that.
    """
    try:
        req = urllib.request.Request(
            RELEASES_API_URL, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None

    tag = data.get("tag_name") or ""
    if not tag:
        return None
    remote_version = parse_version(tag)
    if _compare_versions(remote_version, parse_version(current_version)) <= 0:
        return None

    asset_name = _ASSET_BY_PLATFORM.get(sys.platform)
    asset_url = None
    for asset in data.get("assets", []):
        if asset.get("name") == asset_name:
            asset_url = asset.get("browser_download_url")
            break

    return ReleaseInfo(
        version=tag.lstrip("vV"),
        version_tuple=remote_version,
        notes=(data.get("body") or "").strip(),
        asset_url=asset_url,
    )


def _log_path() -> str:
    # Deliberately NOT next to the executable: on Windows/Linux that's the
    # install directory itself, which the update script renames out from
    # under this path partway through -- writing the log there breaks the
    # log redirection for every command that runs after the rename.
    return os.path.join(tempfile.gettempdir(), f"{APP_NAME}-updater.log")


def _log(log_path: str, message: str) -> None:
    with open(log_path, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}: {message}\n")


def _download(url: str, dest: str, timeout: int = 60) -> None:
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)
    if os.path.getsize(dest) == 0:
        raise OSError(f"Downloaded file is empty: {url}")


def _safe_extract(zip_path: str, dest_dir: str) -> None:
    """extractall(), but refusing any member whose path would land outside
    dest_dir (a maliciously or corruptly crafted zip could otherwise write
    anywhere on disk via "../" entries -- "zip slip")."""
    dest_abs = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = os.path.abspath(os.path.join(dest_abs, member))
            if target != dest_abs and not target.startswith(dest_abs + os.sep):
                raise OSError(f"Update archive has an unsafe entry: {member!r}")
        zf.extractall(dest_abs)


def _install_root() -> str:
    """Path to the directory that must be replaced: the .app bundle on
    macOS, or the onedir folder containing the exe on Windows/Linux."""
    exe = os.path.abspath(sys.executable)
    if sys.platform == "darwin":
        # exe is .../TheSimpleBudget.app/Contents/MacOS/TheSimpleBudget --
        # walk up from it and take the *nearest* ".app" ancestor, rather
        # than string-splitting on the first occurrence of ".app/" (which
        # picks the wrong directory if some earlier path segment also
        # happens to end in ".app").
        path = exe
        while True:
            parent = os.path.dirname(path)
            if parent == path:
                break
            if path.endswith(".app"):
                return path
            path = parent
        raise OSError(f"Could not find the enclosing .app bundle for {exe!r}")
    return os.path.dirname(exe)


_POSIX_SCRIPT = textwrap.dedent("""\
    #!/bin/sh
    # Auto-generated by updater.py -- waits for the old process to exit,
    # swaps the install directory, relaunches, and deletes itself.
    PID="$1"
    INSTALL="$2"
    NEWDIR="$3"
    LOG="$4"
    PLATFORM="$5"

    while kill -0 "$PID" 2>/dev/null; do sleep 0.2; done

    {
      echo "$(date): replacing $INSTALL"
      BAK="$INSTALL.bak"
      rm -rf "$BAK"
      if mv "$INSTALL" "$BAK" && mv "$NEWDIR" "$INSTALL"; then
        echo "$(date): replaced ok"
      else
        echo "$(date): replace FAILED, leaving backup at $BAK"
        exit 1
      fi
    } >> "$LOG" 2>&1

    if [ "$PLATFORM" = "darwin" ]; then
      open "$INSTALL"
    else
      chmod +x "$INSTALL/{app_name}" 2>>"$LOG"
      nohup "$INSTALL/{app_name}" >/dev/null 2>&1 &
    fi

    rm -rf "$(dirname "$0")"
    """)

_WINDOWS_SCRIPT = textwrap.dedent("""\
    @echo off
    rem Auto-generated by updater.py -- waits for the old process to exit,
    rem swaps the install directory, relaunches, and deletes itself.
    set PID=%~1
    set INSTALL=%~2
    set NEWDIR=%~3
    set LOG=%~4

    :wait
    tasklist /FI "PID eq %PID%" 2>NUL | find "%PID%" >NUL
    if not errorlevel 1 (
        timeout /t 1 /nobreak >NUL
        goto wait
    )

    >>"%LOG%" echo %date% %time% replacing %INSTALL%
    if exist "%INSTALL%.bak" rmdir /s /q "%INSTALL%.bak"

    rem /Y suppresses the interactive overwrite prompt -- this script is
    rem launched detached with no console/stdin, so an unanswered prompt
    rem would hang forever.
    move /Y "%INSTALL%" "%INSTALL%.bak" >>"%LOG%" 2>&1
    if errorlevel 1 (
        >>"%LOG%" echo %date% %time% FAILED to move %INSTALL% aside, aborting
        goto cleanup
    )
    move /Y "%NEWDIR%" "%INSTALL%" >>"%LOG%" 2>&1
    if errorlevel 1 (
        >>"%LOG%" echo %date% %time% FAILED to move the new build into place -- old build left at %INSTALL%.bak
        goto cleanup
    )
    >>"%LOG%" echo %date% %time% replaced ok

    start "" "%INSTALL%\\{app_name}.exe"

    :cleanup
    del "%~f0"
    """)


def perform_self_update(release: ReleaseInfo) -> None:
    """Download `release`'s asset, extract it, hand off to a detached helper
    script that swaps the install directory once this process exits, then
    terminate this process immediately.

    Raises OSError/urllib errors on failure *before* the handoff (download,
    extraction, or missing asset) so the caller can show an error dialog.
    Once the helper script is launched there is no return -- the process
    exits via ``os._exit`` so the file lock releases right away.
    """
    if not release.asset_url:
        raise OSError("No download available for this platform.")

    log = _log_path()
    _log(log, f"Starting update to {release.version}")
    tmp_dir = tempfile.mkdtemp(prefix="TheSimpleBudget-update-")
    zip_path = os.path.join(tmp_dir, "update.zip")
    _download(release.asset_url, zip_path)
    _log(log, f"Downloaded {release.asset_url}")

    extract_dir = os.path.join(tmp_dir, "extracted")
    _safe_extract(zip_path, extract_dir)

    if sys.platform == "darwin":
        new_root = os.path.join(extract_dir, f"{APP_NAME}.app")
    else:
        new_root = os.path.join(extract_dir, APP_NAME)
    if not os.path.exists(new_root):
        raise OSError(f"Downloaded update didn't contain {new_root!r}")

    install_root = _install_root()
    pid = str(os.getpid())
    _log(log, f"Handing off: pid={pid} install={install_root} new={new_root}")

    if sys.platform == "win32":
        script_path = os.path.join(tmp_dir, "update.bat")
        with open(script_path, "w") as f:
            f.write(_WINDOWS_SCRIPT.format(app_name=APP_NAME))
        subprocess.Popen(
            ["cmd", "/c", script_path, pid, install_root, new_root, log],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    else:
        script_path = os.path.join(tmp_dir, "update.sh")
        with open(script_path, "w") as f:
            f.write(_POSIX_SCRIPT.format(app_name=APP_NAME))
        os.chmod(script_path, 0o755)
        subprocess.Popen(
            ["/bin/sh", script_path, pid, install_root, new_root, log, sys.platform],
            start_new_session=True,
            close_fds=True,
        )

    os._exit(0)
