from dataclasses import dataclass, field
from typing import List


@dataclass
class WarehouseProcess:
    process_id: str
    order_id: str
    arrival_time: int
    burst_time: int
    priority: int
    required_resources: List[str] = field(default_factory=list)

    remaining_time: int = 0
    completion_time: int = 0
    waiting_time: int = 0
    turnaround_time: int = 0
    state: str = "NEW"

    def __post_init__(self):
        self.remaining_time = self.burst_time