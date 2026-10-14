import socket
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO

import app as app_module
import network.client as tcp_client
import network.server as tcp_server
from network.server import handle_client
from os_modules.banker import Banker
from os_modules.deadlock_detector import DeadlockDetector
from os_modules.resource_manager import ResourceManager
from os_modules.warehouse_engine import WarehouseEngine


class FlaskApiRegressionTests(unittest.TestCase):
    def setUp(self):
        self.previous_engine = app_module.engine
        app_module.engine = WarehouseEngine()
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.engine = self.previous_engine

    def create_order(self, process_id, resources):
        return self.client.post("/create_order", json={
            "process_id": process_id,
            "order_id": f"O_{process_id}",
            "arrival_time": 0,
            "burst_time": 5,
            "priority": 1,
            "resources": resources
        })

    def test_unknown_resource_is_rejected_before_process_creation(self):
        response = self.create_order("P_BAD", ["Forklfit"])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])
        self.assertEqual(self.client.get("/status").get_json()["processes"], [])

    def test_order_validation_rejects_missing_duplicate_and_negative_priority(self):
        missing = self.client.post("/create_order", json={
            "process_id": "P_MISSING",
            "arrival_time": 0,
            "burst_time": 1,
            "priority": 1,
            "resources": []
        })
        self.assertEqual(missing.status_code, 400)

        created = self.create_order("P_DUPLICATE", [])
        self.assertEqual(created.status_code, 200)
        duplicate = self.client.post("/create_order", json={
            "process_id": "P_DUPLICATE",
            "order_id": "O_OTHER",
            "arrival_time": 0,
            "burst_time": 1,
            "priority": 1,
            "resources": []
        })
        self.assertEqual(duplicate.status_code, 409)

        invalid_priority = self.client.post("/create_order", json={
            "process_id": "P_NEGATIVE_PRIORITY",
            "order_id": "O_NEGATIVE_PRIORITY",
            "arrival_time": 0,
            "burst_time": 1,
            "priority": -1,
            "resources": []
        })
        self.assertEqual(invalid_priority.status_code, 400)
        self.assertEqual(
            [p["process_id"] for p in self.client.get("/status").get_json()["processes"]],
            ["P_DUPLICATE"]
        )

    def test_dashboard_read_routes_report_live_engine_state(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        created = self.create_order("P_STATE", ["Packing"])
        self.assertEqual(created.status_code, 200)

        status = self.client.get("/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["processes"][0]["process_id"], "P_STATE")
        self.assertEqual(status.get_json()["resources"]["Packing"], 3)

        system_status = self.client.get("/system_status")
        self.assertEqual(system_status.get_json()["total_processes"], 1)
        debug = self.client.get("/debug_resources").get_json()
        self.assertEqual(debug["available"]["Packing"], 3)
        self.assertEqual(debug["process_states"]["P_STATE"], "NEW")
        self.assertTrue(self.client.get("/deadlock").get_json()["success"])

    def test_allocation_and_release_are_idempotently_guarded(self):
        self.assertEqual(
            self.create_order("P1", ["Worker"]).status_code, 200
        )
        allocated = self.client.post("/allocate", json={
            "process_id": "P1",
            "resources": ["Worker"]
        })
        self.assertEqual(allocated.status_code, 200)
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            4
        )

        repeated = self.client.post("/allocate", json={
            "process_id": "P1",
            "resources": ["Worker"]
        })
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            4
        )

        released = self.client.post("/release", json={"process_id": "P1"})
        self.assertEqual(released.status_code, 200)
        repeated_release = self.client.post(
            "/release", json={"process_id": "P1"}
        )
        self.assertEqual(repeated_release.status_code, 409)
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            5
        )

    def test_exhausted_resource_does_not_corrupt_counts(self):
        for index in range(5):
            process_id = f"P{index}"
            self.assertEqual(
                self.create_order(process_id, ["Worker"]).status_code, 200
            )
            response = self.client.post("/allocate", json={
                "process_id": process_id,
                "resources": ["Worker"]
            })
            self.assertEqual(response.status_code, 200)

        self.assertEqual(
            self.create_order("P_EXTRA", ["Worker"]).status_code, 200
        )
        exhausted = self.client.post("/allocate", json={
            "process_id": "P_EXTRA",
            "resources": ["Worker"]
        })
        self.assertEqual(exhausted.status_code, 409)
        self.assertFalse(exhausted.get_json()["success"])
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            0
        )

    def test_multiple_resource_units_preserve_claim_and_allow_partial_release(self):
        created = self.create_order(
            "P_QUANTITY", ["Worker", "Worker"]
        )
        self.assertEqual(created.status_code, 200, created.get_json())
        status_process = self.client.get("/status").get_json()["processes"][0]
        self.assertEqual(status_process["maximum_claim"]["Worker"], 2)

        first = self.client.post("/allocate", json={
            "process_id": "P_QUANTITY",
            "resources": ["Worker"]
        })
        second = self.client.post("/allocate", json={
            "process_id": "P_QUANTITY",
            "resources": ["Worker"]
        })
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            3
        )
        allocated = self.client.get("/status").get_json()["processes"][0]
        self.assertEqual(allocated["allocated_resources"]["Worker"], 2)

        over_claim = self.client.post("/allocate", json={
            "process_id": "P_QUANTITY",
            "resources": ["Worker"]
        })
        self.assertEqual(over_claim.status_code, 409)
        self.assertIn("remaining maximum claim", over_claim.get_json()["message"])
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            3
        )

        released = self.client.post("/release", json={
            "process_id": "P_QUANTITY",
            "resource": "Worker",
            "quantity": 1
        })
        self.assertEqual(released.status_code, 200, released.get_json())
        self.assertEqual(len(released.get_json()["released_resources"]), 1)
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            4
        )
        release_too_many = self.client.post("/release", json={
            "process_id": "P_QUANTITY",
            "resource": "Worker",
            "quantity": 2
        })
        self.assertEqual(release_too_many.status_code, 409)
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            4
        )

    def test_global_shortage_is_atomic_and_retried_after_release(self):
        for index in range(5):
            process_id = f"P_GLOBAL_{index}"
            self.assertEqual(
                self.create_order(process_id, ["Worker"]).status_code, 200
            )
            self.assertEqual(
                self.client.post("/allocate", json={
                    "process_id": process_id,
                    "resources": ["Worker"]
                }).status_code,
                200
            )

        self.assertEqual(
            self.create_order(
                "P_RETRY_QUANTITY", ["Worker", "Worker"]
            ).status_code,
            200
        )
        failed = self.client.post("/allocate", json={
            "process_id": "P_RETRY_QUANTITY",
            "resources": ["Worker", "Worker"]
        })
        self.assertEqual(failed.status_code, 409)
        self.assertEqual(
            failed.get_json()["pending_requests"],
            ["Worker", "Worker"]
        )
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            0
        )

        self.assertEqual(
            self.client.post("/release", json={
                "process_id": "P_GLOBAL_0"
            }).status_code,
            200
        )
        still_short = self.client.post("/allocate", json={
            "process_id": "P_RETRY_QUANTITY",
            "resources": ["Worker", "Worker"]
        })
        self.assertEqual(still_short.status_code, 409)
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            1
        )

        self.assertEqual(
            self.client.post("/release", json={
                "process_id": "P_GLOBAL_1"
            }).status_code,
            200
        )
        retried = self.client.post("/allocate", json={
            "process_id": "P_RETRY_QUANTITY",
            "resources": ["Worker", "Worker"]
        })
        self.assertEqual(retried.status_code, 200, retried.get_json())
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            0
        )
        self.assertEqual(
            self.client.get("/status").get_json()["processes"][-1]
            ["allocated_resources"]["Worker"],
            2
        )

    def test_bankers_uses_quantity_maximum_and_calculates_need(self):
        self.assertEqual(
            self.create_order("P_BANKER_QUANTITY", ["Worker", "Worker"]).status_code,
            200
        )
        self.assertEqual(
            self.client.post("/allocate", json={
                "process_id": "P_BANKER_QUANTITY",
                "resources": ["Worker"]
            }).status_code,
            200
        )
        result = self.client.post("/banker", json={}).get_json()
        self.assertTrue(result["safe"])
        self.assertEqual(result["maximum"]["P_BANKER_QUANTITY"]["Worker"], 2)
        self.assertEqual(result["allocation"]["P_BANKER_QUANTITY"]["Worker"], 1)
        self.assertEqual(result["need_by_process"]["P_BANKER_QUANTITY"]["Worker"], 1)

    def test_completed_process_state_survives_schedule_and_monitor_checks(self):
        self.assertEqual(self.create_order("P_COMPLETED_PERSIST", []).status_code, 200)
        self.assertTrue(self.client.post(
            "/run_process", json={"process_id": "P_COMPLETED_PERSIST"}
        ).get_json()["success"])
        self.assertTrue(self.client.post(
            "/complete_process", json={"process_id": "P_COMPLETED_PERSIST"}
        ).get_json()["success"])

        scheduled = self.client.post("/schedule", json={
            "algorithm": "FCFS"
        })
        self.assertEqual(scheduled.status_code, 200, scheduled.get_json())
        self.client.post("/banker", json={})
        self.client.get("/deadlock")
        process = self.client.get("/status").get_json()["processes"][0]
        self.assertEqual(process["state"], "COMPLETED")
        self.assertEqual(process["completion_time"], 5)

    def test_persisted_state_round_trips_claims_allocations_and_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = f"{directory}\\warehouse.sqlite3"
            first = WarehouseEngine(state_path)
            first.create_order(
                "P_PERSIST",
                "O_PERSIST",
                0,
                2,
                1,
                ["Worker", "Worker"]
            )
            first.allocate_resources("P_PERSIST", ["Worker", "Worker"])
            restored = WarehouseEngine(state_path)
            self.assertEqual(
                restored.maximum_claims["P_PERSIST"]["Worker"], 2
            )
            self.assertEqual(
                restored.resource_manager.get_allocated_resources("P_PERSIST"),
                ["Worker", "Worker"]
            )
            self.assertEqual(
                restored.resource_manager.get_available("Worker"), 3
            )
            self.assertTrue(restored.run_process("P_PERSIST")["success"])
            self.assertTrue(restored.complete_process("P_PERSIST")["success"])

            after_restart = WarehouseEngine(state_path)
            self.assertEqual(
                after_restart.process_manager.get_process("P_PERSIST").state,
                "COMPLETED"
            )
            self.assertNotIn("P_PERSIST", after_restart.maximum_claims)
            self.assertEqual(
                after_restart.resource_manager.get_available("Worker"), 5
            )

    def test_all_resource_types_allocate_and_release_through_api(self):
        initial = {
            "Worker": 5,
            "Forklift": 2,
            "Packing": 3,
            "Vehicle": 2
        }

        for resource, count in initial.items():
            process_id = f"P_{resource}"
            self.assertEqual(
                self.create_order(process_id, [resource]).status_code,
                200
            )
            allocated = self.client.post("/allocate", json={
                "process_id": process_id,
                "resources": [resource]
            })
            self.assertEqual(allocated.status_code, 200, allocated.get_json())
            self.assertEqual(
                allocated.get_json()["available_resources"][resource],
                count - 1
            )

            released = self.client.post(
                "/release", json={"process_id": process_id}
            )
            self.assertEqual(released.status_code, 200, released.get_json())
            self.assertEqual(
                released.get_json()["available_resources"][resource],
                count
            )

        self.assertEqual(
            self.client.get("/resources").get_json()["resources"],
            initial
        )

    def test_allocation_and_release_validation_preserves_resource_counts(self):
        self.assertEqual(self.create_order("P_VALIDATE", ["Worker"]).status_code, 200)
        invalid_requests = (
            ({"process_id": "P_MISSING"}, 400),
            ({"process_id": "P_UNKNOWN", "resources": ["Worker"]}, 404),
            ({"process_id": "P_VALIDATE", "resources": []}, 400),
            ({"process_id": "P_VALIDATE", "resources": ["Forklfit"]}, 400),
            ({"process_id": "P_VALIDATE", "resources": ["Worker", "Worker"]}, 409),
            ({"process_id": "P_VALIDATE", "resources": ["Forklift"]}, 409)
        )
        for payload, expected_status in invalid_requests:
            response = self.client.post("/allocate", json=payload)
            self.assertEqual(
                response.status_code,
                expected_status,
                response.get_json()
            )

        missing_release_id = self.client.post("/release", json={})
        unknown_release_id = self.client.post(
            "/release", json={"process_id": "P_UNKNOWN"}
        )
        self.assertEqual(missing_release_id.status_code, 400)
        self.assertEqual(unknown_release_id.status_code, 404)
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"],
            {"Worker": 5, "Forklift": 2, "Packing": 3, "Vehicle": 2}
        )

    def test_run_stays_running_until_explicit_completion(self):
        self.assertEqual(
            self.create_order("P_RUN", ["Forklift"]).status_code, 200
        )
        started = self.client.post(
            "/run_process", json={"process_id": "P_RUN"}
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.get_json()["state"], "RUNNING")
        self.assertEqual(
            self.client.get("/status").get_json()["processes"][0]["state"],
            "RUNNING"
        )

        denied_release = self.client.post(
            "/release", json={"process_id": "P_RUN"}
        )
        self.assertEqual(denied_release.status_code, 409)
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Forklift"],
            1
        )

        completed = self.client.post(
            "/complete_process", json={"process_id": "P_RUN"}
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.get_json()["state"], "COMPLETED")
        repeated = self.client.post(
            "/complete_process", json={"process_id": "P_RUN"}
        )
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Forklift"],
            2
        )

    def test_running_process_does_not_auto_complete_and_new_process_cannot_complete(self):
        self.assertEqual(self.create_order("P_TIMEOUT", ["Worker"]).status_code, 200)
        not_running = self.client.post(
            "/complete_process", json={"process_id": "P_TIMEOUT"}
        )
        self.assertEqual(not_running.status_code, 409)

        started = self.client.post(
            "/run_process", json={"process_id": "P_TIMEOUT"}
        )
        self.assertEqual(started.status_code, 200)
        time.sleep(3.1)
        process = self.client.get("/status").get_json()["processes"][0]
        self.assertEqual(process["state"], "RUNNING")
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            4
        )

    def test_scheduling_algorithms_match_independent_expected_results(self):
        orders = (
            ("A", 0, 5, 4),
            ("B", 1, 4, 3),
            ("C", 2, 2, 1),
            ("D", 3, 1, 2)
        )
        for process_id, arrival, burst, priority in orders:
            response = self.client.post("/create_order", json={
                "process_id": process_id,
                "order_id": f"O{process_id}",
                "arrival_time": arrival,
                "burst_time": burst,
                "priority": priority,
                "resources": []
            })
            self.assertEqual(response.status_code, 200, response.get_json())

        expected = {
            "FCFS": [
                ("A", 5, 0, 5), ("B", 9, 4, 8),
                ("C", 11, 7, 9), ("D", 12, 8, 9)
            ],
            "SJF": [
                ("A", 5, 0, 5), ("D", 6, 2, 3),
                ("C", 8, 4, 6), ("B", 12, 7, 11)
            ],
            "PRIORITY": [
                ("A", 5, 0, 5), ("C", 7, 3, 5),
                ("D", 8, 4, 5), ("B", 12, 7, 11)
            ],
            "RR": [
                ("C", 6, 2, 4), ("D", 9, 5, 6),
                ("B", 11, 6, 10), ("A", 12, 7, 12)
            ]
        }

        for algorithm, rows in expected.items():
            response = self.client.post("/schedule", json={
                "algorithm": algorithm,
                "time_quantum": 2
            })
            self.assertEqual(response.status_code, 200, response.get_json())
            data = response.get_json()
            actual = [
                (
                    process["process_id"],
                    process["completion_time"],
                    process["waiting_time"],
                    process["turnaround_time"]
                )
                for process in data["results"]
            ]
            self.assertEqual(actual, rows, algorithm)
            self.assertAlmostEqual(
                data["average_waiting_time"],
                sum(row[2] for row in rows) / len(rows),
                msg=algorithm
            )
            self.assertAlmostEqual(
                data["average_turnaround_time"],
                sum(row[3] for row in rows) / len(rows),
                msg=algorithm
            )

    def test_equal_arrival_scheduler_ties_are_deterministic(self):
        for process_id in ("P_B", "P_A"):
            response = self.client.post("/create_order", json={
                "process_id": process_id,
                "order_id": f"O{process_id}",
                "arrival_time": 0,
                "burst_time": 2,
                "priority": 1,
                "resources": []
            })
            self.assertEqual(response.status_code, 200)

        for algorithm in ("FCFS", "SJF", "PRIORITY", "RR"):
            response = self.client.post("/schedule", json={
                "algorithm": algorithm,
                "time_quantum": 1
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                [p["process_id"] for p in response.get_json()["results"]],
                ["P_A", "P_B"]
            )

    def test_round_robin_uses_submitted_time_quantum(self):
        self.assertEqual(self.create_order("A", []).status_code, 200)
        self.assertEqual(self.create_order("B", []).status_code, 200)
        # The test fixture uses short bursts for easily checked completion times.
        app_module.engine.process_manager.get_process("A").burst_time = 5
        app_module.engine.process_manager.get_process("B").burst_time = 1

        quantum_one = self.client.post("/schedule", json={
            "algorithm": "RR",
            "time_quantum": 1
        })
        quantum_two = self.client.post("/schedule", json={
            "algorithm": "RR",
            "time_quantum": 2
        })
        self.assertEqual(quantum_one.status_code, 200)
        self.assertEqual(quantum_two.status_code, 200)
        completion_one = {
            process["process_id"]: process["completion_time"]
            for process in quantum_one.get_json()["results"]
        }
        completion_two = {
            process["process_id"]: process["completion_time"]
            for process in quantum_two.get_json()["results"]
        }
        self.assertEqual(completion_one["B"], 2)
        self.assertEqual(completion_two["B"], 3)

    def test_bad_json_and_scheduling_inputs_return_json_errors(self):
        malformed = self.client.post(
            "/schedule", data="{", content_type="application/json"
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertFalse(malformed.get_json()["success"])

        bad_algorithm = self.client.post(
            "/schedule", json={"algorithm": 1}
        )
        self.assertEqual(bad_algorithm.status_code, 400)
        self.assertFalse(bad_algorithm.get_json()["success"])

        bad_quantum = self.client.post("/schedule", json={
            "algorithm": "RR",
            "time_quantum": 0
        })
        self.assertEqual(bad_quantum.status_code, 400)
        self.assertFalse(bad_quantum.get_json()["success"])

    def test_banker_api_rejects_supplied_safety_matrices(self):
        response = self.client.post("/banker", json={
            "available": [3, 3, 2],
            "maximum": {
                "P1": [7, 5, 3],
                "P2": [3, 2, 2],
                "P3": [9, 0, 2],
                "P4": [2, 2, 2],
                "P5": [4, 3, 3]
            },
            "allocation": {
                "P1": [0, 1, 0],
                "P2": [2, 0, 0],
                "P3": [3, 0, 2],
                "P4": [2, 1, 1],
                "P5": [0, 0, 2]
            }
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])
        self.assertIn("live warehouse state", response.get_json()["message"])

    def test_banker_api_without_body_checks_current_warehouse(self):
        response = self.client.post("/banker")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["safe"])

    def test_created_order_claims_support_current_warehouse_safety_check(self):
        self.assertEqual(self.create_order("P_CLAIMED", ["Worker"]).status_code, 200)

        response = self.client.post("/banker")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["safe"])
        self.assertEqual(response.get_json()["safe_sequence"], ["P_CLAIMED"])

    def test_banker_current_state_ignores_completed_processes(self):
        self.assertEqual(self.create_order("P_COMPLETED", ["Worker"]).status_code, 200)
        self.assertEqual(
            self.client.post(
                "/run_process", json={"process_id": "P_COMPLETED"}
            ).status_code,
            200
        )
        self.assertEqual(
            self.client.post(
                "/complete_process", json={"process_id": "P_COMPLETED"}
            ).status_code,
            200
        )

        response = self.client.post("/banker")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["safe"])
        self.assertEqual(response.get_json()["safe_sequence"], [])

    def test_banker_api_reports_missing_current_claim_as_failure(self):
        self.assertEqual(self.create_order("P_NO_CLAIM", ["Worker"]).status_code, 200)
        app_module.engine.maximum_claims.pop("P_NO_CLAIM")

        response = self.client.post("/banker")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])
        self.assertIn("Maximum claim", response.get_json()["message"])

    def test_resource_claim_limit_uses_total_capacity(self):
        engine = app_module.engine
        for process_id in ("P1", "P2"):
            self.assertEqual(
                self.create_order(process_id, ["Worker"]).status_code, 200
            )
            self.assertTrue(
                engine.allocate_resources(process_id, ["Worker"])["success"]
            )

        claim = engine.set_maximum_claim("P1", {"Worker": 5})
        self.assertEqual(claim["Worker"], 5)

    def test_waiting_resource_requests_are_visible_to_deadlock_detection(self):
        process_ids = ["P1", "P3", "P4", "P5", "P6", "P2", "P7"]
        for process_id in process_ids:
            self.assertEqual(
                self.create_order(process_id, ["Worker", "Forklift"]).status_code,
                200
            )

        engine = app_module.engine
        for process_id in ("P1", "P3", "P4", "P5", "P6"):
            self.assertTrue(
                engine.resource_manager.request_resource(process_id, "Worker")
            )
        for process_id in ("P2", "P7"):
            self.assertTrue(
                engine.resource_manager.request_resource(process_id, "Forklift")
            )

        for process_id in ("P1", "P3", "P4", "P5", "P6", "P2", "P7"):
            result = engine.run_process(process_id)
            self.assertFalse(result["success"])
            self.assertEqual(result["state"], "WAITING")

        deadlock = self.client.get("/deadlock").get_json()
        self.assertTrue(deadlock["deadlock_detected"])
        self.assertEqual(
            set(deadlock["deadlocked_processes"]), set(process_ids)
        )


class OperatingSystemModuleRegressionTests(unittest.TestCase):
    def test_every_supported_resource_can_be_allocated_and_released(self):
        expected = {
            "Worker": 5,
            "Forklift": 2,
            "Packing": 3,
            "Vehicle": 2
        }
        manager = ResourceManager()
        self.assertEqual(manager.get_all_resources(), expected)

        for resource in expected:
            process_id = f"P_{resource}"
            self.assertTrue(manager.request_resource(process_id, resource))
            self.assertEqual(
                manager.get_available(resource),
                expected[resource] - 1
            )
            self.assertTrue(manager.release_all(process_id))
            self.assertEqual(
                manager.get_available(resource),
                expected[resource]
            )

    def test_concurrent_allocations_never_exceed_available_capacity(self):
        manager = ResourceManager()
        outcomes = []
        outcome_lock = threading.Lock()

        def request_worker():
            result = manager.request_resource("P", "Worker")
            with outcome_lock:
                outcomes.append(result)

        threads = [
            threading.Thread(target=request_worker)
            for _ in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sum(outcomes), 5)
        self.assertEqual(manager.get_available("Worker"), 0)
        self.assertEqual(len(manager.get_allocated_resources("P")), 5)
        self.assertTrue(manager.release_all("P"))
        self.assertEqual(manager.get_available("Worker"), 5)
        self.assertFalse(manager.release_all("P"))
        self.assertEqual(manager.get_available("Worker"), 5)

    def test_banker_and_deadlock_reject_invalid_resource_counts(self):
        with self.assertRaises(ValueError):
            Banker().check_safety([True], [[0]], [[1]])
        with self.assertRaises(ValueError):
            Banker().request_resources(
                -1, [0], [1], [[0]], [[1]]
            )
        with self.assertRaises(ValueError):
            DeadlockDetector().detect_deadlock(
                [[-1]], [[0]], [0], ["P1"]
            )

    def test_banker_unsafe_request_is_denied_without_mutating_inputs(self):
        available = [3, 3, 2]
        allocation = [
            [0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [0, 0, 2]
        ]
        maximum = [
            [7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]
        ]
        original = (
            available.copy(),
            [row.copy() for row in allocation],
            [row.copy() for row in maximum]
        )
        banker = Banker()

        unsafe_system = banker.check_safety([0], [[1]], [[2]], ["P"])
        self.assertFalse(unsafe_system["safe"])
        self.assertEqual(unsafe_system["unfinished_processes"], ["P"])

        result = banker.request_resources(
            0, [0, 0, 2], available, allocation, maximum,
            ["P0", "P1", "P2", "P3", "P4"]
        )
        self.assertFalse(result["granted"])
        self.assertIn("unsafe state", result["message"])
        self.assertEqual(available, original[0])
        self.assertEqual(allocation, original[1])
        self.assertEqual(maximum, original[2])

    def test_deadlock_detector_finds_no_deadlock_and_rejects_bad_dimensions(self):
        detector = DeadlockDetector()
        result = detector.detect_deadlock(
            [[1, 0], [0, 1]],
            [[0, 0], [0, 0]],
            [0, 0],
            ["P1", "P2"]
        )
        self.assertFalse(result["deadlock_detected"])
        self.assertEqual(set(result["safe_sequence"]), {"P1", "P2"})

        with self.assertRaises(ValueError):
            detector.detect_deadlock([[1, 0]], [[0]], [0, 0], ["P1"])
        with self.assertRaises(ValueError):
            detector.detect_deadlock([[1, 0]], [[0, 0]], [0, 0], [])

    def test_tcp_server_replies_to_valid_and_invalid_requests(self):
        for payload, expected in (
            (b"Order O1\n", b"Order received by warehouse server: Order O1"),
            (b"\xff\n", b"Request must be valid UTF-8"),
            (b"\n", b"Request cannot be empty"),
            (b"X" * 4097, b"Request is too large")
        ):
            client_socket, server_socket = socket.socketpair()

            def serve():
                with server_socket:
                    handle_client(server_socket, ("local", 0))

            thread = threading.Thread(target=serve)
            thread.start()
            with client_socket:
                client_socket.sendall(payload)
                client_socket.shutdown(socket.SHUT_WR)
                response = bytearray()
                while True:
                    chunk = client_socket.recv(1024)
                    if not chunk:
                        break
                    response.extend(chunk)
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(bytes(response), expected)

    def test_tcp_server_reports_port_conflict_and_request_timeout(self):
        reserved = socket.socket()
        reserved.bind(("127.0.0.1", 0))
        previous_host, previous_port = tcp_server.HOST, tcp_server.PORT
        tcp_server.HOST, tcp_server.PORT = reserved.getsockname()
        try:
            output = StringIO()
            with redirect_stdout(output):
                self.assertFalse(tcp_server.start_server())
            self.assertIn("Could not start the warehouse server", output.getvalue())
        finally:
            tcp_server.HOST, tcp_server.PORT = previous_host, previous_port
            reserved.close()

        client_socket, server_socket = socket.socketpair()

        def wait_for_request():
            with server_socket:
                handle_client(server_socket, ("local", 0))

        thread = threading.Thread(target=wait_for_request)
        thread.start()
        try:
            client_socket.settimeout(7)
            response = bytearray()
            while True:
                chunk = client_socket.recv(1024)
                if not chunk:
                    break
                response.extend(chunk)
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(bytes(response), b"Request timed out")
        finally:
            client_socket.close()
            server_socket.close()
            thread.join(timeout=2)

    def test_tcp_client_times_out_when_server_does_not_reply(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        host, port = listener.getsockname()
        previous_host, previous_port = tcp_client.HOST, tcp_client.PORT
        server_errors = []

        def accept_without_reply():
            try:
                connection, _ = listener.accept()
                with connection:
                    while connection.recv(1024):
                        pass
                    time.sleep(5.2)
            except OSError as error:
                server_errors.append(error)
            finally:
                listener.close()

        thread = threading.Thread(target=accept_without_reply)
        thread.start()
        try:
            tcp_client.HOST, tcp_client.PORT = host, port
            output = StringIO()
            with redirect_stdout(output):
                self.assertFalse(tcp_client.send_order("Order O_TIMEOUT"))
            self.assertIn("Could not communicate", output.getvalue())
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            self.assertFalse(server_errors)
        finally:
            tcp_client.HOST, tcp_client.PORT = previous_host, previous_port
            listener.close()
            if thread.is_alive():
                thread.join(timeout=1)

    def test_tcp_server_cleans_up_after_client_disconnect(self):
        client_socket, server_socket = socket.socketpair()

        def serve_disconnected_client():
            with server_socket:
                handle_client(server_socket, ("local", 0))

        thread = threading.Thread(target=serve_disconnected_client)
        thread.start()
        client_socket.close()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_tcp_client_integrates_with_handler_and_reports_refused_connection(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        host, port = listener.getsockname()
        previous_host, previous_port = tcp_client.HOST, tcp_client.PORT
        server_errors = []

        def serve_one_client():
            try:
                connection, address = listener.accept()
                with connection:
                    handle_client(connection, address)
            except OSError as error:
                server_errors.append(error)
            finally:
                listener.close()

        thread = threading.Thread(target=serve_one_client)
        thread.start()
        try:
            tcp_client.HOST, tcp_client.PORT = host, port
            output = StringIO()
            with redirect_stdout(output):
                self.assertTrue(tcp_client.send_order("Order O_TEST"))
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertFalse(server_errors)
            self.assertIn(
                "Order received by warehouse server: Order O_TEST",
                output.getvalue()
            )
        finally:
            tcp_client.HOST, tcp_client.PORT = previous_host, previous_port
            listener.close()
            if thread.is_alive():
                thread.join(timeout=2)

        unavailable = socket.socket()
        unavailable.bind(("127.0.0.1", 0))
        unavailable_port = unavailable.getsockname()[1]
        unavailable.close()
        tcp_client.HOST, tcp_client.PORT = "127.0.0.1", unavailable_port
        try:
            output = StringIO()
            with redirect_stdout(output):
                self.assertFalse(tcp_client.send_order("Order O_TEST"))
            self.assertIn("Could not communicate", output.getvalue())
        finally:
            tcp_client.HOST, tcp_client.PORT = previous_host, previous_port

        output = StringIO()
        with redirect_stdout(output):
            self.assertFalse(tcp_client.send_order("X" * 5000))
        self.assertIn("4096 UTF-8 bytes", output.getvalue())


if __name__ == "__main__":
    unittest.main()
