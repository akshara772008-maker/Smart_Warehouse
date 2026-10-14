class Scheduler:

    def fcfs(self, processes):

        processes = sorted(
            processes,
            key=lambda process: (
                process.arrival_time,
                process.process_id
            )
        )

        current_time = 0

        for process in processes:

            if current_time < process.arrival_time:
                current_time = process.arrival_time

            process.waiting_time = (
                current_time - process.arrival_time
            )

            current_time += process.burst_time

            process.completion_time = current_time

            process.turnaround_time = (
                process.completion_time
                - process.arrival_time
            )

        return processes

    def sjf(self, processes):

        processes = processes.copy()

        completed = []
        current_time = 0

        while processes:

            available = [
                process
                for process in processes
                if process.arrival_time <= current_time
            ]

            if not available:
                current_time = min(
                    process.arrival_time
                    for process in processes
                )
                continue

            process = min(
                available,
                key=lambda process: (
                    process.burst_time,
                    process.arrival_time,
                    process.process_id
                )
            )

            processes.remove(process)

            process.waiting_time = (
                current_time - process.arrival_time
            )

            current_time += process.burst_time

            process.completion_time = current_time

            process.turnaround_time = (
                process.completion_time
                - process.arrival_time
            )

            completed.append(process)

        return completed

    def priority(self, processes):

        processes = processes.copy()

        completed = []
        current_time = 0

        while processes:

            available = [
                process
                for process in processes
                if process.arrival_time <= current_time
            ]

            if not available:
                current_time = min(
                    process.arrival_time
                    for process in processes
                )
                continue

            process = min(
                available,
                key=lambda process: (
                    process.priority,
                    process.arrival_time,
                    process.process_id
                )
            )

            processes.remove(process)

            process.waiting_time = (
                current_time - process.arrival_time
            )

            current_time += process.burst_time

            process.completion_time = current_time

            process.turnaround_time = (
                process.completion_time
                - process.arrival_time
            )

            completed.append(process)

        return completed

    def round_robin(self, processes, quantum=2):
        if (
            not isinstance(quantum, int)
            or isinstance(quantum, bool)
            or quantum <= 0
        ):
            raise ValueError("Round Robin time quantum must be a positive integer")

        processes = sorted(
            processes,
            key=lambda process: (
                process.arrival_time,
                process.process_id
            )
        )

        queue = []
        completed = []

        current_time = 0
        index = 0

        for process in processes:
            process.remaining_time = process.burst_time

        while queue or index < len(processes):

            while (
                index < len(processes)
                and processes[index].arrival_time <= current_time
            ):
                queue.append(processes[index])
                index += 1

            if not queue:

                current_time = processes[index].arrival_time
                continue

            process = queue.pop(0)

            execution_time = min(
                quantum,
                process.remaining_time
            )

            current_time += execution_time

            process.remaining_time -= execution_time

            while (
                index < len(processes)
                and processes[index].arrival_time <= current_time
            ):
                queue.append(processes[index])
                index += 1

            if process.remaining_time > 0:

                queue.append(process)

            else:

                process.completion_time = current_time

                process.turnaround_time = (
                    process.completion_time
                    - process.arrival_time
                )

                process.waiting_time = (
                    process.turnaround_time
                    - process.burst_time
                )

                completed.append(process)

        return completed
    
    def schedule(self, process_manager, algorithm="FCFS", time_quantum=2):
        if not isinstance(algorithm, str):
            raise ValueError("Scheduling algorithm must be a string")

        processes = (
            process_manager.get_all_processes()
            if hasattr(process_manager, "get_all_processes")
            else list(process_manager)
        )

        algorithm = algorithm.upper().replace("-", "_").replace(" ", "_")

        if algorithm == "FCFS":
            return self.fcfs(processes)
        elif algorithm == "SJF":
            return self.sjf(processes)
        elif algorithm in ("PRIORITY", "PRIORITY_SCHEDULING"):
            return self.priority(processes)
        elif algorithm in ("ROUND_ROBIN", "ROUNDROBIN", "RR"):
            return self.round_robin(processes, time_quantum)
        else:
            raise ValueError(f"Unknown scheduling algorithm: {algorithm}")
