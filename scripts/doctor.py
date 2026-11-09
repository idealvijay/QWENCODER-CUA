from qwencoder_cua.core.computer import Computer
from qwencoder_cua.core.registry import detect_linux_session
import platform

print("QWENCODER CUA environment diagnostic")
print("OS:", platform.platform())
if platform.system() == "Linux":
    print("Desktop session:", detect_linux_session())

try:
    with Computer() as computer:
        print("Driver:", computer.driver.name)
        print("Capabilities:", computer.driver.capabilities.model_dump())
        observation = computer.observe()
        print("Screenshot:", observation.screenshot)
        print("Windows found:", len(observation.windows))
except Exception as exc:
    print("Driver check failed:", type(exc).__name__, str(exc))
    raise SystemExit(1)
