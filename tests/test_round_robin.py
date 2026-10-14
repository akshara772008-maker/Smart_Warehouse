
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from os_modules.process_manager import ProcessManager
from os_modules.scheduler import Scheduler

manager = ProcessManager()
scheduler = Scheduler()

manager.create_process("P401", "O401", 0, 5, 2, [])
manager.create_process("P402", "O402", 1, 3, 1, [])
manager.create_process("P403", "O403", 2, 2, 3, [])

processes = manager.get_all_processes()

print("\n========== ROUND ROBIN TEST ==========")

quantum = 2
result = scheduler.round_robin(processes, quantum)

print("Time Quantum:", quantum)
print("Completion Order:", [p.process_id for p in result])

for process in sorted(result, key=lambda p: p.process_id):
    print(
        f"{process.process_id}: "
        f"Completion={process.completion_time}, "
        f"Waiting={process.waiting_time}, "
        f"Turnaround={process.turnaround_time}"
    )

assert [p.process_id for p in result] == ["P403", "P402", "P401"]

expected = {
    "P401": (10, 5, 10),
    "P402": (9, 5, 8),
    "P403": (6, 2, 4)
}

for process in result:
    assert (
        process.completion_time,
        process.waiting_time,
        process.turnaround_time
    ) == expected[process.process_id]

print("\nROUND ROBIN TEST PASSED")