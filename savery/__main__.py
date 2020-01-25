import argparse
import grp
import logging
import os
import sys

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from . import const, loginctl, screensaver, sleep, utils

DBusGMainLoop(set_as_default=True)


def configure_logger(config):
    logging.basicConfig(level=config['General']['log_level'],
                        format='%(asctime)s - %(message)s')


def main():
    parser = argparse.ArgumentParser(const.APP_NAME)

    parser.add_argument(
        '-c', '--config', nargs='?', type=str,
        help='Path to alternative config file. '
        'Defaults to "{}"'.format(const.DEFAULT_CONFIG),
        default=const.DEFAULT_CONFIG)

    args = parser.parse_args()

    if 'input' not in [grp.getgrgid(g).gr_name for g in os.getgroups()]:
        print(
            'Your user should be in the "input" group, as '
            'otherwise monitoring input devices will not work.',
            file=sys.stderr)
        sys.exit(1)

    config = utils.get_config(args.config)
    if not config:
        print('Invalid or missing config.')
        sys.exit(1)

    configure_logger(config)

    sleep.register(config)
    loginctl.register(config)
    screensaver.register(config)

    try:
        print('Use ctlr+c to exit...')
        GLib.MainLoop().run()

    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
