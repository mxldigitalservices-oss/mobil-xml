from __future__ import annotations
import random
from dataclasses import dataclass


@dataclass
class HumanizeConfig:
    humanize: bool = True
    media_type: str = "video"  # "video" | "audio"


def gaussian_delay(mu: float, sigma: float, min_delay: float = 0.05) -> float:
    """Retardo gaussiano no negativo (clamp inferior)."""
    value = random.gauss(mu, sigma)
    return max(min_delay, value)


def organic_pause(media_type: str) -> float:
    """Pausa orgánica según tipo de medio."""
    if media_type == "video":
        return gaussian_delay(mu=4.5, sigma=1.2)
    if media_type == "audio":
        return gaussian_delay(mu=8.0, sigma=2.5)
    return gaussian_delay(mu=2.0, sigma=0.8)


def cubic_bezier_point(t: float, p0, p1, p2, p3) -> tuple[int, int]:
    """Punto en curva de Bézier cúbica para t ∈ [0, 1]."""
    u = 1 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return int(x), int(y)


def bezier_segments(start, end, segments: int = 12) -> list[tuple[int, int]]:
    """
    Genera puntos intermedios aproximando una curva cúbica entre start y end.
    Los puntos de control se desplazan aleatoriamente (no colineales) para
    evitar trayectorias rectilíneas.
    """
    mid_x = (start[0] + end[0]) // 2 + random.randint(-80, 80)
    mid_y = (start[1] + end[1]) // 2 + random.randint(-80, 80)
    p1 = (mid_x, mid_y)
    p2 = (mid_x + random.randint(-40, 40), mid_y + random.randint(-40, 40))
    return [cubic_bezier_point(i / segments, start, p1, p2, end)
            for i in range(1, segments + 1)]
