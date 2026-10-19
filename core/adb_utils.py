from __future__ import annotations
import subprocess


def adb_connect(device_id: str) -> bool:
    res = subprocess.run(
        ["adb", "connect", device_id], capture_output=True, text=True
    )
    return res.returncode == 0


def adb_tap(device_id: str, x: int, y: int) -> None:
    subprocess.run(
        ["adb", "-s", device_id, "shell", "input", "tap", str(x), str(y)],
        check=True,
    )


def adb_swipe(device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
    subprocess.run(
        ["adb", "-s", device_id, "shell", "input", "swipe",
         str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
        check=True,
    )


def adb_screencap(device_id: str) -> bytes:
    """Captura binaria (PNG) — no requiere guardar archivo en el nodo."""
    res = subprocess.run(
        ["adb", "-s", device_id, "exec-out", "screencap", "-p"],
        capture_output=True,
        check=True,
    )
    return res.stdout
