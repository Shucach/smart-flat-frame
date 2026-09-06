# Frame deployment

The API lives in `/var/python_app` on the Pi (`python_app.service`, gunicorn on
port 5000). The slideshow is `fbi`, driven by the two scripts here.

## Files

| Repo | On the Pi |
|---|---|
| `deploy/slideshow.sh` | `/usr/local/bin/slideshow.sh` — builds the picture list and execs `fbi` |
| `deploy/slideshowctl` | `/usr/local/bin/slideshowctl` — `start` / `stop` / `restart` / `status` |

Started from `/etc/rc.local` at boot, kept alive by a root cron entry that runs
`slideshowctl start` every two minutes (a no-op while it is already running).
`POST /api/v1/restart-slideshow` calls `slideshowctl restart` through sudo.

## Why not a systemd unit

The obvious answer is a unit with `Restart=always`, and it does not work: started
directly by systemd, `fbi` loses the race for the console and exits with status 0
within a second, over and over. The same script run through `sudo` from a shell
survived every attempt. What `sudo` adds is a PAM session (`pam_systemd`), which
is what lets the process take the virtual terminal.

`StandardInput=tty`, `tty-force`, `setsid --wait`, `openvt`, `TERM=linux` and a
never-closing pipe on stdin were each tried, alone and combined; none of them
kept `fbi` alive under systemd. The launch path here is the one that measurably
works, and `slideshowctl start` retries five times before giving up, because the
race is occasionally lost even from a login session.

## Frame geometry

The panel is a 1024x600 LCD rotated 90 degrees (`display_lcd_rotate=3`), so the
usable area is 600x1024 — a ratio of ~0.586, *not* 9:16. `FRAME_WIDTH`/
`FRAME_HEIGHT` in `.env` must match it, or `fbi` trims the difference off the
picture at display time.

Pictures are stored at exactly 600x1024 so `fbi` draws them 1:1 and the JPEG
decoder can halve every phone photo it reads (`load_for` in `ImageHelper`), which
matters on a single-core ARMv6 board with 440MB of RAM.
