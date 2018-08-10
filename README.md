savery
===
**savery** is a X11 Screensaver written in python (because that's what I started
prototyping with and I don't feel like rewriting it).  

It also integrates with **logind**.


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
Copy [config.ini](config.ini) to `~/.config/savery.ini` and change it to your
liking.

### Autostart with systemd
To automatically start **savery** via systemd, copy
[savery.service](savery.service) to `~/.config/systemd/user/savery.service`
and tweak it as you like.

```sh
systemctl --user daemon-reload
systemctl --user start savery

# To have it start automatically
systemctl --user enable savery
```


## Usage
```sh
$ savery
```
