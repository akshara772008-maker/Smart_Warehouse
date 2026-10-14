
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from os_modules.banker import Banker

banker = Banker()

print("\n========== BANKER'S ALGORITHM TEST ==========")

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

process_ids = ["P0", "P1", "P2", "P3", "P4"]

result = banker.check_safety(
    available,
    allocation,
    maximum,
    process_ids
)

print("System Safe:", result["safe"])
print("Safe Sequence:", result["safe_sequence"])
print("Need Matrix:", result["need"])

assert result["safe"] is True
assert len(result["safe_sequence"]) == 5

print("\nTESTING RESOURCE REQUEST")

request = [1, 0, 2]

request_result = banker.request_resources(
    1,
    request,
    available,
    allocation,
    maximum,
    process_ids
)

print("Request Granted:", request_result["granted"])
print("Message:", request_result["message"])

assert request_result["granted"] is True
assert available == [2, 3, 0]

print("\nBANKER'S ALGORITHM TEST PASSED")