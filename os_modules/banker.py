class Banker:
    @staticmethod
    def _validate_vector(values, name):
        if not isinstance(values, (list, tuple)):
            raise ValueError(f"{name} must be a list")
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in values
        ):
            raise ValueError(f"{name} must contain non-negative integers")
        return list(values)

    @classmethod
    def _validate_matrix(cls, matrix, name, resource_count):
        if not isinstance(matrix, (list, tuple)):
            raise ValueError(f"{name} must be a matrix")
        rows = []
        for row in matrix:
            if not isinstance(row, (list, tuple)):
                raise ValueError(f"Each {name} row must be a list")
            validated_row = cls._validate_vector(row, f"{name} row")
            if len(validated_row) != resource_count:
                raise ValueError("Resource matrix dimensions do not match")
            rows.append(validated_row)
        return rows

    def calculate_need(self, maximum, allocation):
        if not isinstance(maximum, (list, tuple)) or not isinstance(
            allocation, (list, tuple)
        ):
            raise ValueError("Maximum and allocation must be matrices")
        if len(maximum) != len(allocation):
            raise ValueError(
                "Maximum and allocation matrices must have equal rows"
            )

        maximum_rows = []
        allocation_rows = []
        resource_count = None
        for maximum_row, allocation_row in zip(maximum, allocation):
            if not isinstance(maximum_row, (list, tuple)) or not isinstance(
                allocation_row, (list, tuple)
            ):
                raise ValueError("Each matrix row must be a list")
            if resource_count is None:
                resource_count = len(maximum_row)
            if (
                len(maximum_row) != len(allocation_row)
                or len(maximum_row) != resource_count
            ):
                raise ValueError(
                    "Maximum and allocation matrices must have equal columns"
                )
            maximum_rows.append(
                self._validate_vector(maximum_row, "Maximum row")
            )
            allocation_rows.append(
                self._validate_vector(allocation_row, "Allocation row")
            )

        need = []
        for maximum_row, allocation_row in zip(
            maximum_rows, allocation_rows
        ):
            if any(
                maximum_row[index] < allocation_row[index]
                for index in range(len(maximum_row))
            ):
                raise ValueError("Allocation cannot exceed maximum demand")
            need.append([
                maximum_row[index] - allocation_row[index]
                for index in range(len(maximum_row))
            ])
        return need

    def check_safety(self, available, allocation, maximum, process_ids=None):
        available_values = self._validate_vector(available, "Available resources")
        allocation_rows = self._validate_matrix(
            allocation, "Allocation", len(available_values)
        )
        maximum_rows = self._validate_matrix(
            maximum, "Maximum", len(available_values)
        )
        process_count = len(allocation_rows)

        if len(maximum_rows) != process_count:
            raise ValueError(
                "Maximum and allocation matrices must have equal rows"
            )
        if process_ids is None:
            process_ids = [f"P{i + 1}" for i in range(process_count)]
        elif not isinstance(process_ids, (list, tuple)):
            raise ValueError("Process IDs must be a list")
        if len(process_ids) != process_count:
            raise ValueError("Process ID count does not match")

        need = self.calculate_need(maximum_rows, allocation_rows)
        work = available_values.copy()
        finish = [False] * process_count
        safe_sequence = []

        while len(safe_sequence) < process_count:
            found = False
            for i in range(process_count):
                if not finish[i] and all(
                    need[i][j] <= work[j]
                    for j in range(len(work))
                ):
                    work = [
                        work[j] + allocation_rows[i][j]
                        for j in range(len(work))
                    ]
                    finish[i] = True
                    safe_sequence.append(process_ids[i])
                    found = True
            if not found:
                break

        return {
            "safe": all(finish),
            "safe_sequence": safe_sequence,
            "need": need,
            "final_work": work.copy(),
            "unfinished_processes": [
                process_ids[i]
                for i in range(process_count)
                if not finish[i]
            ]
        }

    def request_resources(
        self, process_index, request, available, allocation, maximum,
        process_ids=None
    ):
        if not all(
            isinstance(matrix, list)
            for matrix in (allocation, maximum)
        ):
            raise ValueError(
                "Allocation and maximum must be mutable lists for requests"
            )
        if not isinstance(available, list):
            raise ValueError(
                "Available resources must be a mutable list for requests"
            )
        if (
            not isinstance(process_index, int)
            or isinstance(process_index, bool)
            or process_index < 0
            or process_index >= len(allocation)
        ):
            raise ValueError("Invalid process index")

        request_values = self._validate_vector(request, "Request")
        available_values = self._validate_vector(
            available, "Available resources"
        )
        if len(request_values) != len(available_values):
            raise ValueError("Request dimensions do not match")

        allocation_rows = self._validate_matrix(
            allocation, "Allocation", len(available_values)
        )
        maximum_rows = self._validate_matrix(
            maximum, "Maximum", len(available_values)
        )
        if len(maximum_rows) != len(allocation_rows):
            raise ValueError(
                "Maximum and allocation matrices must have equal rows"
            )
        if process_index >= len(allocation_rows):
            raise ValueError("Invalid process index")

        need = self.calculate_need(maximum_rows, allocation_rows)
        if any(
            request_values[j] > need[process_index][j]
            for j in range(len(request_values))
        ):
            return {
                "granted": False,
                "message": "Request exceeds the process maximum demand"
            }
        if any(
            request_values[j] > available_values[j]
            for j in range(len(request_values))
        ):
            return {
                "granted": False,
                "message": "Resources are not currently available"
            }

        new_available = [
            available_values[j] - request_values[j]
            for j in range(len(request_values))
        ]
        new_allocation = [row.copy() for row in allocation_rows]
        for j in range(len(request_values)):
            new_allocation[process_index][j] += request_values[j]

        result = self.check_safety(
            new_available,
            new_allocation,
            maximum_rows,
            process_ids
        )
        if result["safe"]:
            available[:] = new_available
            allocation[:] = new_allocation
            return {
                "granted": True,
                "message": "Request granted; system remains in a safe state",
                "safe_sequence": result["safe_sequence"]
            }
        return {
            "granted": False,
            "message": "Request denied; system would enter an unsafe state",
            "safe_sequence": result["safe_sequence"]
        }
