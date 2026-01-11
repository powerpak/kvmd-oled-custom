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

The Linux kernel must have I2C and/or SPI enabled with a `dtparam` line in `/boot/config.txt`, as in [this example](https://www.raspberrypi.com/documentation/computers/configuration.html#part3.2). Then, the user must be in the `spi`, `i2c`, and `gpio` groups to properly access GPIO.

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

### Create a `systemd` service

If that works, you can create a `systemd` service (modified from the existing `kvmd-oled*` services) to start the script on boot and manage its lifecycle:

```
# cd /etc/systemd/system
# cp /usr/lib/systemd/system/kvmd-oled.service kvmd-oled-custom.service
# cp /usr/lib/systemd/system/kvmd-oled-shutdown.service kvmd-oled-custom-shutdown.service
# cp /usr/lib/systemd/system/kvmd-oled-reboot.service kvmd-oled-custom-reboot.service
```

Modify these `.service` files to point to `/opt/kvmd-oled-custom/kvmd-oled-custom` and use the extra arguments you prefer. If you are using SPI and not I2C, you need to make this change to `kvmd-oled-custom.service`:

```
[Unit]
ConditionPathExists=/dev/spidev0.0  # rather than /dev/i2c-1
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