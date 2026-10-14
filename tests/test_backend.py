import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from os_modules.resource_manager import ResourceManager
from os_modules.process_manager import ProcessManager
from os_modules.scheduler import Scheduler
manager = ProcessManager()
manager.create_process(
    "P1",
    "O101",
    0,
    5,
    2,
    ["Worker", "Forklift"]
)

manager.create_process(
    "P2",
    "O102",
    1,
    3,
    1,
    ["Worker"]
)

manager.create_process(
    "P3",
    "O103",
    2,
    4,
    3,
    ["Worker", "Packing"]
)


processes = manager.get_all_processes()

scheduler = Scheduler()

print("\n========== FCFS ==========")

result = scheduler.fcfs(processes)

for process in result:
    print(
        process.process_id,
        "Order:", process.order_id,
        "Waiting:", process.waiting_time,
        "Turnaround:", process.turnaround_time,
        "Completion:", process.completion_time
    )


print("\n========== SJF ==========")

result = scheduler.sjf(processes)

for process in result:
    print(
        process.process_id,
        "Order:", process.order_id,
        "Waiting:", process.waiting_time,
        "Turnaround:", process.turnaround_time,
        "Completion:", process.completion_time
    )


print("\n========== PRIORITY ==========")

result = scheduler.priority(processes)

for process in result:
    print(
        process.process_id,
        "Order:", process.order_id,
        "Waiting:", process.waiting_time,
        "Turnaround:", process.turnaround_time,
        "Completion:", process.completion_time
    )


print("\n========== ROUND ROBIN ==========")

result = scheduler.round_robin(processes, 2)

for process in result:
    print(
        process.process_id,
        "Order:", process.order_id,
        "Waiting:", process.waiting_time,
        "Turnaround:", process.turnaround_time,
        "Completion:", process.completion_time
    )
print("\n========== RESOURCE MANAGEMENT ==========")

resource_manager = ResourceManager()

print("Initial Resources:")
print(resource_manager.get_all_resources())

print("\nP1 requests Worker:")
print(resource_manager.request_resource("P1", "Worker"))

print("P1 requests Forklift:")
print(resource_manager.request_resource("P1", "Forklift"))

print("\nResources after allocation:")
print(resource_manager.get_all_resources())

print("\nP1 allocated resources:")
print(resource_manager.get_allocated_resources("P1"))

print("\nP1 releases Forklift:")
print(resource_manager.release_resource("P1", "Forklift"))

print("\nResources after release:")
print(resource_manager.get_all_resources())
from os_modules.synchronization import WarehouseSynchronizer

print("\n========== MULTITHREADING & SYNCHRONIZATION ==========")

synchronizer = WarehouseSynchronizer()

synchronizer.run_parallel_processes(
    ["P1", "P2", "P3"]
)
from os_modules.deadlock_detector import DeadlockDetector

print("\n========== DEADLOCK DETECTION ==========")

from os_modules.deadlock_detector import DeadlockDetector

deadlock_detector = DeadlockDetector()

allocation = [
    [1, 0],
    [0, 1]
]

request = [
    [0, 1],
    [1, 0]
]

available = [0, 0]
process_ids = ["P1", "P2"]

result = deadlock_detector.detect_deadlock(
    allocation,
    request,
    available,
    process_ids
)

print("Deadlock Detected:", result["deadlock_detected"])
print("Deadlocked Processes:", result["deadlocked_processes"])
print("Safe Sequence:", result["safe_sequence"])

assert result["deadlock_detected"] is True
assert set(result["deadlocked_processes"]) == {"P1", "P2"}

print("DEADLOCK DETECTION TEST PASSED")


from os_modules.banker import Banker

print("\n========== BANKER'S ALGORITHM ==========")

from os_modules.banker import Banker

available = [3, 3, 2]

maximum = [
    [7, 5, 3],
    [3, 2, 2],
    [9, 0, 2],
    [2, 2, 2],
    [4, 3, 3]
]

allocation = [
    [0, 1, 0],
    [2, 0, 0],
    [3, 0, 2],
    [2, 1, 1],
    [0, 0, 2]
]

process_ids = ["P0", "P1", "P2", "P3", "P4"]

banker = Banker()

result = banker.check_safety(
    available.copy(),
    allocation,
    maximum,
    process_ids
)

print("Need Matrix:")
for i, process in enumerate(process_ids):
    need = [
        maximum[i][j] - allocation[i][j]
        for j in range(len(available))
    ]
    print(process, ":", need)

print("System Safe:", result["safe"])
print("Safe Sequence:", result["safe_sequence"])

assert result["safe"] is True
assert len(result["safe_sequence"]) == len(process_ids)

print("BANKER'S ALGORITHM TEST PASSED")
from os_modules.warehouse_engine import WarehouseEngine

print("\n========== WAREHOUSE ENGINE ==========")

engine = WarehouseEngine()

engine.create_order(
    "P10",
    "O110",
    0,
    5,
    1,
    ["Worker", "Forklift"]
)

print("\nOrders created:")
for process in engine.process_manager.get_all_processes():
    print(
        process.process_id,
        process.order_id,
        process.state
    )

print("\nScheduling orders:")

result = engine.schedule_orders("FCFS")

for process in result["processes"]:
    print(
        process.process_id,
        "Waiting:",
        process.waiting_time,
        "Completion:",
        process.completion_time
    )

print("\nAllocating resources:")

print(
    engine.allocate_resources(
        "P10",
        ["Worker", "Forklift"]
    )
)

print(
    "Available resources:",
    engine.resource_manager.get_all_resources()
)

print("\nRunning process:")

print(engine.run_process("P10"))

print("\nFinal status:")

process = engine.process_manager.get_process("P10")

print(
    process.process_id,
    process.state
)

print(
    "Available resources:",
    engine.resource_manager.get_all_resources()
)