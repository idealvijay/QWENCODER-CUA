from PIL import Image

from qwencoder_cua.drivers.linux.wayland.backend import WaylandPortalDriver
from qwencoder_cua.execution.verifier import verify_observation
from qwencoder_cua.models.observation import Observation, ScreenshotRef


def test_wayland_keysym_mapping():
    assert WaylandPortalDriver._keysym("enter") == 0xFF0D
    assert WaylandPortalDriver._keysym("a") == ord("a")
    assert WaylandPortalDriver._keysym("é") == 0x01000000 | ord("é")


def test_wayland_driver_does_not_advertise_unapproved_controls():
    driver = WaylandPortalDriver()
    assert not driver.capabilities.screenshot
    assert not driver.capabilities.mouse_input
    assert not driver.capabilities.keyboard_input


def test_screen_change_postcondition_uses_before_and_after_images(tmp_path):
    before_path = tmp_path / "before.png"
    after_path = tmp_path / "after.png"
    Image.new("RGB", (64, 64), "black").save(before_path)
    Image.new("RGB", (64, 64), "white").save(after_path)
    observation = Observation(
        observation_id="o", platform="test",
        screenshot=ScreenshotRef(path=str(after_path), width=64, height=64),
    )
    verified, message = verify_observation(
        observation,
        {"screen_changed": {"min_fraction": 0.5}},
        previous_screenshot_path=str(before_path),
    )
    assert verified
    assert "Changed pixels" in message
