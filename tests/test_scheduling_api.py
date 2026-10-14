
import unittest

if __name__ != "__main__":
    raise unittest.SkipTest("Manual live-server API check; run as a script.")

import requests

BASE_URL = "http://127.0.0.1:5000"

print("\n========== SCHEDULING API TEST ==========")

response = requests.post(
    f"{BASE_URL}/schedule",
    json={"algorithm": "FCFS"}
)

print("Status Code:", response.status_code)
assert response.status_code == 200

data = response.json()

assert data["success"] is True
assert data["algorithm"] == "FCFS"
assert "results" in data
assert "average_waiting_time" in data
assert "average_turnaround_time" in data

print("Algorithm:", data["algorithm"])
print("Results:", data["results"])
print("Average Waiting Time:", data["average_waiting_time"])
print("Average Turnaround Time:", data["average_turnaround_time"])

if data["results"]:
    expected_waiting = sum(
        process["waiting_time"] for process in data["results"]
    ) / len(data["results"])

    expected_turnaround = sum(
        process["turnaround_time"] for process in data["results"]
    ) / len(data["results"])

    assert abs(data["average_waiting_time"] - expected_waiting) < 0.001
    assert abs(data["average_turnaround_time"] - expected_turnaround) < 0.001

print("\nSCHEDULING API TEST PASSED")