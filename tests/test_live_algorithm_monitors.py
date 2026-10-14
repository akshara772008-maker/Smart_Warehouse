import unittest

import app as app_module
from os_modules.warehouse_engine import WarehouseEngine


class LiveAlgorithmMonitorApiTests(unittest.TestCase):
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
            "burst_time": 4,
            "priority": 1,
            "resources": resources
        })

    def test_monitors_use_only_live_state_and_include_process_metadata(self):
        created = self.create_order("P_LIVE", ["Worker"])
        self.assertEqual(created.status_code, 200)

        banker = self.client.post("/banker", json={})
        self.assertEqual(banker.status_code, 200)
        banker_data = banker.get_json()
        self.assertTrue(banker_data["safe"])
        self.assertEqual(banker_data["processes"], [{
            "process_id": "P_LIVE",
            "order_id": "O_P_LIVE",
            "state": "NEW"
        }])
        self.assertEqual(banker_data["allocation"]["P_LIVE"]["Worker"], 0)
        self.assertEqual(banker_data["maximum"]["P_LIVE"]["Worker"], 1)

        deadlock = self.client.get("/deadlock")
        self.assertEqual(deadlock.status_code, 200)
        deadlock_data = deadlock.get_json()
        self.assertEqual(deadlock_data["status"], "NO DEADLOCK")
        self.assertEqual(deadlock_data["processes"][0]["process_id"], "P_LIVE")
        self.assertEqual(deadlock_data["processes"][0]["order_id"], "O_P_LIVE")

        supplied_state = self.client.post("/banker", json={
            "available": [0],
            "allocation": {"P_FAKE": [1]},
            "maximum": {"P_FAKE": [1]}
        })
        self.assertEqual(supplied_state.status_code, 400)
        self.assertIn("live warehouse state", supplied_state.get_json()["message"])
        self.assertEqual(
            self.client.post("/algorithm-lab/banker", json={}).status_code,
            404
        )
        self.assertEqual(
            self.client.post("/algorithm-lab/deadlock", json={}).status_code,
            404
        )

    def test_failed_real_allocation_is_visible_but_zero_holding_waiter_is_not_deadlocked(self):
        for index in range(5):
            process_id = f"P_HOLDER_{index}"
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
            self.create_order("P_WAITER", ["Worker"]).status_code, 200
        )
        failed = self.client.post("/allocate", json={
            "process_id": "P_WAITER",
            "resources": ["Worker"]
        })
        self.assertEqual(failed.status_code, 409)
        self.assertEqual(failed.get_json()["pending_requests"], ["Worker"])

        deadlock = self.client.get("/deadlock").get_json()
        self.assertFalse(deadlock["deadlock_detected"])
        waiter = next(
            process for process in deadlock["processes"]
            if process["process_id"] == "P_WAITER"
        )
        self.assertFalse(waiter["deadlocked"])
        self.assertIn("holds no resources", waiter["explanation"])
        self.assertEqual(
            waiter["request"]["Worker"],
            1
        )

        self.assertTrue(
            self.client.post(
                "/release", json={"process_id": "P_HOLDER_0"}
            ).get_json()["success"]
        )
        retried = self.client.post("/allocate", json={
            "process_id": "P_WAITER",
            "resources": ["Worker"]
        })
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(
            self.client.get("/deadlock").get_json()["processes"][-1]["request"]["Worker"],
            0
        )

    def test_waiting_process_request_tracks_resources_released_by_that_process(self):
        self.assertEqual(
            self.create_order("P_WAITING", ["Worker", "Forklift"]).status_code,
            200
        )
        for process_id in ("P_FORK_1", "P_FORK_2"):
            self.assertEqual(
                self.create_order(process_id, ["Forklift"]).status_code,
                200
            )
            self.assertEqual(
                self.client.post("/allocate", json={
                    "process_id": process_id,
                    "resources": ["Forklift"]
                }).status_code,
                200
            )

        self.assertEqual(
            self.client.post("/allocate", json={
                "process_id": "P_WAITING",
                "resources": ["Worker"]
            }).status_code,
            200
        )
        waiting = self.client.post(
            "/run_process", json={"process_id": "P_WAITING"}
        )
        self.assertEqual(waiting.status_code, 409)
        self.assertEqual(
            next(
                process for process in self.client.get(
                    "/deadlock"
                ).get_json()["processes"]
                if process["process_id"] == "P_WAITING"
            )["request"],
            {"Worker": 0, "Forklift": 1, "Packing": 0, "Vehicle": 0}
        )

        released = self.client.post(
            "/release", json={"process_id": "P_WAITING"}
        )
        self.assertEqual(released.status_code, 200)
        waiting_process = next(
            process for process in self.client.get(
                "/deadlock"
            ).get_json()["processes"]
            if process["process_id"] == "P_WAITING"
        )
        self.assertEqual(
            waiting_process["request"],
            {"Worker": 1, "Forklift": 1, "Packing": 0, "Vehicle": 0}
        )

    def test_live_deadlock_reports_only_processes_holding_resources(self):
        process_ids = [
            "P1", "P3", "P4", "P5", "P6", "P2", "P7", "P8"
        ]
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

        for process_id in process_ids[:7]:
            waiting = engine.run_process(process_id)
            self.assertFalse(waiting["success"])
            self.assertEqual(waiting["state"], "WAITING")

        no_holding_waiter = self.client.post("/allocate", json={
            "process_id": "P8",
            "resources": ["Worker"]
        })
        self.assertEqual(no_holding_waiter.status_code, 409)

        result = self.client.get("/deadlock").get_json()
        self.assertTrue(result["deadlock_detected"])
        self.assertEqual(set(result["deadlocked_processes"]), set(process_ids[:7]))
        waiter = next(
            process for process in result["processes"]
            if process["process_id"] == "P8"
        )
        self.assertFalse(waiter["deadlocked"])
        self.assertEqual(waiter["allocation"]["Worker"], 0)

    def test_unsafe_banker_state_is_not_reported_as_deadlock(self):
        for process_id in ("P_A", "P_B"):
            self.assertEqual(
                self.create_order(process_id, ["Worker"]).status_code, 200
            )
            self.assertTrue(
                app_module.engine.allocate_resources(
                    process_id, ["Worker"]
                )["success"]
            )
            app_module.engine.set_maximum_claim(
                process_id,
                {"Worker": 5, "Forklift": 0, "Packing": 0, "Vehicle": 0}
            )

        banker = self.client.post("/banker").get_json()
        self.assertFalse(banker["safe"])
        self.assertEqual(set(banker["unfinished_processes"]), {"P_A", "P_B"})
        deadlock = self.client.get("/deadlock").get_json()
        self.assertFalse(deadlock["deadlock_detected"])
        self.assertEqual(deadlock["status"], "NO DEADLOCK")

    def test_completed_processes_are_excluded_and_monitors_do_not_mutate_state(self):
        self.assertEqual(
            self.create_order("P_DONE", ["Packing"]).status_code, 200
        )
        self.assertTrue(
            self.client.post(
                "/run_process", json={"process_id": "P_DONE"}
            ).get_json()["success"]
        )
        self.assertTrue(
            self.client.post(
                "/complete_process", json={"process_id": "P_DONE"}
            ).get_json()["success"]
        )
        before = self.client.get("/status").get_json()

        banker = self.client.post("/banker").get_json()
        deadlock = self.client.get("/deadlock").get_json()
        after = self.client.get("/status").get_json()

        self.assertEqual(banker["processes"], [])
        self.assertEqual(banker["status"], "SAFE STATE")
        self.assertEqual(deadlock["processes"], [])
        self.assertEqual(deadlock["message"], "No active processes.")
        self.assertEqual(before["processes"], after["processes"])
        self.assertEqual(before["resources"], after["resources"])

    def test_monitors_reject_inconsistent_live_resource_accounting(self):
        self.assertEqual(
            self.create_order("P_BROKEN", ["Worker"]).status_code, 200
        )
        app_module.engine.resource_manager.resources["Worker"] -= 1

        banker = self.client.post("/banker")
        deadlock = self.client.get("/deadlock")
        self.assertEqual(banker.status_code, 400)
        self.assertEqual(deadlock.status_code, 400)
        self.assertIn("accounting mismatch", banker.get_json()["message"])
        self.assertIn("accounting mismatch", deadlock.get_json()["message"])

    def test_order_ids_are_unique(self):
        self.assertEqual(
            self.create_order("P_ORDER_1", []).status_code, 200
        )
        duplicate = self.client.post("/create_order", json={
            "process_id": "P_ORDER_2",
            "order_id": "O_P_ORDER_1",
            "arrival_time": 0,
            "burst_time": 1,
            "priority": 1,
            "resources": []
        })
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(
            [
                process["process_id"]
                for process in self.client.get("/status").get_json()["processes"]
            ],
            ["P_ORDER_1"]
        )


if __name__ == "__main__":
    unittest.main()
