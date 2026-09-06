#!/bin/bash
#
# Paints the gallery onto the frame panel. Started by slideshow.service on tty1.
#
# `fbi` reads the picture list once, at startup, so the API restarts this unit
# whenever the gallery changes.
set -u

GALLERY="${GALLERY:-/home/pi/images_api/images}"
CONSOLE="${CONSOLE:-/dev/tty7}"
DELAY="${DELAY:-60}"
VT="${VT:-7}"
LIST=/run/slideshow.list

# Keep the panel lit and free of the blinking cursor, whatever the console left behind.
setterm --cursor off --blank 0 --powerdown 0 >"$CONSOLE" 2>/dev/null || true

# The gallery can still be empty moments after boot, so wait rather than give up:
# the unit restarts on failure anyway, but retrying here keeps the log quiet.
for _ in $(seq 30); do
    find "$GALLERY" -maxdepth 1 -type f \
        \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) \
        | sort >"$LIST"

    [ -s "$LIST" ] && break
    sleep 2
done

if [ ! -s "$LIST" ]; then
    echo "no pictures in $GALLERY" >&2
    exit 1
fi

echo "showing $(wc -l <"$LIST") pictures, ${DELAY}s each"

# Two things keep the slideshow alive, and it needs both:
#
#   tty7  -- tty1 is shared with agetty, which pulls the terminal out from under
#            fbi. tty7 has no getty on it, so nothing competes for the console.
#   stdin -- fbi watches the keyboard and quits the instant stdin reports EOF.
#            Under systemd every ordinary stdin (null, the journal, even the tty
#            itself) reaches EOF within a second, which is what left the frame
#            sitting on a bare console after boot. A pipe nobody ever writes to
#            never ends, and the frame has no keyboard to miss.
#
# -cachemem is deliberately small: this board has 440MB of RAM to share.
exec /usr/bin/fbi -a -u --noverbose -fitwidth -T "$VT" -t "$DELAY" -cachemem 16 -l "$LIST" < <(sleep infinity)
