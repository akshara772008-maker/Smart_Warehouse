
class DeadlockDetector:
    def detect_deadlock(self, allocation, request, available, process_ids=None):
        if not isinstance(allocation, (list, tuple)) or not isinstance(
            request, (list, tuple)
        ):
            raise ValueError("Allocation and request must be matrices")
        if not isinstance(available, (list, tuple)):
            raise ValueError("Available resources must be a list")
        process_count = len(allocation)

        if len(request) != process_count:
            raise ValueError("Allocation and request matrices must have equal rows")

        resource_count = len(available)
        matrices = (allocation, request, [available])
        validated = []
        for matrix in matrices:
            rows = []
            for row in matrix:
                if not isinstance(row, (list, tuple)):
                    raise ValueError("Each matrix row must be a list")
                if len(row) != resource_count:
                    raise ValueError("Resource matrix dimensions do not match")
                if any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                    for value in row
                ):
                    raise ValueError(
                        "Resource counts must be non-negative integers"
                    )
                rows.append(list(row))
            validated.append(rows)

        allocation, request, available_values = validated
        available_values = available_values[0]

        if process_ids is None:
            process_ids = [f"P{i + 1}" for i in range(process_count)]
        elif not isinstance(process_ids, (list, tuple)):
            raise ValueError("Process IDs must be a list")
        if len(process_ids) != process_count:
            raise ValueError("Process ID count does not match")

        work = available_values.copy()
        initial_work = work.copy()
        finish = [not any(row) for row in allocation]
        safe_sequence = []
        work_trace = []

        while True:
            found = False

            for i in range(process_count):
                if not finish[i] and all(request[i][j] <= work[j] for j in range(len(work))):
                    work_before = work.copy()
                    work = [
                        work[j] + allocation[i][j]
                        for j in range(len(work))
                    ]
                    finish[i] = True
                    safe_sequence.append(process_ids[i])
                    work_trace.append({
                        "process_id": process_ids[i],
                        "work_before": work_before,
                        "released_allocation": allocation[i].copy(),
                        "work_after": work.copy()
                    })
                    found = True

            if not found:
                break

        deadlocked = [
            process_ids[i]
            for i in range(process_count)
            if not finish[i]
        ]

        return {
            "deadlock_detected": bool(deadlocked),
            "deadlocked_processes": deadlocked,
            "safe_sequence": safe_sequence,
            "initial_work": initial_work,
            "final_work": work.copy(),
            "work_trace": work_trace,
            "blocked_processes": [
                {
                    "process_id": process_ids[i],
                    "request": request[i].copy(),
                    "work": work.copy(),
                    "unavailable_resources": [
                        resource_index
                        for resource_index in range(len(work))
                        if request[i][resource_index] > work[resource_index]
                    ]
                }
                for i in range(process_count)
                if not finish[i]
            ]
        }