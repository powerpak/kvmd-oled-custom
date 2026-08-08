# ========================================================================== #
#                                                                            #
#    KVMD-OLED - A small OLED daemon for PiKVM.                              #
#                                                                            #
#    Copyright (C) 2018-2024  Maxim Devaev <mdevaev@gmail.com>               #
#                       2026  Theodore Pak                                   #
#                                                                            #
#    This program is free software: you can redistribute it and/or modify    #
#    it under the terms of the GNU General Public License as published by    #
#    the Free Software Foundation, either version 3 of the License, or       #
#    (at your option) any later version.                                     #
#                                                                            #
#    This program is distributed in the hope that it will be useful,         #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#    GNU General Public License for more details.                            #
#                                                                            #
#    You should have received a copy of the GNU General Public License       #
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.  #
#                                                                            #
# ========================================================================== #


import asyncio
import time

from kvmd.logging import get_logger

logger = get_logger(0)


# =====
class Buttons:
    """Watches GPIO buttons to wake the OLED after an inactivity timeout.

    The buttons are assumed to be wired active-low with the internal pull-up
    enabled -- that is, pressing a button ties its GPIO pin to ground, so a
    press reads as LOW. This is the convention used by the Waveshare and
    Adafruit 2.23" OLED HATs, whose three buttons live on BCM pins 16, 20 and
    21.

    The pin levels are **polled** with ``GPIO.input()`` rather than armed with
    edge-detection callbacks (``GPIO.add_event_detect``). Edge detection in
    RPi.GPIO is implemented through the legacy sysfs GPIO class
    (``/sys/class/gpio/export`` and the per-pin ``edge`` files), which is
    root-owned and therefore unavailable to the non-root ``kvmd-oled`` user --
    attempting it fails with "Failed to add edge detection". Polling, by
    contrast, only needs memory-mapped GPIO access via ``/dev/gpiomem``, the
    same path the display already uses, so it works with the permissions the
    daemon already has. The poll interval (default 50 ms) is far below human
    tap speed, so wake latency is imperceptible.

    RPi.GPIO is imported lazily inside ``__init__`` so the rest of the daemon
    does not gain a hard dependency on it. If the library or the GPIO hardware
    is unavailable, constructing this object raises and the caller is expected
    to treat ``--sleep-timeout`` as a fatal error rather than silently degrade.
    """

    def __init__(
        self,
        pins: list[int],
        poll_interval: float = 0.05,
    ) -> None:

        try:
            import RPi.GPIO as GPIO
        except (ImportError, RuntimeError) as ex:
            # ImportError: package not installed.
            # RuntimeError: RPi.GPIO refuses to load on non-Pi hardware.
            raise RuntimeError("RPi.GPIO is required for --sleep-timeout") from ex
        self.__gpio = GPIO

        self.__poll_interval = poll_interval
        self.__pins: list[int] = []

        # BCM numbering matches the --sleep-gpio defaults and the pin labels
        # printed on the HATs. setmode() is a no-op if BCM is already selected.
        GPIO.setmode(GPIO.BCM)
        try:
            for pin in pins:
                # pull_up_down=PUD_UP + active-low means a press pulls the line
                # to ground, so the pin reads LOW while the button is held.
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                self.__pins.append(pin)
        except Exception:
            # Clean up anything we already configured so we don't leave pins
            # claimed if construction fails partway through.
            self.__cleanup()
            raise

        logger.info("GPIO wake buttons (BCM, active-low, pull-up, polled): %s", pins)

    def __any_pressed(self) -> bool:
        GPIO = self.__gpio
        # Active-low: pressed == GPIO.LOW. Stop on the first held pin so we
        # don't read every pin when one is enough. GPIO.input() is a fast
        # memory-mapped register read, safe to call inline from the loop.
        for pin in self.__pins:
            if GPIO.input(pin) == GPIO.LOW:
                return True
        return False

    async def wait_for_press(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for any button to be pressed.

        Returns True as soon as a pressed (LOW) button is seen -- including one
        already held when this method is called -- otherwise returns False once
        the timeout has elapsed. Polling runs at ``poll_interval`` granularity.
        """
        if self.__any_pressed():
            return True
        if timeout <= 0:
            return False
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(self.__poll_interval, remaining))
            if self.__any_pressed():
                return True
            if time.monotonic() >= deadline:
                return False

    def __cleanup(self) -> None:
        GPIO = self.__gpio
        for pin in self.__pins:
            try:
                GPIO.cleanup(pin)
            except Exception:
                pass
        self.__pins = []

    def close(self) -> None:
        self.__cleanup()
