
import copy
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from os_modules.process_manager import ProcessManager
from os_modules.scheduler import Scheduler
from os_modules.resource_manager import ResourceManager
from os_modules.deadlock_detector import DeadlockDetector
from os_modules.banker import Banker
from os_modules.synchronization import WarehouseSynchronizer
from os_modules.models import WarehouseProcess


class WarehouseEngine:
    def __init__(self, state_path=None):
        self.process_manager = ProcessManager()
        self.scheduler = Scheduler()
        self.resource_manager = ResourceManager()
        self.deadlock_detector = DeadlockDetector()
        self.banker = Banker()
        self.synchronizer = WarehouseSynchronizer()
        self.maximum_claims = {}
        self.resource_order = list(
            self.resource_manager.get_all_resources().keys()
        )
        self.resource_capacity = self.resource_manager.get_all_resources()
        self.state_path = Path(state_path) if state_path is not None else None
        if self.state_path is not None:
            self._load_persisted_state()

    def _state_payload_locked(self):
        return {
            "processes": [
                {
                    "process_id": process.process_id,
                    "order_id": process.order_id,
                    "arrival_time": process.arrival_time,
                    "burst_time": process.burst_time,
                    "priority": process.priority,
                    "required_resources": process.required_resources,
                    "remaining_time": process.remaining_time,
                    "completion_time": process.completion_time,
                    "waiting_time": process.waiting_time,
                    "turnaround_time": process.turnaround_time,
                    "state": process.state
                }
                for process in self.process_manager.get_all_processes()
            ],
            "available": self.resource_manager.get_all_resources(),
            "resource_capacity": (
                self.resource_manager.get_total_resources()
            ),
            "allocated": copy.deepcopy(self.resource_manager.allocated),
            "pending_requests": copy.deepcopy(
                self.resource_manager.pending_requests
            ),
            "maximum_claims": copy.deepcopy(self.maximum_claims)
        }

    def _persist_state_locked(self):
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._state_payload_locked())
        with closing(sqlite3.connect(self.state_path, timeout=10)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS warehouse_state (
                        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                        version INTEGER NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO warehouse_state (singleton_id, version, payload)
                    VALUES (1, 1, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        version = excluded.version,
                        payload = excluded.payload
                    """,
                    (payload,)
                )

    def _load_persisted_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.state_path, timeout=10)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS warehouse_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT version, payload FROM warehouse_state "
                "WHERE singleton_id = 1"
            ).fetchone()

        if row is None:
            return
        version, serialized = row
        if version != 1:
            raise RuntimeError(
                f"Unsupported warehouse state version: {version}"
            )

        try:
            payload = json.loads(serialized)
            processes = [
                WarehouseProcess(
                    process_id=item["process_id"],
                    order_id=item["order_id"],
                    arrival_time=item["arrival_time"],
                    burst_time=item["burst_time"],
                    priority=item["priority"],
                    required_resources=item["required_resources"]
                )
                for item in payload["processes"]
            ]
            for process, item in zip(processes, payload["processes"]):
                process.remaining_time = item["remaining_time"]
                process.completion_time = item["completion_time"]
                process.waiting_time = item["waiting_time"]
                process.turnaround_time = item["turnaround_time"]
                process.state = item["state"]

            available = payload["available"]
            allocated = payload["allocated"]
            pending_requests = payload["pending_requests"]
            maximum_claims = payload["maximum_claims"]
            resource_capacity = payload.get(
                "resource_capacity",
                self.resource_manager.get_total_resources()
            )
            if (
                not isinstance(available, dict)
                or not isinstance(resource_capacity, dict)
                or not isinstance(allocated, dict)
                or not isinstance(pending_requests, dict)
                or not isinstance(maximum_claims, dict)
            ):
                raise ValueError("Persisted resource records are invalid")
            process_ids = [process.process_id for process in processes]
            order_ids = [process.order_id for process in processes]
            if len(process_ids) != len(set(process_ids)):
                raise ValueError("Persisted process IDs are not unique")
            if len(order_ids) != len(set(order_ids)):
                raise ValueError("Persisted order IDs are not unique")
            if set(resource_capacity) != set(self.resource_order):
                raise ValueError("Persisted resource capacities do not match")
            for name, amount in resource_capacity.items():
                if (
                    not isinstance(amount, int)
                    or isinstance(amount, bool)
                    or amount < 0
                    or amount > ResourceManager.MAX_CAPACITY
                ):
                    raise ValueError(
                        f"Invalid persisted resource capacity for {name}"
                    )
            self.resource_capacity = resource_capacity.copy()
            self.resource_manager.total_resources = (
                resource_capacity.copy()
            )
            if set(available) != set(self.resource_order):
                raise ValueError("Persisted resource names do not match")
            for name, amount in available.items():
                if (
                    not isinstance(amount, int)
                    or isinstance(amount, bool)
                    or amount < 0
                    or amount > self.resource_capacity[name]
                ):
                    raise ValueError(
                        f"Invalid persisted resource count for {name}"
                    )
            if any(
                not isinstance(process.state, str)
                or process.state not in ProcessManager.VALID_STATES
                for process in processes
            ):
                raise ValueError("Persisted process state is invalid")

            self.process_manager.processes = processes
            self.resource_manager.resources = available
            self.resource_manager.allocated = allocated
            self.resource_manager.pending_requests = pending_requests
            self.maximum_claims = maximum_claims
            snapshot = self._live_resource_snapshot_locked()
            active_ids = {
                process.process_id
                for process in snapshot["active_processes"]
            }
            if set(maximum_claims) != active_ids:
                raise ValueError("Persisted maximum claims do not match active processes")
            for process_id, claims in maximum_claims.items():
                if not isinstance(claims, dict) or set(claims) != set(
                    self.resource_order
                ):
                    raise ValueError(
                        f"Invalid persisted maximum claim for {process_id}"
                    )
                allocation = snapshot["allocation_by_id"].get(
                    process_id, {}
                )
                for name, amount in claims.items():
                    if (
                        not isinstance(amount, int)
                        or isinstance(amount, bool)
                        or amount < allocation.get(name, 0)
                        or amount > self.resource_capacity[name]
                    ):
                        raise ValueError(
                            f"Invalid persisted maximum claim for {process_id}: {name}"
                        )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"Could not load persisted warehouse state: {error}"
            ) from error

    @staticmethod
    def _remaining_resources(required, allocated):
        remaining = Counter(required)
        remaining.subtract(allocated)
        return [
            resource
            for resource, quantity in remaining.items()
            for _ in range(max(quantity, 0))
        ]

    def create_order(
        self, process_id, order_id, arrival_time,
        burst_time, priority, resources
    ):
        if (
            not isinstance(process_id, str)
            or not process_id.strip()
            or not isinstance(order_id, str)
            or not order_id.strip()
        ):
            raise ValueError("Process ID and Order ID are required")
        if (
            not isinstance(resources, (list, tuple))
            or any(
                not isinstance(resource, str)
                or resource not in self.resource_capacity
                for resource in resources
            )
        ):
            raise ValueError("Resources must contain valid resource names")
        requested = Counter(resources)
        for name, quantity in requested.items():
            if quantity > self.resource_capacity[name]:
                raise ValueError(
                    f"Maximum claim for {name} exceeds total capacity "
                    f"({self.resource_capacity[name]})"
                )

        with self.resource_manager.lock:
            if any(
                process.order_id == order_id.strip()
                for process in self.process_manager.get_all_processes()
            ):
                raise ValueError(f"Order ID '{order_id.strip()}' already exists")
            process = self.process_manager.create_process(
                process_id,
                order_id,
                arrival_time,
                burst_time,
                priority,
                resources
            )
            self.set_maximum_claim(
                process.process_id,
                {
                    name: resources.count(name)
                    for name in self.resource_order
                }
            )
            self._persist_state_locked()
        return process

    def configure_resource_capacity(self, capacities):
        if not isinstance(capacities, dict) or set(capacities) != set(
            self.resource_order
        ):
            raise ValueError(
                "Provide a capacity for every supported resource"
            )
        if any(
            not isinstance(amount, int)
            or isinstance(amount, bool)
            or amount < 0
            or amount > ResourceManager.MAX_CAPACITY
            for amount in capacities.values()
        ):
            raise ValueError(
                "Resource capacities must be non-negative safe integers"
            )

        with self.resource_manager.lock:
            snapshot = self._live_resource_snapshot_locked()
            allocated_totals = {
                name: (
                    snapshot["total"][name] - snapshot["available"][name]
                )
                for name in self.resource_order
            }
            for name in self.resource_order:
                amount = capacities[name]
                if amount < allocated_totals[name]:
                    raise ValueError(
                        f"Cannot reduce {name} capacity below its "
                        f"{allocated_totals[name]} currently allocated unit(s)"
                    )

            for process in snapshot["active_processes"]:
                claims = self.maximum_claims[process.process_id]
                for name in self.resource_order:
                    if capacities[name] < claims[name]:
                        raise ValueError(
                            f"Cannot reduce {name} capacity below the "
                            f"{claims[name]}-unit maximum claim for "
                            f"{process.process_id}"
                        )

            previous_capacity = self.resource_manager.get_total_resources()
            previous_available = self.resource_manager.get_all_resources()
            try:
                total, available = (
                    self.resource_manager.configure_capacity(capacities)
                )
                self.resource_capacity = total.copy()
                self._persist_state_locked()
            except Exception:
                self.resource_manager.total_resources = previous_capacity
                self.resource_manager.resources = previous_available
                self.resource_capacity = previous_capacity.copy()
                raise

            return {
                "total_resources": total,
                "available_resources": available
            }

    def reset_warehouse(self):
        with self.resource_manager.lock:
            with self.process_manager.lock:
                running_processes = [
                    process.process_id
                    for process in self.process_manager.processes
                    if process.state == "RUNNING"
                ]
                if running_processes:
                    raise ValueError(
                        "Cannot reset while processes are running: "
                        + ", ".join(running_processes)
                    )

                previous_processes = self.process_manager.processes.copy()
                previous_available = (
                    self.resource_manager.get_all_resources()
                )
                previous_capacity = (
                    self.resource_manager.get_total_resources()
                )
                previous_allocated = copy.deepcopy(
                    self.resource_manager.allocated
                )
                previous_pending = copy.deepcopy(
                    self.resource_manager.pending_requests
                )
                previous_claims = copy.deepcopy(self.maximum_claims)

                try:
                    self.process_manager.processes.clear()
                    self.resource_manager.total_resources = (
                        ResourceManager.DEFAULT_CAPACITY.copy()
                    )
                    self.resource_manager.resources = (
                        ResourceManager.DEFAULT_CAPACITY.copy()
                    )
                    self.resource_manager.allocated.clear()
                    self.resource_manager.pending_requests.clear()
                    self.maximum_claims.clear()
                    self.resource_capacity = (
                        ResourceManager.DEFAULT_CAPACITY.copy()
                    )
                    self._persist_state_locked()
                except Exception:
                    self.process_manager.processes = previous_processes
                    self.resource_manager.resources = previous_available
                    self.resource_manager.total_resources = previous_capacity
                    self.resource_manager.allocated = previous_allocated
                    self.resource_manager.pending_requests = previous_pending
                    self.maximum_claims = previous_claims
                    self.resource_capacity = previous_capacity.copy()
                    raise

                return {
                    "total_resources": (
                        self.resource_manager.get_total_resources()
                    ),
                    "available_resources": (
                        self.resource_manager.get_all_resources()
                    )
                }

    def schedule_orders(self, algorithm="FCFS", time_quantum=2):
        with self.resource_manager.lock:
            processes = [
                copy.deepcopy(process)
                for process in self.process_manager.get_all_processes()
            ]
            scheduled = self.scheduler.schedule(
                processes,
                algorithm,
                time_quantum
            )
            processes_by_id = {
                process.process_id: process
                for process in self.process_manager.get_all_processes()
            }
            for result in scheduled:
                process = processes_by_id[result.process_id]
                process.completion_time = result.completion_time
                process.waiting_time = result.waiting_time
                process.turnaround_time = result.turnaround_time
            self._persist_state_locked()

        count = len(scheduled)
        total_waiting = sum(p.waiting_time for p in scheduled)
        total_turnaround = sum(
            p.turnaround_time for p in scheduled
        )

        return {
            "processes": scheduled,
            "average_waiting_time": (
                total_waiting / count if count else 0
            ),
            "average_turnaround_time": (
                total_turnaround / count if count else 0
            )
        }

    def allocate_resources(self, process_id, resources):
        if isinstance(resources, str):
            resources = [resources]

        if not isinstance(resources, (list, tuple)) or not resources:
            return {
                "success": False,
                "message": "Provide a non-empty list of resources"
            }

        if any(not isinstance(resource, str) for resource in resources):
            return {
                "success": False,
                "message": "Resource names must be strings"
            }

        with self.resource_manager.lock:
            process = self.process_manager.get_process(process_id)
            if process is None:
                return {
                    "success": False,
                    "message": "Process not found"
                }

            if process.state in ("RUNNING", "COMPLETED", "TERMINATED"):
                return {
                    "success": False,
                    "message": (
                        f"Cannot allocate resources to a process in "
                        f"{process.state} state"
                    )
                }

            allocated = self.resource_manager.get_allocated_resources(
                process_id
            )
            requested_counts = Counter(resources)
            maximum_claim = self.maximum_claims.get(process_id, {})
            allocated_counts = Counter(allocated)
            for resource, quantity in requested_counts.items():
                if resource not in self.resource_manager.resources:
                    return {
                        "success": False,
                        "message": f"Unknown resource: {resource}"
                    }

                claim = maximum_claim.get(resource)
                if not isinstance(claim, int) or isinstance(claim, bool):
                    return {
                        "success": False,
                        "message": (
                            f"Maximum claim is not configured for "
                            f"{process_id}: {resource}"
                        )
                    }
                remaining_claim = max(claim - allocated_counts[resource], 0)
                if quantity > remaining_claim:
                    return {
                        "success": False,
                        "message": (
                            f"Request exceeds {process_id}'s remaining "
                            f"maximum claim for {resource} "
                            f"({remaining_claim} "
                            "unit(s) remaining)."
                        )
                    }

            available_counts = self.resource_manager.get_all_resources()
            shortages = {
                resource: quantity - available_counts[resource]
                for resource, quantity in requested_counts.items()
                if quantity > available_counts[resource]
            }
            if shortages:
                resource = next(iter(shortages))
                if process.state == "WAITING":
                    pending_requests = self._remaining_resources(
                        process.required_resources, allocated
                    )
                else:
                    pending_requests = list(resources)
                self.resource_manager.set_pending_requests(
                    process_id, pending_requests
                )
                self._persist_state_locked()
                return {
                    "success": False,
                    "message": (
                        f"Insufficient {resource}: requested "
                        f"{requested_counts[resource]}, available "
                        f"{available_counts[resource]}."
                    ),
                    "pending_requests": pending_requests
                }

            if not self.resource_manager.request_resources(
                process_id, resources
            ):
                return {
                    "success": False,
                    "message": "Resource allocation failed; no resources were allocated"
                }

            allocated_now = list(resources)
            if process.state == "WAITING":
                allocated = self.resource_manager.get_allocated_resources(
                    process_id
                )
                remaining = self._remaining_resources(
                    process.required_resources, allocated
                )
                self.resource_manager.set_pending_requests(
                    process_id, remaining
                )
            else:
                pending = self.resource_manager.get_pending_requests(
                    process_id
                )
                remaining_pending = self._remaining_resources(
                    pending, allocated_now
                )
                self.resource_manager.set_pending_requests(
                    process_id, remaining_pending
                )

            self._persist_state_locked()
            return {
                "success": True,
                "process_id": process_id,
                "allocated": allocated_now,
                "available": self.resource_manager.get_all_resources()
            }

    def release_resources(self, process_id, resource=None, quantity=None):
        with self.resource_manager.lock:
            process = self.process_manager.get_process(process_id)
            if process is not None and process.state == "RUNNING":
                return {
                    "success": False,
                    "message": (
                        "Cannot release resources while the process is "
                        "RUNNING; complete it first"
                    ),
                    "process_id": process_id,
                    "available": self.resource_manager.get_all_resources()
                }

            holdings = self.resource_manager.get_allocated_resources(process_id)
            if resource is None:
                if quantity is not None:
                    return {
                        "success": False,
                        "message": "Specify a resource when releasing a quantity"
                    }
                released = holdings
                success = self.resource_manager.release_all(process_id)
            else:
                if resource not in self.resource_order:
                    return {
                        "success": False,
                        "message": f"Unknown resource: {resource}",
                        "available": self.resource_manager.get_all_resources()
                    }
                if quantity is None:
                    quantity = 1
                if (
                    not isinstance(quantity, int)
                    or isinstance(quantity, bool)
                    or quantity <= 0
                ):
                    return {
                        "success": False,
                        "message": "Release quantity must be a positive integer",
                        "available": self.resource_manager.get_all_resources()
                    }
                if holdings.count(resource) < quantity:
                    return {
                        "success": False,
                        "message": (
                            f"Cannot release {quantity} {resource} unit(s); "
                            f"{process_id} holds {holdings.count(resource)}."
                        ),
                        "available": self.resource_manager.get_all_resources()
                    }
                released = [resource] * quantity
                success = self.resource_manager.release_resources(
                    process_id, released
                )

            if success and process is not None and process.state == "WAITING":
                allocated = self.resource_manager.get_allocated_resources(
                    process_id
                )
                self.resource_manager.set_pending_requests(
                    process_id,
                    self._remaining_resources(
                        process.required_resources, allocated
                    )
                )
            if success:
                self._persist_state_locked()

            return {
                "success": success,
                "process_id": process_id,
                "released": released if success else [],
                "available": self.resource_manager.get_all_resources()
            }

    
    
    def run_process(self, process_id):
        with self.resource_manager.lock:
            return self._run_process_locked(process_id)

    def _run_process_locked(self, process_id):
        process = self.process_manager.get_process(process_id)

        if process is None:
            return {
            "success": False,
            "message": "Process not found"
        }

        if process.state not in ("NEW", "READY", "WAITING"):
            return {
            "success": False,
            "message": f"Cannot run process in {process.state} state"
        }

        if process.state == "NEW":
            if not self.process_manager.update_state(process_id, "READY"):
                return {
                "success": False,
                "message": "Unable to move process to READY state"
            }

        required = process.required_resources or []
        allocated = self.resource_manager.get_allocated_resources(process_id)
        missing = self._remaining_resources(required, allocated)

        if missing:
            result = self.allocate_resources(process_id, missing)

            if not result.get("success"):
                self.resource_manager.set_pending_requests(
                    process_id, missing
                )
                if process.state != "WAITING":
                    self.process_manager.update_state(process_id, "WAITING")
                self._persist_state_locked()

                return {
                "success": False,
                "message": "Required resources are unavailable: " + ", ".join(missing),
                "state": "WAITING",
                "allocated_resources": self.resource_manager.get_allocated_resources(process_id)
            }

        self.resource_manager.cancel_pending_requests(process_id)

        if process.state == "WAITING":
            if not self.process_manager.update_state(process_id, "READY"):
                return {
                "success": False,
                "message": "Unable to move process back to READY state"
            }

        if not self.process_manager.update_state(process_id, "RUNNING"):
            return {
            "success": False,
            "message": "Unable to move process to RUNNING state"
        }

        self._persist_state_locked()
        return {
        "success": True,
        "process_id": process_id,
        "state": "RUNNING",
        "allocated_resources": self.resource_manager.get_allocated_resources(process_id)
    }

    def complete_process(self, process_id):
        with self.resource_manager.lock:
            process = self.process_manager.get_process(process_id)
            if process is None:
                return {
                    "success": False,
                    "message": "Process not found"
                }
            if process.state != "RUNNING":
                return {
                    "success": False,
                    "message": "Only a RUNNING process can be completed"
                }
            if not self.process_manager.update_state(
                process_id, "COMPLETED"
            ):
                return {
                    "success": False,
                    "message": "Unable to complete process"
                }

            self.resource_manager.release_all(process_id)
            self.resource_manager.cancel_pending_requests(process_id)
            self.maximum_claims.pop(process_id, None)
            self._persist_state_locked()
            return {
                "success": True,
                "process_id": process_id,
                "state": "COMPLETED",
                "available_resources": (
                    self.resource_manager.get_all_resources()
                )
            }


    def check_safe_state(
        self, available, allocation, maximum, process_ids=None
    ):
        try:
            if not isinstance(available, list):
                raise ValueError(
                    "Available resources must be a list"
                )

            if (
                not isinstance(allocation, list)
                or not isinstance(maximum, list)
            ):
                raise ValueError(
                    "Allocation and maximum must be matrices"
                )

            if len(allocation) != len(maximum):
                raise ValueError(
                    "Allocation and maximum must have equal rows"
                )

            if any(
                not isinstance(row, list)
                for row in allocation + maximum
            ):
                raise ValueError("Each matrix row must be a list")

            if any(
                len(row) != len(available)
                for row in allocation + maximum
            ):
                raise ValueError(
                    "Resource matrix dimensions do not match"
                )

            values = available + [
                value
                for row in allocation + maximum
                for value in row
            ]

            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
                for value in values
            ):
                raise ValueError(
                    "Resource counts must be non-negative numbers"
                )

            for allocation_row, maximum_row in zip(
                allocation, maximum
            ):
                if any(
                    maximum_row[j] < allocation_row[j]
                    for j in range(len(available))
                ):
                    raise ValueError(
                        "Maximum claim cannot be less than allocation"
                    )

            return self.banker.check_safety(
                available.copy(),
                copy.deepcopy(allocation),
                copy.deepcopy(maximum),
                process_ids
            )

        except (ValueError, TypeError, IndexError) as error:
            return {
                "error": True,
                "safe": False,
                "safe_sequence": [],
                "need": [],
                "unfinished_processes": [],
                "message": str(error)
            }

    def _live_resource_snapshot_locked(self):
        available = self.resource_manager.get_all_resources()
        total = self.resource_manager.get_total_resources()
        resource_names = list(available)
        processes = self.process_manager.get_all_processes()
        process_by_id = {process.process_id: process for process in processes}

        if (
            len(process_by_id) != len(processes)
            or set(resource_names) != set(total)
            or set(resource_names) != set(self.resource_order)
        ):
            raise ValueError("Live process or resource records are inconsistent")

        for resource in resource_names:
            if (
                not isinstance(available[resource], int)
                or isinstance(available[resource], bool)
                or available[resource] < 0
                or not isinstance(total[resource], int)
                or isinstance(total[resource], bool)
                or total[resource] < 0
            ):
                raise ValueError(f"Invalid live resource count for {resource}")

        allocated = copy.deepcopy(self.resource_manager.allocated)
        pending = copy.deepcopy(self.resource_manager.pending_requests)
        allocation_by_id = {}
        request_by_id = {}
        allocated_totals = {name: 0 for name in resource_names}

        for process_id, holdings in allocated.items():
            process = process_by_id.get(process_id)
            if process is None or process.state in ("COMPLETED", "TERMINATED"):
                raise ValueError(
                    f"Allocation exists for inactive or unknown process {process_id}"
                )
            if not isinstance(holdings, list) or any(
                name not in allocated_totals for name in holdings
            ):
                raise ValueError(f"Invalid allocation record for {process_id}")
            allocation_by_id[process_id] = {
                name: holdings.count(name) for name in resource_names
            }
            for name in holdings:
                allocated_totals[name] += 1

        active_processes = [
            process for process in processes
            if process.state not in ("COMPLETED", "TERMINATED")
        ]
        active_ids = {process.process_id for process in active_processes}
        if set(self.maximum_claims) != active_ids:
            raise ValueError(
                "Maximum claims do not match the active process records"
            )

        for process in active_processes:
            process_id = process.process_id
            claims = self.maximum_claims.get(process_id)
            if (
                not isinstance(claims, dict)
                or set(claims) != set(resource_names)
            ):
                raise ValueError(
                    f"Maximum claim is missing or invalid for {process_id}"
                )
            allocations = allocation_by_id.get(process_id, {})
            for name in resource_names:
                amount = claims[name]
                if (
                    not isinstance(amount, int)
                    or isinstance(amount, bool)
                    or amount < allocations.get(name, 0)
                    or amount > total[name]
                ):
                    raise ValueError(
                        f"Invalid maximum claim for {process_id}: {name}"
                    )

        for process_id, requests in pending.items():
            process = process_by_id.get(process_id)
            if (
                process is None
                or process_id not in active_ids
                or not isinstance(requests, list)
                or any(name not in resource_names for name in requests)
            ):
                raise ValueError(f"Invalid pending request record for {process_id}")
            request_by_id[process_id] = {
                name: requests.count(name) for name in resource_names
            }
            allocations = allocation_by_id.get(process_id, {})
            claims = self.maximum_claims[process_id]
            if any(
                request_by_id[process_id][name]
                > claims[name] - allocations.get(name, 0)
                for name in resource_names
            ):
                raise ValueError(
                    f"Pending requests exceed {process_id}'s remaining claim"
                )

        for name in resource_names:
            if available[name] + allocated_totals[name] != total[name]:
                raise ValueError(
                    f"Resource accounting mismatch for {name}: available plus "
                    "allocated does not equal total"
                )

        return {
            "available": available,
            "total": total,
            "resource_names": resource_names,
            "active_processes": active_processes,
            "process_by_id": process_by_id,
            "allocation_by_id": allocation_by_id,
            "request_by_id": request_by_id
        }

    def check_current_warehouse_state(self):
        with self.resource_manager.lock:
            return self._check_current_warehouse_state_locked()

    def _check_current_warehouse_state_locked(self):
        try:
            snapshot = self._live_resource_snapshot_locked()
            resources = snapshot["available"]
            resource_names = snapshot["resource_names"]
            processes = snapshot["active_processes"]
            process_ids = [process.process_id for process in processes]
            allocation = []
            maximum = []
            need_by_id = {}
            allocations_by_id = {}
            maxima_by_id = {}

            for process in processes:
                process_id = process.process_id
                allocation_row = [
                    snapshot["allocation_by_id"].get(
                        process_id, {}
                    ).get(name, 0)
                    for name in resource_names
                ]
                claim = self.maximum_claims.get(process_id)
                if not isinstance(claim, dict) or set(claim) != set(resource_names):
                    raise ValueError(
                        f"Maximum claim is missing or invalid for {process_id}"
                    )

                maximum_row = []
                for index, name in enumerate(resource_names):
                    amount = claim[name]
                    if (
                        not isinstance(amount, int)
                        or isinstance(amount, bool)
                        or amount < allocation_row[index]
                        or amount > snapshot["total"][name]
                    ):
                        raise ValueError(
                            f"Invalid maximum claim for {process_id}: {name}"
                        )
                    maximum_row.append(amount)

                allocation.append(allocation_row)
                maximum.append(maximum_row)
                allocations_by_id[process_id] = dict(
                    zip(resource_names, allocation_row)
                )
                maxima_by_id[process_id] = dict(
                    zip(resource_names, maximum_row)
                )

            if not process_ids:
                return {
                    "safe": True,
                    "safe_sequence": [],
                    "need": [],
                    "need_by_process": {},
                    "unfinished_processes": [],
                    "available": resources,
                    "final_work": [resources[name] for name in resource_names],
                    "resource_types": resource_names,
                    "processes": [],
                    "allocation": {},
                    "maximum": {},
                    "process_explanations": [],
                    "message": "No active processes; the system is safe."
                }

            result = self.check_safe_state(
                [resources[name] for name in resource_names],
                allocation,
                maximum,
                process_ids
            )
            if result.get("error"):
                raise ValueError(result["message"])

            for index, process_id in enumerate(process_ids):
                need_by_id[process_id] = {
                    name: result["need"][index][resource_index]
                    for resource_index, name in enumerate(resource_names)
                }

            unfinished = set(result["unfinished_processes"])
            explanations = []
            for process in processes:
                process_id = process.process_id
                unsatisfied = [
                    f"{name} needs {need_by_id[process_id][name]} but "
                    f"final Work has {result['final_work'][index]}"
                    for index, name in enumerate(resource_names)
                    if need_by_id[process_id][name] > result["final_work"][index]
                ]
                explanations.append({
                    "process_id": process_id,
                    "order_id": process.order_id,
                    "state": process.state,
                    "can_finish": process_id not in unfinished,
                    "explanation": (
                        "Cannot finish because " + ", ".join(unsatisfied) + "."
                        if process_id in unfinished
                        else "Can finish in the computed safe sequence."
                    )
                })

            result.update({
                "available": resources,
                "resource_types": resource_names,
                "allocation": allocations_by_id,
                "maximum": maxima_by_id,
                "need_by_process": need_by_id,
                "processes": [
                    {
                        "process_id": process.process_id,
                        "order_id": process.order_id,
                        "state": process.state
                    }
                    for process in processes
                ],
                "process_explanations": explanations,
                "message": (
                    "The current warehouse state is safe."
                    if result["safe"]
                    else "The current warehouse state is unsafe. "
                         "No complete safe sequence was found."
                )
            })
            return result
        except (KeyError, TypeError, ValueError) as error:
            return {
                "error": True,
                "safe": False,
                "safe_sequence": [],
                "need": [],
                "need_by_process": {},
                "unfinished_processes": [],
                "available": self.resource_manager.get_all_resources(),
                "allocation": {},
                "maximum": {},
                "processes": [],
                "process_explanations": [],
                "message": str(error)
            }

    def detect_current_deadlock(self):
        with self.resource_manager.lock:
            snapshot = self._live_resource_snapshot_locked()
            resource_names = snapshot["resource_names"]
            processes = snapshot["active_processes"]
            process_ids = [process.process_id for process in processes]
            allocation = [
                [
                    snapshot["allocation_by_id"].get(pid, {}).get(name, 0)
                    for name in resource_names
                ]
                for pid in process_ids
            ]
            requests = [
                [
                    snapshot["request_by_id"].get(pid, {}).get(name, 0)
                    for name in resource_names
                ]
                for pid in process_ids
            ]
            available = [snapshot["available"][name] for name in resource_names]
            result = self.deadlock_detector.detect_deadlock(
                allocation, requests, available, process_ids
            )
            deadlocked = set(result["deadlocked_processes"])
            explanations = []

            for index, process in enumerate(processes):
                process_id = process.process_id
                holds_resources = any(allocation[index])
                request = requests[index]
                if process_id in deadlocked:
                    unavailable = [
                        f"{resource_names[column]} needs {request[column]} "
                        f"but final Work has {result['final_work'][column]}"
                        for column in range(len(resource_names))
                        if request[column] > result["final_work"][column]
                    ]
                    explanation = (
                        "Deadlocked: it holds resources and cannot be "
                        "satisfied because " + ", ".join(unavailable) + "."
                    )
                elif any(request) and not holds_resources:
                    unavailable = [
                        resource_names[column]
                        for column in range(len(resource_names))
                        if request[column] > available[column]
                    ]
                    explanation = (
                        "Waiting for " + ", ".join(unavailable)
                        + " but holds no resources, so it is not part of "
                          "a deadlock."
                        if unavailable
                        else "Its request can be granted; it holds no "
                             "resources and is not deadlocked."
                    )
                elif any(request):
                    explanation = (
                        "Its request can be satisfied after the preceding "
                        "processes in the detection sequence finish."
                    )
                else:
                    explanation = "No outstanding resource request."
                explanations.append({
                    "process_id": process_id,
                    "order_id": process.order_id,
                    "state": process.state,
                    "allocation": {
                        name: allocation[index][column]
                        for column, name in enumerate(resource_names)
                    },
                    "request": {
                        name: requests[index][column]
                        for column, name in enumerate(resource_names)
                    },
                    "deadlocked": process_id in deadlocked,
                    "explanation": explanation
                })

            return {
                **result,
                "resource_types": resource_names,
                "available": snapshot["available"],
                "processes": explanations,
                "status": (
                    "DEADLOCK DETECTED"
                    if result["deadlock_detected"]
                    else "NO DEADLOCK"
                ),
                "message": (
                    f"Deadlock detected involving {', '.join(result['deadlocked_processes'])}."
                    if result["deadlock_detected"]
                    else (
                        "No active processes."
                        if not process_ids
                        else "No deadlock detected in the current warehouse state."
                    )
                )
            }

    def set_maximum_claim(self, process_id, claims):
        if not isinstance(claims, dict):
            raise ValueError(
                "Maximum claims must be a dictionary"
            )

        if self.process_manager.get_process(process_id) is None:
            raise ValueError(f"Unknown process: {process_id}")

        with self.resource_manager.lock:
            current_allocation = (
                self.resource_manager.get_allocated_resources(process_id)
            )
            current_counts = {
                name: current_allocation.count(name)
                for name in self.resource_order
            }

            for name, amount in claims.items():
                if name not in self.resource_order:
                    raise ValueError(f"Unknown resource: {name}")

                if (
                    not isinstance(amount, int)
                    or isinstance(amount, bool)
                    or amount < current_counts[name]
                    or amount > self.resource_capacity[name]
                ):
                    raise ValueError(
                        f"Invalid maximum claim for {process_id}: {name}"
                    )

            self.maximum_claims[process_id] = {
                name: claims.get(name, current_counts[name])
                for name in self.resource_order
            }
            self._persist_state_locked()

            return self.maximum_claims[process_id]

    def get_system_status(self):
        with self.resource_manager.lock:
            return {
                "resources": self.resource_manager.get_all_resources(),
                "allocated": copy.deepcopy(
                    self.resource_manager.allocated
                ),
                "banker": self.check_current_warehouse_state()
            }
