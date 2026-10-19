from unittest.mock import patch
from core.orchestrator import OrchestratorEngine
from core.humanizer import HumanizeConfig


def test_visual_precheck_empty_frame_fails():
    with patch("core.orchestrator.adb_screencap", return_value=b""):
        assert OrchestratorEngine("emu-1").visual_precheck() is False


def test_visual_precheck_ok():
    with patch("core.orchestrator.adb_screencap", return_value=b"x" * 5000):
        assert OrchestratorEngine("emu-1").visual_precheck() is True


def test_execute_action_aborts_when_precheck_fails():
    with patch("core.orchestrator.adb_screencap", return_value=b""), \
         patch("core.orchestrator.adb_tap") as tap:
        OrchestratorEngine("emu-1").execute_action("tap", {"x": 10, "y": 10})
        tap.assert_not_called()


def test_tap_calls_adb_when_precheck_ok():
    with patch("core.orchestrator.adb_screencap", return_value=b"x" * 5000), \
         patch("core.orchestrator.adb_tap") as tap:
        OrchestratorEngine("emu-1", HumanizeConfig(humanize=False)).execute_action(
            "tap", {"x": 10, "y": 20}
        )
        tap.assert_called_once_with("emu-1", 10, 20)
