
import unittest

if __name__ != "__main__":
    raise unittest.SkipTest("Manual live-server API check; run as a script.")

import requests

BASE_URL = "http://127.0.0.1:5000"

print("\n========== PROCESS API TESTS ==========")

process_id = "P301"
order_id = "O301"

response = requests.post(
    f"{BASE_URL}/create_order",
    json={
        "process_id": process_id,
        "order_id": order_id,
        "arrival_time": 0,
        "burst_time": 5,
        "priority": 1,
        "resources": []
    }
)

print("\nTEST 1: Create Warehouse Order")
print("Status:", response.status_code)
print("Response:", response.text)
assert response.status_code == 200

response = requests.get(f"{BASE_URL}/status")
print("\nTEST 2: Check System Status")
print("Status:", response.status_code)
assert response.status_code == 200
print("PASSED")

response = requests.post(
    f"{BASE_URL}/create_order",
    json={
        "process_id": process_id,
        "order_id": "O302",
        "arrival_time": 0,
        "burst_time": 4,
        "priority": 2,
        "resources": []
    }
)

print("\nTEST 3: Reject Duplicate Process ID")
print("Status:", response.status_code)
print("Response:", response.text)

print("\n========== TESTS COMPLETED ==========")