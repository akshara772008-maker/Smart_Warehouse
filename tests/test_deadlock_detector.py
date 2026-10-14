
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from os_modules.deadlock_detector import DeadlockDetector

detector = DeadlockDetector()

print("\n========== DEADLOCK DETECTION TEST ==========")

allocation = [
    [1, 0],
    [0, 1],
    [0, 0]
]

request = [
    [0, 1],
    [1, 0],
    [0, 0]
]

available = [0, 0]

result = detector.detect_deadlock(
    allocation,
    request,
    available,
    ["P1", "P2", "P3"]
)

print("Deadlock Detected:", result["deadlock_detected"])
print("Deadlocked Processes:", result["deadlocked_processes"])
print("Completed Sequence:", result["safe_sequence"])

assert result["deadlock_detected"] is True
assert set(result["deadlocked_processes"]) == {"P1", "P2"}


print("\nDEADLOCK DETECTION TEST PASSED")