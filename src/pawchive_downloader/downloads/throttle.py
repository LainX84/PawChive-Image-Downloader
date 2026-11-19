"""Bandwidth limiting and speed measurement for downloads."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol


class CancelFlag(Protocol):
    def is_set(self) -> bool: ...


class BandwidthLimiter:
    """Token bucket shared by every download: the *total* speed stays below the limit.

    A rate of 0 disables the limit. The rate can change while transfers run.
    """

    def __init__(self, bytes_per_second: float = 0, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleep
        self._rate = 0.0
        self._tokens = 0.0
        self._last = clock()
        self.set_rate(bytes_per_second)

    @property
    def rate(self) -> float:
        return self._rate

    def set_rate(self, bytes_per_second: float) -> None:
        with self._lock:
            self._rate = max(0.0, float(bytes_per_second))
            self._tokens = min(self._tokens, self._rate)
            self._last = self._clock()

    def consume(self, amount: int, cancel: CancelFlag | None = None) -> None:
        """Account for *amount* bytes; sleep as long as needed to respect the rate."""
        while True:
            with self._lock:
                rate = self._rate
                if rate <= 0:
                    return
                now = self._clock()
                self._tokens = min(rate, self._tokens + (now - self._last) * rate)  # burst: one second
                self._last = now
                self._tokens -= amount
                wait = -self._tokens / rate if self._tokens < 0 else 0.0
            if wait <= 0:
                return
            # Sleep in short slices so that pausing or a new limit applies quickly.
            slept = 0.0
            while slept < wait:
                if cancel is not None and cancel.is_set():
                    return
                step = min(0.2, wait - slept)
                self._sleep(step)
                slept += step
            return


class SpeedMeter:
    """Average speed over a sliding window (default: the last 4 seconds)."""

    def __init__(self, window: float = 4.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.window = window
        self._clock = clock
        self._samples: deque[tuple[float, int]] = deque()

    def add(self, done: int) -> None:
        now = self._clock()
        self._samples.append((now, done))
        while len(self._samples) > 2 and now - self._samples[0][0] > self.window:
            self._samples.popleft()

    def speed(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        (t0, d0), (t1, d1) = self._samples[0], self._samples[-1]
        if self._clock() - t1 > self.window:  # stalled
            return 0.0
        return max(0.0, (d1 - d0) / (t1 - t0)) if t1 > t0 else 0.0
