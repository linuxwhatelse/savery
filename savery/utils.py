import configparser
import logging
import os
import subprocess
import threading

LOGGER = logging.getLogger(__name__)


def get_action(config, section, key):
    return config['Actions'][config[section][key]]


def get_config(file_):
    config_file = os.path.abspath(os.path.expanduser(file_))

    config = configparser.ConfigParser()
    config.read(config_file)

    if not config.sections():
        return None

    return config


class Action:
    __instances = {}

    _lock = threading.RLock()

    _command = None
    _proc = None

    def __init__(self, command):
        self._command = command

    @classmethod
    def get(cls, command):
        if command not in cls.__instances:
            cls.__instances[command] = cls(command)
        return cls.__instances[command]

    def run(self):
        with self._lock:
            if self.is_running():
                return

            LOGGER.info('Executing: {}'.format(self._command))
            self._proc = subprocess.Popen(self._command, shell=True)

    def terminate(self):
        if not self.is_running():
            return
        LOGGER.info('Terminating: {}'.format(self._command))
        self._proc.terminate()
        self._proc = None

    def kill(self):
        if not self.is_running():
            return

        LOGGER.info('Killing: {}'.format(self._command))
        self._proc.kill()
        self._proc = None

    def is_running(self):
        if self._proc is None:
            return False
        return self._proc.poll() is None
