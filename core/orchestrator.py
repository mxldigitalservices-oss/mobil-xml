from __future__ import annotations
import logging
import time

from core.adb_utils import adb_connect, adb_tap, adb_swipe, adb_screencap
from core.humanizer import (
    HumanizeConfig,
    organic_pause,
    bezier_segments,
    gaussian_delay,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Orchestrator")


class OrchestratorEngine:
    def __init__(self, device_id: str, config: HumanizeConfig | None = None):
        self.device_id = device_id
        self.config = config or HumanizeConfig()

    def connect_adb(self) -> bool:
        ok = adb_connect(self.device_id)
        logger.info(f"ADB Connect result for {self.device_id}: {ok}")
        return ok

    # --- Verificación visual ---
    def visual_precheck(self, expected_marker: str | None = None) -> bool:
        """
        Captura pantalla y verifica que hay contenido renderizado antes de actuar.
        Con integración OpenCV/OCR se puede comparar contra expected_marker;
        por ahora sólo valida que el frame no esté vacío.
        """
        try:
            frame = adb_screencap(self.device_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"screencap falló en {self.device_id}: {exc}")
            return False
        return len(frame) > 1000

    # --- Swipe humanizado ---
    def _human_swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        if not self.config.humanize:
            adb_swipe(self.device_id, x1, y1, x2, y2, duration_ms)
            return

        pts = bezier_segments((x1, y1), (x2, y2))
        prev = (x1, y1)
        step_ms = max(10, duration_ms // len(pts))
        for curr in pts:
            adb_swipe(self.device_id, prev[0], prev[1], curr[0], curr[1], step_ms)
            prev = curr
            time.sleep(gaussian_delay(mu=0.03, sigma=0.01))

    # --- Ejecución ---
    def execute_action(self, action: str, payload: dict) -> None:
        logger.info(f"[{self.device_id}] action={action} payload={payload}")

        if not self.visual_precheck():
            logger.warning(f"[{self.device_id}] pantalla no lista, abortando")
            return

        if action == "tap":
            x, y = payload.get("x", 0), payload.get("y", 0)
            if self.config.humanize:
                time.sleep(gaussian_delay(mu=0.15, sigma=0.05))
            adb_tap(self.device_id, x, y)

        elif action == "swipe":
            self._human_swipe(
                payload.get("x1", 0),
                payload.get("y1", 0),
                payload.get("x2", 0),
                payload.get("y2", 0),
                payload.get("duration", 300),
            )

        elif action == "sleep":
            secs = payload.get("seconds")
            if secs is None:
                secs = organic_pause(self.config.media_type) if self.config.humanize else 1
            time.sleep(float(secs))

        else:
            logger.warning(f"Acción no soportada: {action}")
