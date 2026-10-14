
import threading

from .models import WarehouseProcess


class ProcessManager:

    VALID_STATES = {
        "NEW",
        "READY",
        "RUNNING",
        "COMPLETED",
        "WAITING",
        "TERMINATED"
    }

    ALLOWED_TRANSITIONS = {
        "NEW": {"READY", "TERMINATED"},
        "READY": {"RUNNING", "WAITING", "TERMINATED"},
        "RUNNING": {"READY", "WAITING", "COMPLETED", "TERMINATED"},
        "WAITING": {"READY", "TERMINATED"},
        "COMPLETED": set(),
        "TERMINATED": set()
    }

    def __init__(self):
        self.lock = threading.RLock()
        self.processes = []

    def create_process(
        self,
        process_id,
        order_id,
        arrival_time,
        burst_time,
        priority,
        required_resources=None
    ):
        if (
            not isinstance(process_id, str)
            or not process_id.strip()
            or not isinstance(order_id, str)
            or not order_id.strip()
        ):
            raise ValueError("Process ID and Order ID are required")

        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in (arrival_time, burst_time, priority)
        ):
            raise ValueError("Arrival time, burst time, and priority must be integers")
        if arrival_time < 0:
            raise ValueError("Arrival time cannot be negative")

        if burst_time <= 0:
            raise ValueError("Burst time must be greater than zero")
        if priority < 1:
            raise ValueError("Priority must be greater than zero")

        if required_resources is None:
            required_resources = []
        if (
            not isinstance(required_resources, (list, tuple))
            or any(not isinstance(resource, str) for resource in required_resources)
        ):
            raise ValueError("Required resources must be a list of resource names")
        process = WarehouseProcess(
            process_id=process_id.strip(),
            order_id=order_id.strip(),
            arrival_time=arrival_time,
            burst_time=burst_time,
            priority=priority,
            required_resources=list(required_resources)
        )

        with self.lock:
            if self.get_process(process.process_id):
                raise ValueError(
                    f"Process ID '{process.process_id}' already exists"
                )
            if any(
                existing.order_id == process.order_id
                for existing in self.processes
            ):
                raise ValueError(
                    f"Order ID '{process.order_id}' already exists"
                )
            self.processes.append(process)
        return process

    def get_process(self, process_id):
        with self.lock:
            for process in self.processes:
                if process.process_id == process_id:
                    return process
            return None

    def get_all_processes(self):
        with self.lock:
            return self.processes.copy()

    def update_state(self, process_id, state):
        with self.lock:
            process = self.get_process(process_id)

            if not process or state not in self.VALID_STATES:
                return False

            if state == process.state:
                return True

            allowed = self.ALLOWED_TRANSITIONS.get(process.state, set())

            if state not in allowed:
                return False

            process.state = state
            return True

    def remove_process(self, process_id):
        with self.lock:
            process = self.get_process(process_id)

            if process:
                self.processes.remove(process)
                return True

            return False