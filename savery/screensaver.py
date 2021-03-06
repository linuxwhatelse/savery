import json
import logging
import os
import re
import sys
import threading
import time

import dbus
import dbus.service
import Xlib
import Xlib.display
import Xlib.protocol.event
import Xlib.Xatom

from . import const, utils

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 'asyncio_overwrite'))

import evdev  # noqa: E402, isort:skip
from evdev.ecodes import ecodes  # noqa: E402, isort:skip

LOGGER = logging.getLogger(__name__)


class ScreenSaver(dbus.service.Object):
    __instances = {}

    input_reset_delay = 3
    """int: When input is detected, only reset ever `input_reset_delay` sec.
        to keep cpu-usage low."""

    _lock_action = None
    _lock_sec = None

    _idle_action = None
    _idle_reset_action = None
    _idle_sec = None
    _idle_sec_locked = None

    _idle_reset_ignore = None
    _inhibit_on_fullscreen = True

    _enter_fullscreen_action = None
    _leave_fullscreen_action = None

    __inhibit_count = 0
    __is_active = False
    __active_since = None
    __idle_since = None
    __is_fullscreen = False

    __fs_inhibit_cookie = -1

    __monitor = None
    __cmd_timer = None
    __mem = None

    def __init__(self, path):
        self.__cmd_timer = {}
        self.__mem = []

        # Aquire ScreenSaver name on session-bus
        bus = dbus.SessionBus()
        self.__mem.append(dbus.service.BusName(const.SS_DBUS_NAME, bus))

        dbus.service.Object.__init__(self, bus, path)

    @classmethod
    def get(cls, path):
        if path not in cls.__instances:
            cls.__instances[path] = cls(path)
        return cls.__instances[path]

    def configure(self, lock_cmd=None, lock_sec=0, idle_cmd=None,
                  idle_reset_cmd=None, idle_sec=0, idle_sec_locked=0,
                  idle_reset_ignore=None, inhibit_on_fullscreen=True,
                  enter_fullscreen_cmd=None, leave_fullscreen_cmd=None):
        if lock_cmd:
            self._lock_action = utils.Action.get(lock_cmd)
        self._lock_sec = lock_sec

        if idle_cmd:
            self._idle_action = utils.Action.get(idle_cmd)

        if idle_reset_cmd:
            self._idle_reset_action = utils.Action.get(idle_reset_cmd)

        self._idle_sec = idle_sec
        self._idle_sec_locked = idle_sec_locked

        self._idle_reset_ignore = idle_reset_ignore
        self._inhibit_on_fullscreen = inhibit_on_fullscreen

        if enter_fullscreen_cmd:
            self._enter_fullscreen_action = utils.Action.get(
                enter_fullscreen_cmd)

        if leave_fullscreen_cmd:
            self._leave_fullscreen_action = utils.Action.get(
                leave_fullscreen_cmd)

    def start(self):
        if self.__monitor:
            raise RuntimeError('Already started!')

        self.__monitor = threading.Thread(target=self._monitor)
        self.__monitor.daemon = True
        self.__monitor.start()

    @property
    def _idle_sec_current(self):
        if self._idle_sec_locked == 0:
            return self._idle_sec

        elif self._lock_action and self._lock_action.is_running():
            return self._idle_sec_locked

        else:
            return self._idle_sec

    def _should_ignore(self, ignore_list, wm_class=None, wm_name=None):
        def xstr(s):
            return s or ''

        wm_name = xstr(wm_name)
        wm_inst, wm_cls = ('', '')
        if wm_class:
            wm_inst, wm_cls = [xstr(s) for s in wm_class]

        mapping = [('class', wm_cls), ('inst', wm_inst), ('name', wm_name)]
        for m in mapping:
            for pattern in ignore_list:
                ignore = pattern.get(m[0], None)
                if ignore is None:
                    continue

                if re.match(ignore, m[1]) is not None:
                    return True

        return False

    def _restart_timer(self, sec, func, *args, **kwargs):
        if sec <= 0:
            return

        if func in self.__cmd_timer:
            self.__cmd_timer[func].cancel()

        self.__cmd_timer[func] = threading.Timer(sec, func, args, kwargs)
        self.__cmd_timer[func].start()

    def _is_active_window_fullscreen(self, display):
        root = display.screen().root

        net_active_window = display.intern_atom('_NET_ACTIVE_WINDOW')
        net_wm_state = display.intern_atom('_NET_WM_STATE')
        net_wm_state_fullscreen = display.intern_atom(
            '_NET_WM_STATE_FULLSCREEN')

        active_win_id = root.get_full_property(net_active_window,
                                               Xlib.X.AnyPropertyType)
        if not active_win_id:
            return False

        active_win_id = active_win_id.value[0]
        active_win = display.create_resource_object('window', active_win_id)

        wm_state = active_win.get_full_property(net_wm_state,
                                                Xlib.X.AnyPropertyType)

        if not wm_state:
            return False

        wm_state = wm_state.value

        return net_wm_state_fullscreen in wm_state

    def _handle_fullscreen(self, display):
        fullscreen = self._is_active_window_fullscreen(display)
        if self.__is_fullscreen == fullscreen:
            return

        self.__is_fullscreen = fullscreen

        if fullscreen:
            if self._enter_fullscreen_action:
                self._enter_fullscreen_action.run()

            if self._inhibit_on_fullscreen and self.__fs_inhibit_cookie == -1:
                msg = 'active window entered fullscreen.'
                LOGGER.info('Inhibiting screensaver because {}'.format(msg))
                self.__fs_inhibit_cookie = self.Inhibit(const.APP_NAME, msg)
        else:
            if self._leave_fullscreen_action:
                self._leave_fullscreen_action.run()

            if self._inhibit_on_fullscreen and self.__fs_inhibit_cookie > 0:
                LOGGER.info(
                    'Active window no longer fullscreen, uninhibiting.')
                self.UnInhibit(self.__fs_inhibit_cookie)
                self.__fs_inhibit_cookie = -1

    def _reset_timer(self, idle=True, lock=True):
        self.__idle_since = time.time()

        if idle:
            self._restart_timer(self._idle_sec_current, self.SetActive, True)

        if lock:
            self._restart_timer(self._lock_sec, self.Lock)

    def _monitor(self):
        def _reset():
            LOGGER.debug('Resetting screensaver.')
            self._reset_timer()
            self.SetActive(False)

        def _input_monitor(dev):
            LOGGER.info(f'Monitoring "{dev.name}"')
            for event in dev.read_loop():
                if self.GetSessionIdleTime() < self.input_reset_delay:
                    continue
                _reset()

        # Xlib for monitoring windows
        display = Xlib.display.Display(None)
        root = display.screen().root

        win_attr_mask = (Xlib.X.PropertyChangeMask
                         | Xlib.X.SubstructureNotifyMask)
        root.change_attributes(event_mask=win_attr_mask)

        # evdev for monitoring input devices
        devices = []
        for dev in [evdev.InputDevice(path) for path in evdev.list_devices()]:
            for k, caps in dev.capabilities(absinfo=False).items():
                if (ecodes['BTN_TOUCH'] in caps or ecodes['BTN_MOUSE'] in caps
                        or ecodes['KEY_ENTER'] in caps):
                    devices.append(dev)

        for dev in devices:
            t = threading.Thread(target=_input_monitor, args=(dev, ))
            t.daemon = True
            t.start()

        _reset()

        while True:
            event = display.next_event()

            # Test for new windows
            try:
                if event.type == Xlib.X.CreateNotify:
                    LOGGER.debug('Registering new window')
                    event.window.change_attributes(event_mask=win_attr_mask)

                elif event.type == Xlib.X.MapNotify:
                    wm_class = event.window.get_wm_class()
                    wm_name = event.window.get_wm_name()

                    LOGGER.debug('New window: class: {}, name: {}'.format(
                        wm_class, wm_name))

                    if self._should_ignore(self._idle_reset_ignore, wm_class,
                                           wm_name):
                        LOGGER.debug('Window is in ignore list. '
                                     'Not resetting ScreenSaver.')
                        continue
                    _reset()

                elif event.type == Xlib.X.PropertyNotify:
                    self._handle_fullscreen(display)

            except Xlib.error.XError:
                continue

    # Freedesktop spec
    @dbus.service.method(const.SS_DBUS_NAME, in_signature='ss',
                         out_signature='u')
    def Inhibit(self, application_name, reason_for_inhibit):
        self.__inhibit_count += 1
        self._reset_timer()
        self.SetActive(False)
        return self.__inhibit_count

    @dbus.service.method(const.SS_DBUS_NAME, in_signature='u')
    def UnInhibit(self, cookie):
        self.__inhibit_count = max(0, self.__inhibit_count - 1)

    # Additions
    @dbus.service.method(const.SS_DBUS_NAME, out_signature='b')
    def GetInhibit(self):
        return self.__inhibit_count > 0

    @dbus.service.method(const.SS_DBUS_NAME)
    def Lock(self):
        if self.GetInhibit():
            return

        if self._lock_action:
            self._lock_action.run()

        self._reset_timer(lock=False)
        self.SetActive(True)

    @dbus.service.method(const.SS_DBUS_NAME)
    def Cycle(self):
        pass

    @dbus.service.method(const.SS_DBUS_NAME, in_signature='ss',
                         out_signature='u')
    def Throttle(self, application_name, reason_for_throttle):
        return 1

    @dbus.service.method(const.SS_DBUS_NAME, in_signature='u')
    def UnThrottle(self, cookie):
        pass

    @dbus.service.method(const.SS_DBUS_NAME)
    def SimulateUserActivity(self):
        self._reset_timer()
        self.SetActive(False)

    @dbus.service.method(const.SS_DBUS_NAME, in_signature='b')
    def SetActive(self, active):
        if self.GetInhibit() and active:
            return

        self.__is_active = active
        self.__active_since = None if not active else time.time()

        if self._idle_action:
            if active:
                if not self._idle_action.is_running():
                    self._idle_action.run()

            else:
                self._reset_timer()
                if self._idle_action.is_running():
                    self._idle_action.terminate()

                if self._idle_reset_action:
                    self._idle_reset_action.run()

    @dbus.service.method(const.SS_DBUS_NAME, out_signature='b')
    def GetActive(self):
        return self.__is_active

    @dbus.service.method(const.SS_DBUS_NAME, out_signature='u')
    def GetActiveTime(self):
        if not self.__active_since:
            return 0
        return int(time.time() - self.__active_since)

    @dbus.service.method(const.SS_DBUS_NAME, out_signature='b')
    def GetSessionIdle(self):
        return self.GetSessionIdleTime() > self._idle_sec_current

    @dbus.service.method(const.SS_DBUS_NAME, out_signature='u')
    def GetSessionIdleTime(self):
        if not self.__idle_since:
            return 0
        return int(time.time() - self.__idle_since)


def register(config):
    sconfig = config['ScreenSaver']

    lock_cmd = utils.get_action(config, 'ScreenSaver', 'lock_action')
    lock_sec = sconfig.getint('lock_sec')
    idle_cmd = utils.get_action(config, 'ScreenSaver', 'idle_action')
    idle_reset_cmd = utils.get_action(config, 'ScreenSaver',
                                      'idle_reset_action')
    idle_sec = sconfig.getint('idle_sec')
    idle_sec_locked = sconfig.getint('idle_sec_locked')
    idle_reset_ignore = json.loads(sconfig['idle_reset_ignore'])
    inhibit_on_fullscreen = sconfig.getboolean('inhibit_on_fullscreen')

    enter_fullscreen_cmd = utils.get_action(config, 'ScreenSaver',
                                            'enter_fullscreen_action')
    leave_fullscreen_cmd = utils.get_action(config, 'ScreenSaver',
                                            'leave_fullscreen_action')

    # Register services
    ss = ScreenSaver.get(const.SS_DBUS_PATH)
    ss.configure(lock_cmd, lock_sec, idle_cmd, idle_reset_cmd, idle_sec,
                 idle_sec_locked, idle_reset_ignore, inhibit_on_fullscreen,
                 enter_fullscreen_cmd, leave_fullscreen_cmd)
    ss.start()
