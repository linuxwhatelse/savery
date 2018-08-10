import json
import re
import threading
import time
import logging

import dbus
import dbus.service
import Xlib
import Xlib.display
import Xlib.protocol.event
import Xlib.Xatom
from Xlib.ext import xinput

from . import utils, const

LOGGER = logging.getLogger(__name__)

DBUS_INTERFACE = 'org.savery.ScreenSaver'
DBUS_PATH = '/org/savery/ScreenSaver'


class ScreenSaver(dbus.service.Object):
    idle_event_masks = (xinput.KeyPressMask | xinput.ButtonPressMask
                        | xinput.MotionMask | xinput.RawKeyPressMask
                        | xinput.RawButtonPressMask | xinput.RawMotionMask)
    """int: Mask of xinput events to register for."""

    idle_reset_events = [
        xinput.KeyPress, xinput.ButtonPress, xinput.Motion, xinput.RawKeyPress,
        xinput.RawButtonPress, xinput.RawMotion
    ]
    """list: Events that will reset the idle timer and kill the idle action."""

    input_reset_delay = 3
    """int: When input is detected, only reset ever `input_reset_delay` sec.
        to keep cpu-usage low."""

    _lock_action = None
    _lock_sec = None

    _idle_action = None
    _idle_sec = None
    _idle_sec_locked = None

    _win_ignore = None
    _inhibit_on_fullscreen = True

    __inhibit_count = 0
    __is_active = False
    __active_since = None
    __idle_since = None

    __fs_inhibit_cookie = -1

    __cmd_timer = None
    __mem = None

    def __init__(self, lock_cmd=None, lock_sec=0, idle_cmd=None, idle_sec=0,
                 idle_sec_locked=0, win_ignore=None,
                 inhibit_on_fullscreen=True):
        self.__cmd_timer = {}
        self.__mem = []

        # Aquire ScreenSaver name on session-bus
        bus = dbus.SessionBus()
        self.__mem.append(dbus.service.BusName(DBUS_INTERFACE, bus))

        dbus.service.Object.__init__(self, bus, DBUS_PATH)

        if lock_cmd:
            self._lock_action = utils.Action.get(lock_cmd)
        self._lock_sec = lock_sec

        if idle_cmd:
            self._idle_action = utils.Action.get(idle_cmd)
        self._idle_sec = idle_sec
        self._idle_sec_locked = idle_sec_locked

        self._win_ignore = win_ignore
        self._inhibit_on_fullscreen = inhibit_on_fullscreen

        t = threading.Thread(target=self._monitor)
        t.daemon = True
        t.start()

    @property
    def _idle_sec_current(self):
        if self._idle_sec_locked == 0:
            return self._idle_sec

        elif self._lock_action and self._lock_action.is_running():
            return self._idle_sec_locked

        else:
            return self._idle_sec

    def _is_win_ignore(self, wm_class=None, wm_name=None):
        """Test if the given window is to be ignored due to it being in
        `ScreenSaver._win_ignore`_.

        Args:
            wm_class (tuple|None): Tuple in the form of `(instance, class)` or
                None.
            wm_name (str): The windows name or None."""
        if not self._win_ignore:
            return False

        wm_inst, wm_cls = None, None
        if wm_class:
            wm_inst, wm_cls = wm_class

        match = True
        for pair in [('class', wm_cls), ('inst', wm_inst), ('name', wm_name)]:
            for patterns in self._win_ignore:
                ignore = patterns.get(pair[0], None)
                win = pair[1]

                if ignore is None:
                    continue

                if ignore and not win:
                    return False

                match = re.match(ignore, win) is not None

        return match

    def _restart_timer(self, sec, func, *args, **kwargs):
        if sec <= 0:
            return

        if func in self.__cmd_timer:
            self.__cmd_timer[func].cancel()

        self.__cmd_timer[func] = threading.Timer(sec, func, args, kwargs)
        self.__cmd_timer[func].start()

    def _handle_fullscreen(self, display):
        root = display.screen().root

        net_active_window = display.intern_atom('_NET_ACTIVE_WINDOW')
        net_wm_state = display.intern_atom('_NET_WM_STATE')
        net_wm_state_fullscreen = display.intern_atom(
            '_NET_WM_STATE_FULLSCREEN')

        active_win_id = root.get_full_property(net_active_window,
                                               Xlib.X.AnyPropertyType).value[0]

        active_win = display.create_resource_object('window', active_win_id)

        wm_state = active_win.get_full_property(net_wm_state,
                                                Xlib.X.AnyPropertyType)

        if not wm_state:
            return

        wm_state = wm_state.value

        if (len(wm_state) > 0 and wm_state[0] == net_wm_state_fullscreen):
            if self.__fs_inhibit_cookie == -1:
                msg = 'active window entered fullscreen.'
                LOGGER.info('Inhibiting screensaver becase {}'.format(msg))

                self.__fs_inhibit_cookie = self.Inhibit(const.APP_NAME, msg)

        else:
            if self.__fs_inhibit_cookie > 0:
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
        display = Xlib.display.Display(None)
        root = display.screen().root

        win_attr_mask = (Xlib.X.PropertyChangeMask
                         | Xlib.X.SubstructureNotifyMask)
        root.change_attributes(event_mask=win_attr_mask)

        root.xinput_select_events([(xinput.AllDevices, self.idle_event_masks)])

        self._reset_timer()
        self.SetActive(False)

        while True:
            event = display.next_event()

            reset = False

            # Xinput events
            if event.type == display.extension_event.GenericEvent:
                if event.evtype in self.idle_reset_events:
                    if self.GetSessionIdleTime() < self.input_reset_delay:
                        continue

                    reset = True

            else:
                try:
                    if event.type == Xlib.X.CreateNotify:
                        LOGGER.debug('Registering new window')
                        event.window.change_attributes(
                            event_mask=win_attr_mask)

                    elif event.type == Xlib.X.MapNotify:
                        wm_class = event.window.get_wm_class()
                        wm_name = event.window.get_wm_name()

                        LOGGER.debug('New window: class {}, name {}'.format(
                            wm_class, wm_name))

                        reset = not self._is_win_ignore(wm_class, wm_name)

                        if not reset:
                            LOGGER.info('Not resetting screensaver because '
                                        'window is in ignore-list')

                    elif event.type == Xlib.X.PropertyNotify:
                        if self._inhibit_on_fullscreen:
                            self._handle_fullscreen(display)

                except Xlib.error.XError:
                    continue

            if reset:
                LOGGER.debug('Resetting screensaver.')
                self._reset_timer()
                self.SetActive(False)

    # Freedesktop spec
    @dbus.service.method(DBUS_INTERFACE, in_signature='ss', out_signature='u')
    def Inhibit(self, application_name, reason_for_inhibit):
        self.__inhibit_count += 1
        self._reset_timer()
        self.SetActive(False)
        return self.__inhibit_count

    @dbus.service.method(DBUS_INTERFACE, in_signature='u')
    def UnInhibit(self, cookie):
        self.__inhibit_count = max(0, self.__inhibit_count - 1)

    # Additions
    @dbus.service.method(DBUS_INTERFACE, out_signature='b')
    def GetInhibit(self):
        return self.__inhibit_count > 0

    @dbus.service.method(DBUS_INTERFACE)
    def Lock(self):
        if self.GetInhibit():
            return

        if self._lock_action:
            self._lock_action.run()

        self._reset_timer(lock=False)
        self.SetActive(True)

    @dbus.service.method(DBUS_INTERFACE)
    def Cycle(self):
        pass

    @dbus.service.method(DBUS_INTERFACE, in_signature='ss', out_signature='u')
    def Throttle(self, application_name, reason_for_throttle):
        return 1

    @dbus.service.method(DBUS_INTERFACE, in_signature='u')
    def UnThrottle(self, cookie):
        pass

    @dbus.service.method(DBUS_INTERFACE)
    def SimulateUserActivity(self):
        self._reset_timer()
        self.SetActive(False)

    @dbus.service.method(DBUS_INTERFACE, in_signature='b')
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

    @dbus.service.method(DBUS_INTERFACE, out_signature='b')
    def GetActive(self):
        return self.__is_active

    @dbus.service.method(DBUS_INTERFACE, out_signature='u')
    def GetActiveTime(self):
        if not self.__active_since:
            return 0
        return int(time.time() - self.__active_since)

    @dbus.service.method(DBUS_INTERFACE, out_signature='b')
    def GetSessionIdle(self):
        return self.GetSessionIdleTime() > self._idle_sec_current

    @dbus.service.method(DBUS_INTERFACE, out_signature='u')
    def GetSessionIdleTime(self):
        if not self.__idle_since:
            return 0
        return int(time.time() - self.__idle_since)


def register(config):
    sconfig = config['ScreenSaver']

    lock_cmd = utils.get_action(config, 'ScreenSaver', 'lock_action')
    lock_sec = sconfig.getint('lock_sec')
    idle_cmd = utils.get_action(config, 'ScreenSaver', 'idle_action')
    idle_sec = sconfig.getint('idle_sec')
    idle_sec_locked = sconfig.getint('idle_sec_locked')
    win_ignore = json.loads(sconfig['win_ignore'])
    inhibit_on_fullscreen = sconfig.getboolean('inhibit_on_fullscreen')

    # Register services
    ScreenSaver(lock_cmd, lock_sec, idle_cmd, idle_sec, idle_sec_locked,
                win_ignore, inhibit_on_fullscreen)
