
import threading
from collections import Counter


class ResourceManager:

    MAX_CAPACITY = (2 ** 53) - 1
    DEFAULT_CAPACITY = {
        "Worker": 5,
        "Forklift": 2,
        "Packing": 3,
        "Vehicle": 2
    }

    def __init__(self):
        self.lock = threading.RLock()
        self.resources = self.DEFAULT_CAPACITY.copy()
        self.total_resources = self.resources.copy()
        self.allocated = {}
        self.pending_requests = {}

    def get_available(self, resource):
        with self.lock:
            return self.resources.get(resource, 0)

    def request_resource(self, process_id, resource):
        with self.lock:
            if resource not in self.resources:
                return False

            if self.resources[resource] <= 0:
                return False

            self.resources[resource] -= 1
            self.allocated.setdefault(process_id, []).append(resource)
            return True

    def request_resources(self, process_id, resources):
        with self.lock:
            if not isinstance(resources, (list, tuple)) or not resources:
                return False
            if any(resource not in self.resources for resource in resources):
                return False

            requested = Counter(resources)
            if any(
                self.resources[resource] < quantity
                for resource, quantity in requested.items()
            ):
                return False

            for resource, quantity in requested.items():
                self.resources[resource] -= quantity
                self.allocated.setdefault(process_id, []).extend(
                    [resource] * quantity
                )
            return True

    def release_resource(self, process_id, resource):
        with self.lock:
            if process_id not in self.allocated:
                return False

            if resource not in self.allocated[process_id]:
                return False

            self.allocated[process_id].remove(resource)
            self.resources[resource] += 1

            if not self.allocated[process_id]:
                del self.allocated[process_id]

            return True

    def release_all(self, process_id):
        with self.lock:
            if process_id not in self.allocated:
                return False

            for resource in self.allocated[process_id]:
                self.resources[resource] += 1

            del self.allocated[process_id]
            return True

    def release_resources(self, process_id, resources):
        with self.lock:
            if not isinstance(resources, (list, tuple)) or not resources:
                return False
            holdings = self.allocated.get(process_id, [])
            requested = Counter(resources)
            if any(
                holdings.count(resource) < quantity
                for resource, quantity in requested.items()
            ):
                return False

            for resource, quantity in requested.items():
                for _ in range(quantity):
                    holdings.remove(resource)
                self.resources[resource] += quantity

            if not holdings:
                self.allocated.pop(process_id, None)
            return True

    def get_all_resources(self):
        with self.lock:
            return self.resources.copy()

    def get_total_resources(self):
        with self.lock:
            return self.total_resources.copy()

    def configure_capacity(self, capacities):
        if not isinstance(capacities, dict) or set(capacities) != set(
            self.total_resources
        ):
            raise ValueError(
                "Resource capacity must include every supported resource"
            )
        if any(
            not isinstance(amount, int)
            or isinstance(amount, bool)
            or amount < 0
            or amount > self.MAX_CAPACITY
            for amount in capacities.values()
        ):
            raise ValueError(
                "Resource capacities must be non-negative safe integers"
            )

        with self.lock:
            allocated = Counter(
                resource
                for holdings in self.allocated.values()
                for resource in holdings
            )
            for resource, amount in capacities.items():
                if amount < allocated[resource]:
                    raise ValueError(
                        f"Cannot reduce {resource} capacity below its "
                        f"{allocated[resource]} currently allocated unit(s)"
                    )

            self.total_resources = capacities.copy()
            self.resources = {
                resource: amount - allocated[resource]
                for resource, amount in capacities.items()
            }
            return self.total_resources.copy(), self.resources.copy()

    def get_allocated_resources(self, process_id):
        with self.lock:
            return self.allocated.get(process_id, []).copy()

    def get_pending_requests(self, process_id):
        with self.lock:
            return self.pending_requests.get(process_id, []).copy()

    def set_pending_requests(self, process_id, resources):
        with self.lock:
            if resources:
                self.pending_requests[process_id] = list(resources)
            else:
                self.pending_requests.pop(process_id, None)

    def cancel_pending_requests(self, process_id):
        with self.lock:
            if process_id in self.pending_requests:
                del self.pending_requests[process_id]
                return True

            return False
