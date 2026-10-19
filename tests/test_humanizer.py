from core.humanizer import gaussian_delay, organic_pause, cubic_bezier_point, bezier_segments


def test_gaussian_delay_non_negative():
    for _ in range(200):
        assert gaussian_delay(mu=0.0, sigma=0.1) >= 0.05


def test_organic_pause_audio_longer_than_video():
    v = [organic_pause("video") for _ in range(200)]
    a = [organic_pause("audio") for _ in range(200)]
    assert sum(a) / len(a) > sum(v) / len(v)


def test_bezier_endpoints_exact():
    p0, p3 = (0, 0), (100, 100)
    assert cubic_bezier_point(0, p0, (30, 40), (70, 60), p3) == p0
    assert cubic_bezier_point(1, p0, (30, 40), (70, 60), p3) == p3


def test_bezier_segments_non_colinear():
    pts = bezier_segments((0, 0), (200, 200), segments=10)
    # Al menos un punto debe desviarse de la línea recta y = x
    assert any(abs(x - y) > 1 for x, y in pts)
