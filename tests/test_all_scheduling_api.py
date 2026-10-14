
import unittest

if __name__ != "__main__":
    raise unittest.SkipTest("Manual live-server API check; run as a script.")

import time
import requests

BASE_URL = "http://127.0.0.1:5000"

suffix = str(time.time_ns())
base_arrival = int(time.time())

test_orders = [
    {
        "process_id": f"PA{suffix}",
        "order_id": f"OA{suffix}",
        "arrival_time": base_arrival,
        "burst_time": 5,
        "priority": 2,
        "resources": []
    },
    {
        "process_id": f"PB{suffix}",
        "order_id": f"OB{suffix}",
        "arrival_time": base_arrival + 1,
        "burst_time": 3,
        "priority": 1,
        "resources": []
    },
    {
        "process_id": f"PC{suffix}",
        "order_id": f"OC{suffix}",
        "arrival_time": base_arrival + 2,
        "burst_time": 2,
        "priority": 3,
        "resources": []
    }
]

print("\n========== ALL SCHEDULING API TESTS ==========")

for order in test_orders:
    response = requests.post(
        f"{BASE_URL}/create_order",
        json=order
    )
    print("Create order:", order["process_id"], response.status_code)
    assert response.status_code == 200, response.text

algorithms = ["FCFS", "SJF", "PRIORITY", "RR"]

for algorithm in algorithms:
    response = requests.post(
        f"{BASE_URL}/schedule",
        json={"algorithm": algorithm}
    )

    print(f"\n--- {algorithm} ---")
    print("Status Code:", response.status_code)
    assert response.status_code == 200, response.text

    data = response.json()
    print("Success:", data.get("success"))
    print("Average Waiting Time:", data.get("average_waiting_time"))
    print("Average Turnaround Time:", data.get("average_turnaround_time"))

    results = data.get("results", [])
    assert data.get("success") is True
    assert len(results) >= 3

    assert all(
        "waiting_time" in process
        and "turnaround_time" in process
        and "completion_time" in process
        for process in results
    )

    expected_waiting = sum(
        process["waiting_time"] for process in results
    ) / len(results)

    expected_turnaround = sum(
        process["turnaround_time"] for process in results
    ) / len(results)

    assert abs(data["average_waiting_time"] - expected_waiting) < 0.001
    assert abs(data["average_turnaround_time"] - expected_turnaround) < 0.001

    print("RESULT: PASSED")

print("\nALL FOUR SCHEDULING API TESTS PASSED")