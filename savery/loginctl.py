import dbus

from . import utils


def register(config):
    lock_cmd = utils.get_action(config, 'loginctl', 'lock_action')
    unlock_cmd = utils.get_action(config, 'loginctl', 'unlock_action')

    def _on_lock():
        utils.Action.get(lock_cmd).run()

    def _on_unlock():
        utils.Action.get(unlock_cmd).run()

    bus = dbus.SystemBus()
    if lock_cmd:
        bus.add_signal_receiver(_on_lock, 'Lock',
                                'org.freedesktop.login1.Session')

    if unlock_cmd:
        bus.add_signal_receiver(_on_unlock, 'Unlock',
                                'org.freedesktop.login1.Session')
