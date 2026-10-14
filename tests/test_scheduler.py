
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

print("\n========== CPU SCHEDULING TESTS ==========")

algorithms = {
    "FCFS": scheduler.fcfs,
    "SJF": scheduler.sjf,
    "PRIORITY": scheduler.priority
}

for name, algorithm in algorithms.items():
    result = algorithm(processes.copy())

    print(f"\n{name} Scheduling")
    print("Execution order:", [p.process_id for p in result])
    print("Waiting times:", [p.waiting_time for p in result])
    print("Turnaround times:", [p.turnaround_time for p in result])

    assert len(result) == 3
    assert all(p.completion_time >= 0 for p in result)

    print("RESULT: PASSED")

print("\n========== TESTS COMPLETED ==========")