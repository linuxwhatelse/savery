import os
import time

import dbus

from . import const, utils


class SleepInhibitor:
    __instances = {}

    _name = None
    _proxy = None

    __inhibitor = None
    _fd = None

    def __init__(self, name):
        self._name = name

        bus = dbus.SystemBus()
        self._proxy = bus.get_object('org.freedesktop.login1',
                                     '/org/freedesktop/login1')

    @classmethod
    def get(cls, name):
        if name not in cls.__instances:
            cls.__instances[name] = cls(name)
        return cls.__instances[name]

    @property
    def _inhibitor(self):
        if not self._fd:
            self.__inhibitor = self._proxy.Inhibit(
                'sleep', self._name, self._name, 'delay',
                dbus_interface='org.freedesktop.login1.Manager')
        return self.__inhibitor

    def list(self):
        return self._proxy.ListInhibitors(
            dbus_interface='org.freedesktop.login1.Manager')

    def take(self):
        try:
            self._fd = self._inhibitor.take()
        except ValueError:
            self._fd = None
            raise

    def release(self):
        if not self._fd:
            return

        os.close(self._fd)
        self._fd = None


def register(config):
    inhibitor = SleepInhibitor.get(const.APP_NAME)

    cmd = utils.get_action(config, 'Sleep', 'sleep_action')
    delay = int(config['Sleep']['sleep_delay'])

    def _on_sleep(start):
        if not start:
            inhibitor.take()
            return

        utils.Action.get(cmd).run()
        time.sleep(delay)

        inhibitor.release()

    bus = dbus.SystemBus()
    bus.add_signal_receiver(_on_sleep, 'PrepareForSleep',
                            'org.freedesktop.login1.Manager')

    # Initial inhibit (important)
    inhibitor.take()
