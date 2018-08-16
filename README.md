# savery

**savery** is a X11 *"ScreenSaver"* written in python following the same
"specification" (there doesn't seem to be a real one) as f.e. gnome, kde, ...  
It has its own idle timer (not relying on X11) and allows you to run custom
actions when the session has been idle and when it should be locked.  
It can also inhibit itself when the active window enters fullscreen.

It also integrates with [logind](https://www.freedesktop.org/wiki/Software/systemd/logind/) allowing you to
execute custom actions before sleep and when invoking
[loginctl](https://www.freedesktop.org/software/systemd/man/loginctl.html)
`(un)lock-session`.

The [config file](config.ini) has been documented and will give you a better
idea of how **savery** works.  

## Motivation
To keep it short, neither **xss-lock** nor **xautolock** worked for me.  
Either due to missing features or because they where built on different
principles.  
The biggest issue has always been X11s idle timer which would constantly reset
for unkown reasons.

## Installation
### From source
```sh
$ git clone https://github.com/linuxwhatelse/savery
$ cd savery
$ pip install -r requirements.txt
$ python setup.py install
```

### Archlinux
Install [python-savery-git](https://aur.archlinux.org/packages/python-savery-git/)
from the aur.


## Configuration
Copy [config.ini](config.ini) to `~/.config/savery.ini` and change it to
your liking.

## Usage
### Manually
```sh
$ savery
# or
$ savery -c /path/to/alternative/config.ini
```

### systemd
Copy [savery.service](savery.service) to `~/.config/systemd/user/savery.service`
and change it to your liking.

```sh
systemctl --user daemon-reload
systemctl --user start savery

# To have it start automatically
systemctl --user enable savery
```
