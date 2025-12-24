import time


class Timer:
    """
    A context timer! You can use in context OR explicitly start/stop.
    t = Timer()
    with t:
       do_stuff()
    """

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def stop(self):
        self.end_time = time.perf_counter()
        self.elapsed_time = self.end_time - self.start_time

    def start(self):
        self.start_time = time.perf_counter()
