"""Generate the two short alarm WAVs used by the DPS meter.

Run with: pixi run python gen_sounds.py
Produces assets/alarm_dps.wav and assets/alarm_mining.wav (16-bit PCM mono).
Kept as a committed utility so the sounds can be regenerated/tweaked.
"""
import math
import struct
import wave
from pathlib import Path

SR = 44100
ASSETS = Path(__file__).resolve().parent / 'assets'


def _env(i, n, attack=0.01, release=0.05):
    """Smooth attack/release envelope (0..1) to avoid clicks."""
    t = i / SR
    dur = n / SR
    a = min(1.0, t / attack) if attack > 0 else 1.0
    r = min(1.0, (dur - t) / release) if release > 0 else 1.0
    return max(0.0, min(a, r))


def _tone(freq, dur, vol=0.5, attack=0.008, release=0.05):
    n = int(SR * dur)
    return [vol * _env(i, n, attack, release) * math.sin(2 * math.pi * freq * i / SR)
            for i in range(n)]


def _silence(dur):
    return [0.0] * int(SR * dur)


def _write(path, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = b''.join(struct.pack('<h', int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
        w.writeframes(frames)
    print(f"wrote {path} ({len(samples)/SR:.2f}s)")


def main():
    # DPS alarm: urgent flat double-beep (~0.20s).
    dps = _tone(960, 0.07, vol=0.55) + _silence(0.04) + _tone(960, 0.07, vol=0.55)
    _write(ASSETS / 'alarm_dps.wav', dps)

    # Mining stall: gentle rising two-note chime (~0.34s), clearly distinct.
    mining = _tone(660, 0.12, vol=0.45, release=0.06) + _tone(990, 0.20, vol=0.45, release=0.12)
    _write(ASSETS / 'alarm_mining.wav', mining)


if __name__ == '__main__':
    main()
