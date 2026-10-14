

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from os_modules.process_manager import ProcessManager

manager = ProcessManager()

print("\n========== PROCESS MANAGER TESTS ==========")

process = manager.create_process("P201", "O201", 0, 5, 2, ["Worker"])
assert process.state == "NEW"
print("TEST 1: Create process - PASSED")

try:
    manager.create_process("P201", "O202", 0, 4, 1, [])
    raise AssertionError("Duplicate ID was accepted")
except ValueError:
    print("TEST 2: Reject duplicate process ID - PASSED")

assert manager.update_state("P201", "READY")
assert manager.update_state("P201", "RUNNING")
assert manager.update_state("P201", "COMPLETED")
print("TEST 3: Valid state transitions - PASSED")

assert manager.update_state("P201", "RUNNING") is False
print("TEST 4: Reject transition from COMPLETED to RUNNING - PASSED")

assert manager.update_state("P999", "RUNNING") is False
print("TEST 5: Reject update for missing process - PASSED")

try:
    manager.create_process("P202", "O202", 0, 0, 1, [])
    raise AssertionError("Zero burst time was accepted")
except ValueError:
    print("TEST 6: Reject zero burst time - PASSED")

assert manager.remove_process("P201")
assert manager.get_process("P201") is None
print("TEST 7: Remove process - PASSED")

print("\nALL TESTS PASSED")