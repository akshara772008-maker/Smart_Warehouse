
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from os_modules.warehouse_engine import WarehouseEngine

print("\n========== WAREHOUSE ENGINE INTEGRATION TEST ==========")

engine = WarehouseEngine()

process = engine.create_order(
    "P901",
    "O901",
    0,
    5,
    1,
    ["Forklift"]
)

print("Initial State:", process.state)
assert process.state == "NEW"

result = engine.run_process("P901")

print("Process Started Successfully:", result)
print("Final State:", process.state)
print("Available Resources:", engine.resource_manager.get_all_resources())

assert result["success"] is True
assert result["state"] == "RUNNING"
assert process.state == "RUNNING"
assert engine.resource_manager.get_all_resources()["Forklift"] == 1

completion = engine.complete_process("P901")
assert completion["success"] is True
assert process.state == "COMPLETED"
assert engine.resource_manager.get_all_resources()["Forklift"] == 2

second_completion = engine.complete_process("P901")
assert second_completion["success"] is False
assert engine.resource_manager.get_all_resources()["Forklift"] == 2

print("\nWAREHOUSE ENGINE INTEGRATION TEST PASSED")