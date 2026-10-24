"""Música y efectos del vídeo, sintetizados (sin muestras externas). 120 BPM, La menor.

Uso: python music.py salida.wav
Los instantes de los efectos coinciden con los de index.html.
"""
import sys

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

SR = 44100
DUR = 33.0
BPM = 120
BEAT = 60 / BPM
N = int(SR * DUR)
T = np.arange(N) / SR
rng = np.random.default_rng(42)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def lp(x, f, order=2):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def saw(f, t):
    return 2 * ((f * t) % 1) - 1


def place(bus, start, sig, gain=1.0):
    i = int(start * SR)
    if i >= len(bus):
        return
    j = min(len(bus), i + len(sig))
    bus[i:j] += sig[: j - i] * gain


def env(n, attack, decay):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-t / decay)


def stereo(mono, pan=0.0):
    return np.stack([mono * np.sqrt((1 - pan) / 2), mono * np.sqrt((1 + pan) / 2)], axis=1)


# ---------- instrumentos ----------
def kick():
    n = int(.45 * SR); t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t / .035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .22)
    click = hp(rng.standard_normal(n), 3000) * np.exp(-t / .004) * .3
    return np.tanh(1.6 * (body + click))


def clap():
    n = int(.3 * SR); t = np.arange(n) / SR
    noise = bp(rng.standard_normal(n), 900, 5000)
    e = np.exp(-t / .12) * (1 + .6 * np.exp(-((t - .012) % .011) / .002) * (t < .035))
    return noise * e * .55


def hat(open_=False):
    n = int((.25 if open_ else .06) * SR); t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 7500) * np.exp(-t / (.09 if open_ else .018)) * .35


def pluck(f, dur=.22):
    n = int(dur * SR); t = np.arange(n) / SR
    x = (saw(f, t) + .5 * saw(f * 1.005, t)) * np.exp(-t / .09)
    return lp(x, 3200) * .22


def impact():
    n = int(2.2 * SR); t = np.arange(n) / SR
    f = 30 + 70 * np.exp(-t / .08)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .7)
    crack = lp(rng.standard_normal(n), 5000) * np.exp(-t / .18) * .5
    return np.tanh(1.3 * (boom + crack))


def whoosh(dur, rise=True):
    n = int(dur * SR); t = np.arange(n) / SR
    shape = np.sin(np.pi * t / dur) ** 2 if not rise else (t / dur) ** 2.2
    noise = rng.standard_normal(n)
    bright = hp(noise, 1500) * (t / dur) + lp(noise, 1200) * (1 - t / dur)
    return bright * shape * .5


def riser(dur):
    n = int(dur * SR); t = np.arange(n) / SR
    f = 200 * 2 ** (3 * t / dur)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * .25
    noise = hp(rng.standard_normal(n), 2000) * .35
    return (tone + noise) * (t / dur) ** 2


def tick(f=2200):
    n = int(.03 * SR); t = np.arange(n) / SR
    return np.sin(2 * np.pi * f * t) * np.exp(-t / .006) * .6


def pop():
    n = int(.12 * SR); t = np.arange(n) / SR
    f = 900 + 1500 * (1 - np.exp(-t / .02))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .05) * .45


# ---------- composición ----------
CHORDS = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]  # Am F C G
GROOVE = [(4.0, 23.0), (24.65, 30.0)]


def in_groove(t):
    return any(a <= t < b for a, b in GROOVE)


drums = np.zeros(N); bass = np.zeros(N); pad = np.zeros(N); arp = np.zeros(N); sfx = np.zeros(N)
side = np.ones(N)  # compresión «sidechain» del bombo sobre bajo y pads

K = kick()
beats = np.arange(0, DUR, BEAT)
for b in beats:
    if in_groove(b):
        place(drums, b, K, .95)
        i = int(b * SR); n = int(.35 * SR); tt = np.arange(min(n, N - i)) / SR
        side[i:i + len(tt)] = np.minimum(side[i:i + len(tt)], 1 - .65 * np.exp(-tt / .1))
        if int(round(b / BEAT)) % 2 == 1:
            place(drums, b, clap(), .8)
    eighth = b + BEAT / 2
    if in_groove(eighth):
        place(drums, eighth, hat(open_=int(round(b / BEAT)) % 4 == 3), .9)
for s in np.arange(0, 4.0, BEAT / 4):  # intro: semicorcheas de hi-hat que crecen
    place(drums, s, hat(), .15 + .5 * s / 4)
for b in (0.0, 1.25, 2.5):  # golpes de las frases de la intro
    place(drums, b, K, .9); place(sfx, b, hp(rng.standard_normal(int(.25 * SR)), 2500) * env(int(.25 * SR), .002, .06), .5)

for i, start in enumerate(np.arange(0, DUR, 4 * BEAT)):
    chord = CHORDS[i % 4]
    seg = int(4 * BEAT * SR); t = np.arange(seg) / SR
    a = int(start * SR); m = min(seg, N - a)
    if m <= 0:
        break
    # pad: sierras desafinadas, filtradas
    v = sum(saw(hz(n + 12), t) + saw(hz(n + 12) * 1.004, t) + saw(hz(n), t * 0.998) for n in chord)
    pad[a:a + m] += (lp(v, 1400) * .07 * np.minimum(1, t / .25))[:m]
    # bajo: corcheas sobre la fundamental, con salto de octava
    for k in range(8):
        on = start + k * BEAT / 2
        if in_groove(on):
            f = hz(chord[0] - 24 + (12 if k % 2 else 0))
            nn = int(BEAT / 2 * SR * .9); tt = np.arange(nn) / SR
            place(bass, on, lp(saw(f, tt) + .5 * np.sin(2 * np.pi * f * tt), 500) * np.exp(-tt / .18) * .5)
    # arpegio desde que aparece la app
    for k in range(16):
        on = start + k * BEAT / 4
        if in_groove(on) and on >= 8.0:
            note = chord[k % 3] + 12 * (1 + (k // 3) % 2)
            place(arp, on, pluck(hz(note)), .8)

# final: acorde largo de La menor
n = int(3.2 * SR); t = np.arange(n) / SR
final = sum(saw(hz(x + 12), t) + saw(hz(x + 12) * 1.005, t) for x in (57, 60, 64, 69))
place(pad, 30.0, lp(final, 1800) * .09 * np.minimum(1, t / .05) * np.exp(-t / 1.6))
place(bass, 30.0, np.sin(2 * np.pi * hz(33) * t) * np.exp(-t / 1.2) * .6)
# drone de la intro
place(pad, 0.0, lp(saw(hz(33), T[:int(4 * SR)]) + saw(hz(45), T[:int(4 * SR)]), 300) * .12 * np.minimum(1, T[:int(4 * SR)] / .2))

# efectos sincronizados con la imagen
for at in (4.0, 5.4, 14.15, 24.65, 30.0):
    place(sfx, at, impact(), .9 if at in (4.0, 30.0) else .7)
for start, d in ((3.55, .45), (7.6, .5), (16.4, .5), (22.4, .6), (26.7, .3), (29.6, .4)):
    place(sfx, start, whoosh(d), .7)
place(sfx, 2.5, riser(1.5), .6); place(sfx, 23.6, riser(1.05), .6)
for at in (10.45, 18.05):
    place(sfx, at, tick(), .8)
for at in (18.6, 18.95, 20.55, 20.8):
    place(sfx, at, pop(), .8)
for start in (12.95, 19.2):  # zumbido de «Reiniciando…»
    nn = int(1.2 * SR); tt = np.arange(nn) / SR
    place(sfx, start, np.sin(2 * np.pi * (300 + 600 * tt) * tt) * .12 * np.sin(np.pi * tt / 1.2))

# filtro de la música en los reinicios y en la pausa del escritorio
amount = np.zeros(N)
for a, b in ((12.95, 14.15), (19.2, 20.45), (23.0, 24.65)):
    i, j = int(a * SR), int(b * SR)
    ramp = np.minimum(1, np.minimum((T[i:j] - a) / .15, (b - T[i:j]) / .1))
    amount[i:j] = np.maximum(amount[i:j], ramp)

music = drums + (bass + pad) * side + arp * side
music = music * (1 - amount) + lp(music, 350) * amount * .9

# espacio: reverberación corta sobre pads, arpegio y efectos
ir_n = int(1.6 * SR); ir = rng.standard_normal(ir_n) * np.exp(-np.arange(ir_n) / SR / .45); ir /= np.abs(ir).sum() / 6
wet = fftconvolve(pad * side + arp + sfx * .5, ir)[:N]

dry = music + sfx
delay = int(.013 * SR)  # reverberación desplazada en un canal: da amplitud estéreo
wet_r = np.concatenate([np.zeros(delay), wet[:-delay]])
mix = np.stack([dry + wet * .35, dry + wet_r * .35], axis=1)
mix = np.tanh(mix * 1.1)
fade = np.ones(N); fi = int(.4 * SR); fade[-fi:] = np.linspace(1, 0, fi)
mix *= fade[:, None]
mix /= np.abs(mix).max() / 0.89
wavfile.write(sys.argv[1] if len(sys.argv) > 1 else "music.wav", SR, (mix * 32767).astype(np.int16))
print("ok", mix.shape)
