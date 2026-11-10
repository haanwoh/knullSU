# 04 · Hardware bridge

`plx hw` is a thin, honest wrapper over **Termux:API**. Every call is an Android API call made
by an app that holds the permissions you granted. Nothing bypasses the OS.

## Setup

```bash
pkg install termux-api
# then install the "Termux:API" app from F-Droid and open it once
plx hw status
```

If the app is missing, commands fail with this exact message:

```
✗ termux-battery-status not found. Install the CLI and the app:
  pkg install termux-api
  install 'Termux:API' from F-Droid, then grant the permission when asked
```

## Tools

| `plx hw …` | Android permission | example |
|---|---|---|
| `battery` | none | `plx hw battery` |
| `wifi` | location (Android 10+) | `plx hw wifi` |
| `sensors` | none | `plx hw sensors -l` · `plx hw sensors -s accelerometer` |
| `location` | location | `plx hw location -p gps -r once` |
| `torch` | camera | `plx hw torch on` / `off` |
| `clipboard-get` | none | `plx hw clipboard-get` |
| `clipboard-set` | none | `plx hw clip "text"` |
| `notification` | notifications (13+) | `plx hw notification --title Hi --content there` |
| `toast` | none | `plx hw toast "done"` |
| `vibrate` | vibrate | `plx hw vibrate -d 400` |
| `camera` | camera | `plx hw camera 0 /sdcard/DCIM/plx.jpg` |
| `tts` | none | `plx hw tts "build finished"` |
| `volume` | none | `plx hw volume --stream music --volume 8` |
| `brightness` | write-settings (once) | `plx hw brightness 128` |
| `wake-lock` / `wake-unlock` | none | keep a build alive with the screen off |
| `telephony` | phone state | `plx hw telephony` |
| `sms-list` | SMS | `plx hw sms-list -l 3` |
| `share` / `open` | none | `plx hw open /sdcard/report.pdf` |

Flags for the underlying tool go after `--`:

```bash
plx hw notification -- --title "Build" --content "done" --priority high
```

`--json` wraps every result:

```console
$ plx hw battery --json
{"tool": "battery", "ok": true, "code": 0,
 "stdout": "{...}", "json": {"health": "GOOD", "percentage": 87, ...}}
```

`plx hw status` aggregates battery, Wi-Fi and telephony in one call — handy for a status bar
script or a cron-style widget.

## Recipes using hardware

```bash
# vibrate + notify when a long build finishes
plx shell -c 'make -j4' && plx hw vibrate -d 300 && plx hw notification --title "make" --content "ok"

# photo timelapse into shared storage
for i in $(seq 1 10); do plx hw camera 0 "/sdcard/DCIM/plx-$i.jpg"; sleep 5; done
```

## What it will not do

* read another app's private data, messages you have not granted access to, or the camera while
  another app owns it;
* keep working while Android has frozen Termux — hold `termux-wake-lock` for long jobs;
* bypass a permission dialog. If you denied it, `plx hw` fails, and that is correct behaviour.

Battery note: sensors, GPS and wake locks are expensive. Android will kill a process that
holds a wake lock for hours; that is a feature.
