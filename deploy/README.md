# Frame deployment

The API lives in `/var/python_app` on the Pi (`python_app.service`, gunicorn on
port 5000). The panel is painted by `framecast.py`, started through `slideshowctl`.

## Files

| Repo | On the Pi |
|---|---|
| `deploy/framecast.py` | `/usr/local/bin/framecast.py` — the player: stills into the framebuffer, clips through the GPU |
| `deploy/slideshowctl` | `/usr/local/bin/slideshowctl` — `start` / `stop` / `restart` / `reload` / `status` |
| `deploy/framecast.default` | `/etc/default/framecast` — panel settings, all optional |

Started from `/etc/rc.local` at boot and kept alive by a root cron entry running
`slideshowctl start` every two minutes (a no-op while it is already up).
`POST /api/v1/restart-slideshow` calls `slideshowctl reload` through sudo.

## Requirements on the box

`omxplayer` (clips), `ffmpeg` and `ffprobe` (checking an upload and lifting a
poster frame out of it), and Pillow in the API's virtualenv. Raspbian buster is
past end of life, so `sources.list` points at `legacy.raspbian.org` — the old
mirror stopped serving buster and `apt-get update` fails against it.

## Why the player is no longer fbi

`fbi` reads its picture list once, at startup, and holds the console for as long
as it runs. Neither survives a gallery with video in it: a clip needs the panel
handed to the GPU and handed back on every pass, and the list has to be re-read
to notice an upload at all.

Writing the framebuffer directly turned out to remove more than it added. The
player claims no console — the VT only has to be one nothing else prints to,
which is what tty7 already was — so the launch race that used to keep `fbi` off
the panel is gone, and with it the five-attempt retry loop and the reason this
could not be a systemd unit. What is left of that history is `rc.local` and the
cron entry, which still work and are now belt and braces rather than the
mechanism.

Two things follow for the API. The gallery is re-read on every pass, so an upload
reaches the panel by itself within one slot; and `restart-slideshow` became a
`SIGHUP`, which returns immediately where the old restart cost the caller seven
seconds.

## Frame geometry

The panel is a 1024x600 LCD rotated 90 degrees (`display_lcd_rotate=3`), so the
usable area is 600x1024 — a ratio of ~0.586, *not* 9:16. `FRAME_WIDTH`/
`FRAME_HEIGHT` in `.env` must match it.

Stills are stored at exactly 600x1024 so the player writes them to the
framebuffer 1:1 and the JPEG decoder can halve every phone photo it reads, which
matters on a single-core ARMv6 board with 440MB of RAM.

The framebuffer is 32bpp with **blue in the low byte** (`fbset -i` reports
`rgba 8/16,8/8,8/0,8/24`) and a stride of 2432 bytes against 600 visible pixels,
so rows are padded one at a time. Getting either wrong is visible immediately:
the wrong byte order turns faces blue, the wrong stride shears the picture into
diagonal stripes.

### The two coordinate spaces

Stills and clips do *not* land in the same space, and both settings that follow
were established by measurement rather than reasoning — the reasoning gave the
wrong answer twice.

**Rotation.** `VIDEO_ORIENTATION=0` is correct here, which looks like an omission
and is not. The framebuffer layer is composited with `transform:3`, and asking
omxplayer for orientation 0 produces a layer with `transform:3` as well — it
inherits the display's transform, so a clip comes out the same way up as a still.
Asking for 180 to "match" would turn the clip upside down.

**Scaling.** `--aspect-mode stretch`, not `fill` or `letterbox`, because
omxplayer measures the clip against the panel's *unrotated* 1024x600 shape and
both fitting modes get it wrong: `fill` crops the middle 600x449 band out of the
clip and blows it up, `letterbox` shrinks it into a 263-pixel strip down the
centre (`dst:168,0,263,1024`). `stretch` maps the whole clip onto the whole
panel, which for a clip at the frame's own ratio is an exact 1:1 copy — which is
why the uploader requires that ratio and refuses anything else.

To see what the panel is really showing, including the GPU layer, take a dispmanx
snapshot: `/dev/fb0` carries only the stills. `vcgencmd dispmanx_list` lists the
live layers and the transform on each, and is enough on its own to tell a clip
that is being cropped from one that is not.

## What the frame can play

The GPU decodes H.264 and nothing else. `vcgencmd codec_enabled` answers
`disabled` for MPEG-2 and VC-1 (unlicensed), and BCM2835 has no HEVC block at
all, so an iPhone's default recording cannot be played here at any setting.
Conversion happens upstream, before the upload; the API refuses what it cannot
play and says why. The limits are in [`../API.md`](../API.md).
