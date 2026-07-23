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

from kvmd.logging import get_logger

logger = get_logger(0)


# =====
class Buttons:
    """Watches GPIO buttons to wake the OLED after an inactivity timeout.

    The buttons are assumed to be wired active-low with the internal pull-up
    enabled -- that is, pressing a button ties its GPIO pin to ground. This is
    the convention used by the Waveshare and Adafruit 2.23" OLED HATs, whose
    three buttons live on BCM pins 16, 20 and 21.

    RPi.GPIO is imported lazily inside __init__ so the rest of the daemon does
    not gain a hard dependency on it. If the library (or the GPIO hardware) is
    unavailable, constructing this object raises and the caller is expected to
    fall back to running with the screen always on.
    """

    def __init__(
        self,
        pins: list[int],
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:

        try:
            import RPi.GPIO as GPIO
        except (ImportError, RuntimeError) as ex:
            # ImportError: package not installed.
            # RuntimeError: RPi.GPIO refuses to load on non-Pi hardware.
            raise RuntimeError("RPi.GPIO is required for --sleep-timeout") from ex
        self.__gpio = GPIO

        self.__loop = loop or asyncio.get_running_loop()
        self.__event = asyncio.Event()
        self.__pins: list[int] = []

        # BCM numbering matches the --sleep-gpio defaults and the pin labels
        # printed on the HATs. setmode() is a no-op if BCM is already selected.
        GPIO.setmode(GPIO.BCM)
        for pin in pins:
            # pull_up_down=PUD_UP + active-low means a press pulls the line to
            # ground, producing a falling edge that we treat as a "press".
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                pin, GPIO.FALLING,
                callback=self.__on_press,
                bouncetime=100,  # 0.1 s of software debounce
            )
            self.__pins.append(pin)

        logger.info("GPIO wake buttons (BCM, active-low, pull-up): %s", pins)

    def __on_press(self, _pin: int) -> None:
        # Invoked from RPi.GPIO's background thread, so marshal the signal
        # back into the asyncio event loop thread-safely.
        try:
            self.__loop.call_soon_threadsafe(self.__event.set)
        except RuntimeError:
            pass  # The loop has already been closed during shutdown.

    def __consume(self) -> bool:
        if self.__event.is_set():
            self.__event.clear()
            return True
        return False

    async def wait_for_press(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for any button to be pressed.

        Returns True as soon as a press is detected (including one that was
        already pending when this method is called), otherwise returns False
        once the timeout has elapsed.
        """
        if self.__consume():
            return True
        if timeout <= 0:
            return False
        try:
            await asyncio.wait_for(self.__event.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return self.__consume()

    def close(self) -> None:
        GPIO = self.__gpio
        for pin in self.__pins:
            try:
                GPIO.remove_event_detect(pin)
            except Exception:
                pass
            try:
                GPIO.cleanup(pin)
            except Exception:
                pass
        self.__pins = []
