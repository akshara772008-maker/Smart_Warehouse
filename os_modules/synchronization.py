import threading
import time


class WarehouseSynchronizer:

    def __init__(self):
        self.lock = threading.Lock()
        self.active_workers = 0

    def start_work(self, process_id):
        with self.lock:
            self.active_workers += 1
            print(
                f"{process_id} started work | "
                f"Active workers: {self.active_workers}"
            )

        try:
            time.sleep(3)
        finally:
            with self.lock:
                self.active_workers -= 1
                print(
                    f"{process_id} completed work | "
                    f"Active workers: {self.active_workers}"
                )

    def run_parallel_processes(self, process_ids):
        threads = []

        for process_id in process_ids:
            thread = threading.Thread(
                target=self.start_work,
                args=(process_id,)
            )

            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()