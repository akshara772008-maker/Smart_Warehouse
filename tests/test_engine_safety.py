
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from os_modules.warehouse_engine import WarehouseEngine

engine = WarehouseEngine()

available = [3, 3, 2]

allocation = [
    [0, 1, 0],
    [2, 0, 0],
    [3, 0, 2],
    [2, 1, 1],
    [0, 0, 2]
]

maximum = [
    [7, 5, 3],
    [3, 2, 2],
    [9, 0, 2],
    [2, 2, 2],
    [4, 3, 3]
]

print("\n========== ENGINE SAFETY TEST ==========")

result = engine.check_safe_state(available, allocation, maximum)

print("System Safe:", result["safe"])
print("Safe Sequence:", result["safe_sequence"])
print("Need Matrix:", result["need"])

assert result["safe"] is True
assert len(result["safe_sequence"]) == 5
assert result["need"][0] == [7, 4, 3]

print("\nENGINE SAFETY TEST PASSED")