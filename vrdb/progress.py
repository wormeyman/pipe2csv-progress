"""Progress reporting in the same style as to_csv_progress.py."""

import sys
import time


def human(n: float) -> str:
    for unit in ("", "K", "M", "B"):
        if abs(n) < 1000:
            return f"{n:.0f}{unit}"
        n /= 1000.0
    return f"{n:.1f}T"


class Progress:
    """Prints rows, rate, percent and ETA every `tick` rows.

    `clock` is injectable so tests do not depend on wall time.
    """

    def __init__(self, label, total_bytes=None, tick=100_000, stream=None, clock=time.monotonic):
        self.label = label
        self.total_bytes = total_bytes
        self.tick = tick
        self.stream = stream if stream is not None else sys.stderr
        self.clock = clock
        self.start = clock()
        self._next_tick = tick

    def _elapsed(self) -> float:
        return max(self.clock() - self.start, 1e-6)

    def update(self, rows: int, bytes_read: int) -> None:
        if rows < self._next_tick:
            return
        self._next_tick = ((rows // self.tick) + 1) * self.tick
        elapsed = self._elapsed()
        rate = rows / elapsed
        pct = eta = ""
        if self.total_bytes and bytes_read > 0:
            fraction = bytes_read / self.total_bytes
            pct = f" {fraction * 100:5.1f}%"
            remaining = max(elapsed / fraction - elapsed, 0)
            eta = (
                f" ETA {int(remaining // 3600):02d}:"
                f"{int((remaining % 3600) // 60):02d}:"
                f"{int(remaining % 60):02d}"
            )
        print(
            f"[{self.label}] rows={human(rows)} rate={rate:,.0f}/s{pct}{eta}",
            file=self.stream,
            flush=True,
        )

    def finish(self, rows: int) -> None:
        elapsed = self._elapsed()
        rate = rows / elapsed
        print(
            f"[{self.label}] done: {rows:,} rows in {elapsed:,.1f}s ({rate:,.0f}/s)",
            file=self.stream,
            flush=True,
        )
