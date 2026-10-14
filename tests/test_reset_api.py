import tempfile
import unittest
from pathlib import Path

import app as app_module
from os_modules.warehouse_engine import WarehouseEngine


DEFAULT_CAPACITY = {
    "Worker": 5,
    "Forklift": 2,
    "Packing": 3,
    "Vehicle": 2
}


class WarehouseResetApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_engine = app_module.engine
        self.temp_directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_directory.name) / "warehouse.sqlite3"
        app_module.engine = WarehouseEngine(self.state_path)
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.engine = self.previous_engine
        self.temp_directory.cleanup()

    def create_order(self, process_id, resource="Worker"):
        return self.client.post("/create_order", json={
            "process_id": process_id,
            "order_id": f"O_{process_id}",
            "arrival_time": 0,
            "burst_time": 5,
            "priority": 1,
            "resources": [resource]
        })

    def test_reset_clears_persisted_warehouse_state_and_restores_dashboard(self):
        custom_capacity = {
            "Worker": 5,
            "Forklift": 6,
            "Packing": 7,
            "Vehicle": 4
        }
        configured = self.client.put(
            "/resource_capacity",
            json={"resource_capacity": custom_capacity}
        )
        self.assertEqual(configured.status_code, 200, configured.get_json())

        process_ids = [
            "P101", "P102", "P103", "P104", "P105", "P106"
        ]
        for process_id in process_ids:
            created = self.create_order(process_id)
            self.assertEqual(created.status_code, 200, created.get_json())

        scheduled = self.client.post("/schedule", json={"algorithm": "FCFS"})
        self.assertEqual(scheduled.status_code, 200, scheduled.get_json())
        self.assertEqual(len(scheduled.get_json()["results"]), len(process_ids))
        self.assertNotEqual(
            self.client.get("/status").get_json()["processes"][0]
            ["completion_time"],
            0
        )

        for process_id in process_ids[:5]:
            allocated = self.client.post("/allocate", json={
                "process_id": process_id,
                "resources": ["Worker"]
            })
            self.assertEqual(allocated.status_code, 200, allocated.get_json())

        waiting = self.client.post("/allocate", json={
            "process_id": "P106",
            "resources": ["Worker"]
        })
        self.assertEqual(waiting.status_code, 409, waiting.get_json())
        self.assertEqual(
            waiting.get_json()["pending_requests"], ["Worker"]
        )
        self.assertTrue(self.client.post("/banker", json={}).get_json()["safe"])
        self.assertEqual(
            len(self.client.get("/deadlock").get_json()["processes"]),
            len(process_ids)
        )

        reset = self.client.post("/reset", json={})
        self.assertEqual(reset.status_code, 200, reset.get_json())
        reset_data = reset.get_json()
        self.assertEqual(reset_data["process_count"], 0)
        self.assertEqual(reset_data["resources"], DEFAULT_CAPACITY)
        self.assertEqual(reset_data["total_resources"], DEFAULT_CAPACITY)

        status = self.client.get("/status").get_json()
        self.assertEqual(status["processes"], [])
        self.assertEqual(status["resources"], DEFAULT_CAPACITY)
        self.assertEqual(status["total_resources"], DEFAULT_CAPACITY)
        self.assertEqual(self.client.get("/system_status").get_json()["total_processes"], 0)
        self.assertEqual(
            self.client.get("/debug_resources").get_json()["allocated"],
            {}
        )
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"],
            DEFAULT_CAPACITY
        )

        empty_schedule = self.client.post(
            "/schedule", json={"algorithm": "FCFS"}
        ).get_json()
        self.assertEqual(empty_schedule["results"], [])
        self.assertEqual(empty_schedule["average_waiting_time"], 0)
        self.assertEqual(empty_schedule["average_turnaround_time"], 0)

        banker = self.client.post("/banker", json={}).get_json()
        self.assertTrue(banker["safe"])
        self.assertEqual(banker["processes"], [])
        deadlock = self.client.get("/deadlock").get_json()
        self.assertEqual(deadlock["processes"], [])
        self.assertEqual(deadlock["deadlocked_processes"], [])

        app_module.engine = WarehouseEngine(self.state_path)
        restarted_status = self.client.get("/status").get_json()
        self.assertEqual(restarted_status["processes"], [])
        self.assertEqual(restarted_status["resources"], DEFAULT_CAPACITY)
        self.assertEqual(
            app_module.engine.resource_manager.allocated,
            {}
        )
        self.assertEqual(
            app_module.engine.resource_manager.pending_requests,
            {}
        )
        self.assertEqual(app_module.engine.maximum_claims, {})

        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/status").get_json()["processes"], [])

    def test_dashboard_refresh_does_not_reset_existing_processes(self):
        created = self.create_order("P101")
        self.assertEqual(created.status_code, 200, created.get_json())

        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(
            [
                process["process_id"]
                for process in self.client.get("/status").get_json()["processes"]
            ],
            ["P101"]
        )

        restored = WarehouseEngine(self.state_path)
        self.assertEqual(
            [
                process.process_id
                for process in restored.process_manager.get_all_processes()
            ],
            ["P101"]
        )

    def test_reset_is_rejected_while_a_process_is_running(self):
        created = self.create_order("P_RUNNING")
        self.assertEqual(created.status_code, 200, created.get_json())
        started = self.client.post(
            "/run_process", json={"process_id": "P_RUNNING"}
        )
        self.assertEqual(started.status_code, 200, started.get_json())

        reset = self.client.post("/reset", json={})
        self.assertEqual(reset.status_code, 409, reset.get_json())
        self.assertIn("processes are running", reset.get_json()["message"])

        process = self.client.get("/status").get_json()["processes"][0]
        self.assertEqual(process["process_id"], "P_RUNNING")
        self.assertEqual(process["state"], "RUNNING")
        self.assertEqual(
            self.client.get("/resources").get_json()["resources"]["Worker"],
            4
        )


if __name__ == "__main__":
    unittest.main()
