import json
import sqlite3
import tempfile
import unittest
from contextlib import closing

import app as app_module
from os_modules.warehouse_engine import WarehouseEngine


class ResourceCapacityApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_engine = app_module.engine
        app_module.engine = WarehouseEngine()
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.engine = self.previous_engine

    def current_capacities(self):
        response = self.client.get("/resource_capacity")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def configure(self, **capacities):
        return self.client.put(
            "/resource_capacity",
            json={"resource_capacity": capacities}
        )

    def test_capacity_update_drives_available_claim_limits_and_banker(self):
        updated = self.configure(
            Worker=6,
            Forklift=3,
            Packing=4,
            Vehicle=3
        )
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()["total_resources"], {
            "Worker": 6,
            "Forklift": 3,
            "Packing": 4,
            "Vehicle": 3
        })
        self.assertEqual(updated.get_json()["resources"], {
            "Worker": 6,
            "Forklift": 3,
            "Packing": 4,
            "Vehicle": 3
        })

        created = self.client.post("/create_order", json={
            "process_id": "P_CAPACITY",
            "order_id": "O_CAPACITY",
            "arrival_time": 0,
            "burst_time": 2,
            "priority": 1,
            "resources": ["Worker"] * 6
        })
        self.assertEqual(created.status_code, 200, created.get_json())
        beyond_capacity = self.client.post("/create_order", json={
            "process_id": "P_TOO_MANY",
            "order_id": "O_TOO_MANY",
            "arrival_time": 0,
            "burst_time": 2,
            "priority": 1,
            "resources": ["Worker"] * 7
        })
        self.assertEqual(beyond_capacity.status_code, 400)

        allocated = self.client.post("/allocate", json={
            "process_id": "P_CAPACITY",
            "resources": ["Worker"] * 6
        })
        self.assertEqual(allocated.status_code, 200, allocated.get_json())
        self.assertEqual(
            allocated.get_json()["available_resources"]["Worker"],
            0
        )
        status = self.client.get("/status").get_json()
        self.assertEqual(status["total_resources"]["Worker"], 6)
        safety = self.client.post("/banker", json={})
        self.assertEqual(safety.status_code, 200, safety.get_json())
        self.assertTrue(safety.get_json()["safe"])
        self.assertEqual(
            safety.get_json()["maximum"]["P_CAPACITY"]["Worker"],
            6
        )
        self.assertEqual(
            safety.get_json()["allocation"]["P_CAPACITY"]["Worker"],
            6
        )

    def test_invalid_capacity_values_are_rejected_atomically(self):
        initial = self.current_capacities()
        invalid_updates = (
            {"Worker": 6, "Forklift": 3, "Packing": 4},
            {
                "Worker": 6,
                "Forklift": 3,
                "Packing": 4,
                "Vehicle": 3,
                "Unknown": 1
            },
            {
                "Worker": -1,
                "Forklift": 3,
                "Packing": 4,
                "Vehicle": 3
            },
            {
                "Worker": True,
                "Forklift": 3,
                "Packing": 4,
                "Vehicle": 3
            },
            {
                "Worker": 6,
                "Forklift": 2.5,
                "Packing": 4,
                "Vehicle": 3
            },
            {
                "Worker": 9007199254740992,
                "Forklift": 3,
                "Packing": 4,
                "Vehicle": 3
            }
        )
        for capacity in invalid_updates:
            with self.subTest(capacity=capacity):
                response = self.client.put(
                    "/resource_capacity",
                    json={"resource_capacity": capacity}
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["success"])
                self.assertEqual(
                    self.current_capacities()["total_resources"],
                    initial["total_resources"]
                )
                self.assertEqual(
                    self.current_capacities()["resources"],
                    initial["resources"]
                )

        invalid_body = self.client.put(
            "/resource_capacity",
            data="{",
            content_type="application/json"
        )
        self.assertEqual(invalid_body.status_code, 400)
        self.assertEqual(
            self.current_capacities()["total_resources"],
            initial["total_resources"]
        )

    def test_capacity_reduction_respects_allocations_and_maximum_claims(self):
        created = self.client.post("/create_order", json={
            "process_id": "P_CAPACITY_GUARD",
            "order_id": "O_CAPACITY_GUARD",
            "arrival_time": 0,
            "burst_time": 2,
            "priority": 1,
            "resources": ["Worker", "Worker"]
        })
        self.assertEqual(created.status_code, 200, created.get_json())
        allocated = self.client.post("/allocate", json={
            "process_id": "P_CAPACITY_GUARD",
            "resources": ["Worker"]
        })
        self.assertEqual(allocated.status_code, 200, allocated.get_json())
        before = self.current_capacities()

        below_allocation = self.configure(
            Worker=0,
            Forklift=2,
            Packing=3,
            Vehicle=2
        )
        self.assertEqual(below_allocation.status_code, 400)
        self.assertIn(
            "currently allocated",
            below_allocation.get_json()["message"]
        )

        with_claim_still_allocatable = self.configure(
            Worker=1,
            Forklift=2,
            Packing=3,
            Vehicle=2
        )
        self.assertEqual(with_claim_still_allocatable.status_code, 400)
        self.assertIn(
            "maximum claim",
            with_claim_still_allocatable.get_json()["message"]
        )
        after = self.current_capacities()
        self.assertEqual(after["total_resources"], before["total_resources"])
        self.assertEqual(after["resources"], before["resources"])
        self.assertEqual(
            self.client.get("/status").get_json()["processes"][0]
            ["allocated_resources"]["Worker"],
            1
        )

    def test_zero_capacity_is_valid_when_not_claimed_or_allocated(self):
        response = self.configure(
            Worker=0,
            Forklift=0,
            Packing=0,
            Vehicle=0
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["resources"], {
            "Worker": 0,
            "Forklift": 0,
            "Packing": 0,
            "Vehicle": 0
        })
        order = self.client.post("/create_order", json={
            "process_id": "P_ZERO",
            "order_id": "O_ZERO",
            "arrival_time": 0,
            "burst_time": 1,
            "priority": 1,
            "resources": ["Worker"]
        })
        self.assertEqual(order.status_code, 400)

    def test_configured_capacity_round_trips_with_existing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = f"{directory}\\warehouse.sqlite3"
            first = WarehouseEngine(state_path)
            configured = first.configure_resource_capacity({
                "Worker": 6,
                "Forklift": 3,
                "Packing": 4,
                "Vehicle": 3
            })
            self.assertEqual(
                configured["available_resources"]["Worker"],
                6
            )
            first.create_order(
                "P_CAPACITY_PERSIST",
                "O_CAPACITY_PERSIST",
                0,
                2,
                1,
                ["Worker"] * 6
            )
            first.allocate_resources(
                "P_CAPACITY_PERSIST",
                ["Worker", "Worker"]
            )

            restored = WarehouseEngine(state_path)
            self.assertEqual(
                restored.resource_manager.get_total_resources(),
                {
                    "Worker": 6,
                    "Forklift": 3,
                    "Packing": 4,
                    "Vehicle": 3
                }
            )
            self.assertEqual(
                restored.resource_manager.get_all_resources()["Worker"],
                4
            )
            self.assertEqual(
                restored.maximum_claims["P_CAPACITY_PERSIST"]["Worker"],
                6
            )

    def test_legacy_persisted_state_defaults_to_original_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = f"{directory}\\legacy.sqlite3"
            payload = {
                "processes": [],
                "available": {
                    "Worker": 5,
                    "Forklift": 2,
                    "Packing": 3,
                    "Vehicle": 2
                },
                "allocated": {},
                "pending_requests": {},
                "maximum_claims": {}
            }
            with closing(sqlite3.connect(state_path)) as connection:
                connection.execute(
                    "CREATE TABLE warehouse_state ("
                    "singleton_id INTEGER PRIMARY KEY, version INTEGER NOT NULL, "
                    "payload TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO warehouse_state VALUES (1, 1, ?)",
                    (json.dumps(payload),)
                )
                connection.commit()

            restored = WarehouseEngine(state_path)
            self.assertEqual(
                restored.resource_manager.get_total_resources(),
                {
                    "Worker": 5,
                    "Forklift": 2,
                    "Packing": 3,
                    "Vehicle": 2
                }
            )


if __name__ == "__main__":
    unittest.main()
