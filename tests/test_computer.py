from PIL import Image
from qwencoder_cua.core.computer import Computer
from qwencoder_cua.models.capabilities import DriverCapabilities
from qwencoder_cua.models.window import WindowInfo


class FakeDriver:
    name = "fake"
    capabilities = DriverCapabilities(screenshot=True)

    def connect(self): pass
    def disconnect(self): pass
    def screenshot(self, output=None):
        image = Image.new("RGB", (100, 80))
        if output:
            image.save(output)
        return image
    def get_windows(self):
        return [WindowInfo(id="1", title="Test", is_active=True)]
    def get_active_window(self):
        return self.get_windows()[0]
    def focus_window(self, window_id): pass
    def click(self, x, y, button="left"): pass
    def move(self, x, y): pass
    def scroll(self, dx=0, dy=0): pass
    def type_text(self, text): pass
    def press_key(self, key): pass


def test_observe():
    with Computer(driver=FakeDriver()) as computer:
        obs = computer.observe()
        assert obs.platform == "fake"
        assert obs.screenshot.width == 100
        assert obs.active_window.title == "Test"


def test_requires_connection():
    computer = Computer(driver=FakeDriver())
    try:
        computer.windows()
        assert False, "Expected disconnected guard"
    except RuntimeError:
        pass
