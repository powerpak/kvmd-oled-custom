# kvmd-oled-custom

This is a modification of the `kvmd-oled` daemon provided in the [PiKVM project](https://github.com/pikvm/pikvm), principally to add support for different screens--specifically those with the SSD1305 driver, such as the:

- [Waveshare 17009 2.23" OLED Display Hat](https://www.pishop.us/product/128-32-2-23inch-oled-display-hat-for-raspberry-pi/)
- [Adafruit 2.23" Monochrome OLED Bonnet](https://learn.adafruit.com/adafruit-2-23-monochrome-oled-bonnet)

This is mostly useful if you are building your own PiKVM, as in the [DIY PiKVM v2](https://docs.pikvm.org/v2/), and you want to add one of these OLED screens.

The `kvmd-oled` daemon included with PiKVM uses the [luma.oled](https://github.com/rm-hull/luma.oled) Python library, which doesn't support them natively. A potential fix is described [in a GitHub issue](https://github.com/rm-hull/luma.oled/issues/309#issuecomment-935248846) that builds off the SSD1306 driver code, but it hasn't been merged.

## Installation

### Download the code

Obtain shell access on your PiKVM (either via the web terminal or SSH) and run `su -` to become root. Then clone this repo and verify that the main script prints its help text:

```
# rw
# cd /opt
# git clone https://github.com/powerpak/kvmd-oled-custom
# cd kvmd-oled-custom
# ./kvmd-oled-custom --help
```

### Configure GPIO and permissions

I typically repurpose the preconfigured `kvmd-oled` user on the PiKVM OS to run this daemon. The daemon's user must be given access to GPIO and either I2C or SPI, depending on the way the screen was connected. For instance, the Waveshare screen is wired for SPI out of the box, but you can [re-solder six resistors](https://www.waveshare.com/wiki/2.23inch_OLED_HAT#PINS) to make it use I2C.

The Pi's firmware must have I2C and/or SPI enabled using a `dtparam` line in `/boot/config.txt`, as in [this example](https://www.raspberrypi.com/documentation/computers/configuration.html#part3.2). Then, the user must be in the `spi`, `i2c`, and `gpio` groups to properly access GPIO.

Furthermore, in order for the daemon to access the `/run/kvmd/kvmd.sock` Unix socket and authenticate with `kvmd`, the daemon's user must also be part of the `kvmd` and `kvmd-selfauth` groups. The `kvmd-oled` user is usually already in these groups, but you can verify and fix if necessary with:

```
# groups kvmd-oled            # look for: spi i2c gpio kvmd kvmd-oled
# usermod -aG gpio kvmd-oled  # repeat for any other missing groups
```

On my PiKVM, the permissions for `/dev/gpiomem` needed to be altered from 0600 (root only) to 0660 (granting access to the whole `gpio` group).

```
# echo 'SUBSYSTEM=="gpiomem", KERNEL=="gpiomem", GROUP="gpio", MODE="0660"' | \
    udev/rules.d/99-gpiomem.rules
# udevadm control --reload-rules
# udevadm trigger
# ls -al /dev/gpiomem  # should show: crw-rw---- 1 root gpio ...
```

### Test and configure the main script

At this point it is worth a `reboot` to see if all the changes stick. Then try invoking the script as the `kvmd-oled` user to see if it can put text on the OLED screen, and modify the arguments to the script as needed:

```
# sudo -u kvmd-oled ./kvmd-oled-custom \
    --display ssd1305 --interface spi --width 128 --height 32 --rotate 2
```

### Prevent screen burn-in (optional sleep timeout)

By default the OLED stays illuminated at all times. To reduce the risk of
burn-in you can have the screen automatically clear itself after a period of
inactivity and wake back up when a button is pressed. Add the `--sleep-timeout`
option (in seconds) to the command line:

```
# sudo -u kvmd-oled ./kvmd-oled-custom \
    --display ssd1305 --interface spi --width 128 --height 32 --rotate 2 \
    --sleep-timeout 120
```

After 120 seconds without a button press the screen goes blank. The first
button press wakes it again, and every subsequent press resets the timer, so
the screen stays lit while the device is in use and only sleeps once you stop
interacting with it. Pass `0` (the default) to disable the feature entirely.

The wake buttons are read with [RPi.GPIO](https://sourceforge.net/p/raspberry-gpio-python/wiki/Home/)
and are assumed to be wired active-low with the internal pull-up enabled (a
press ties the GPIO pin to ground). This matches the three buttons on the
Waveshare and Adafruit 2.23" OLED HATs, which live on BCM pins **16, 20 and 21**
-- the default. To use different pins, pass `--sleep-gpio`:

```
--sleep-timeout 120 --sleep-gpio 5 6 12 13
```

`RPi.GPIO` is only imported when `--sleep-timeout` is non-zero, so the rest of
the daemon keeps working without it. If `RPi.GPIO` is missing or the GPIO
hardware is inaccessible, the daemon logs an error and falls back to leaving
the screen always on rather than failing to start. Make sure the `RPi.GPIO`
package is installed for the `kvmd-oled` user, and that the user is in the
`gpio` group (already set up in the previous section).

### Create a `systemd` service

If that works, you can create a `systemd` service (modified from the existing `kvmd-oled*` services) to start the script on boot and manage its lifecycle:

```
# rw
# cd /etc/systemd/system
# cp /usr/lib/systemd/system/kvmd-oled.service kvmd-oled-custom.service
# cp /usr/lib/systemd/system/kvmd-oled-shutdown.service kvmd-oled-custom-shutdown.service
# cp /usr/lib/systemd/system/kvmd-oled-reboot.service kvmd-oled-custom-reboot.service
```

Modify these `.service` files to execute `/opt/kvmd-oled-custom/kvmd-oled-custom` with the arguments you prefer. The top of `kvmd-oled-custom.service` should be adjusted to start only after `kvmd` and when the correct interface in `/dev` is present:

```
[Unit]
Description=PiKVM - A small OLED daemon
After=systemd-modules-load.service kvmd.service
Wants=kvmd.service
ConditionPathExists=/dev/spidev0.0  # If you are using SPI; for I2C, use /dev/i2c-1
```

Also, ensure that the `ExecStart` lines in the `-shutdown` and `-reboot` services are finding the PID of the `kvmd-oled-custom` service, not `kvmd-oled`.

Finally, load and enable these services:

```
# systemctl daemon-reload
# systemctl enable kvmd-oled-custom kvmd-oled-custom-shutdown kvmd-oled-custom-reboot
# systemctl start kvmd-oled-custom
```

If that worked, `systemctl status kvmd-oled-custom` should show that the service is running and the most recent log message should be "INFO --- Polling KVMD ..."

## License

This code was forked from the [PiKVM project](https://github.com/pikvm/pikvm) and is licensed similarly, under the GPL v3. See LICENSE.