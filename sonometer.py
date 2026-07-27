#!/usr/bin/env python3

import sounddevice as sd
import numpy as np
import time
import sqlite3
import threading
import json
import os
from rpi_ws281x import PixelStrip, Color

LED_PIN      = 18
LED_FREQ_HZ  = 800000
LED_DMA      = 10
LED_INVERT   = False
LED_CHANNEL  = 0

SAMPLE_RATE  = 44100
BLOCK_SIZE   = 512
DEVICE_INDEX = None

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DB_PATH      = os.path.join(BASE_DIR, 'sonometer.db')
CONFIG_PATH  = os.path.join(BASE_DIR, 'config.json')

DEFAULT_CONFIG = {
    "db_min": 40, "db_vert": 55, "db_orange": 70,
    "db_rouge": 80, "db_max": 90, "blink_speed": 0.3,
    "led_count": 60,
    "attack": 0.6, "release": 0.08,
    "rouge_duree": 3, "rouge_duree_min": 5,
    "startup_anim": "vague"
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

config = load_config()
config_mtime = 0.0
LED_COUNT = config.get('led_count', 60)

strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ,
                   LED_DMA, LED_INVERT, 200, LED_CHANNEL)
strip.begin()

current_db       = 0.0
smoothed_db      = 0.0
blink_state      = True
last_save_time   = time.time()
red_since        = None
red_blink_active = False
red_alert_start  = None


def refresh_config():
    global config, config_mtime
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
        if mtime != config_mtime:
            config = load_config()
            config_mtime = mtime
    except Exception:
        pass


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS measures
                 (timestamp INTEGER, db_level REAL)''')
    conn.commit()
    conn.close()


def save_to_db(db_val):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO measures VALUES (?, ?)",
              (int(time.time()), round(db_val, 2)))
    conn.commit()
    conn.close()


def compute_db(indata):
    rms = np.sqrt(np.mean(indata.astype(float) ** 2))
    if rms < 1e-10:
        return 0.0
    return 20 * np.log10(rms)


def smooth(raw_db, previous):
    """Attack rapide / release lent - evite le clignotement et la chute brutale."""
    attack = config.get('attack', 0.6)
    release = config.get('release', 0.08)
    if raw_db > previous:
        return previous + (raw_db - previous) * attack
    else:
        return previous + (raw_db - previous) * release


def set_leds_normal(db, blink_on):
    db_min    = config.get('db_min', 40)
    db_orange = config.get('db_orange', 70)
    db_rouge  = config.get('db_rouge', 80)
    db_max    = config.get('db_max', 90)

    db_clamped = max(db_min, min(db_max, db))
    ratio = (db_clamped - db_min) / (db_max - db_min)
    n_allumees = int(ratio * LED_COUNT)

    # Positions des seuils dans la jauge (en proportion 0-1)
    # Le vert demarre directement a db_min (pas de seuil separe)
    span = max(1, db_max - db_min)
    pos_orange = (db_orange - db_min) / span
    pos_rouge  = (db_rouge - db_min) / span

    for i in range(LED_COUNT):
        if i >= n_allumees:
            strip.setPixelColor(i, Color(0, 0, 0))
            continue
        position_ratio = i / LED_COUNT
        if position_ratio < pos_orange:
            strip.setPixelColor(i, Color(0, 255, 0))
        elif position_ratio < pos_rouge:
            strip.setPixelColor(i, Color(255, 165, 0))
        else:
            strip.setPixelColor(i, Color(255, 0, 0))
    strip.show()


def set_leds_red_alert(blink_on):
    """Toutes les LEDs clignotent en rouge - alerte critique."""
    color = Color(255, 0, 0) if blink_on else Color(0, 0, 0)
    for i in range(LED_COUNT):
        strip.setPixelColor(i, color)
    strip.show()


def blink_thread():
    global blink_state
    while True:
        blink_speed = config.get('blink_speed', 0.3)
        if red_blink_active:
            blink_state = not blink_state
            time.sleep(blink_speed)
        else:
            blink_state = True
            time.sleep(0.1)


# ─────────────────────────────────────────
# ANIMATIONS DE DEMARRAGE
# ─────────────────────────────────────────

def anim_vague():
    for cycle in range(2):
        for i in range(LED_COUNT):
            strip.setPixelColor(i, Color(0, 100, 255))
            if i > 3:
                strip.setPixelColor(i - 4, Color(0, 0, 0))
            strip.show()
            time.sleep(0.015)
        for i in range(max(0, LED_COUNT - 4), LED_COUNT):
            strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()


def anim_respiration():
    for _ in range(2):
        for b in range(0, 200, 8):
            for i in range(LED_COUNT):
                strip.setPixelColor(i, Color(0, b, 0))
            strip.show()
            time.sleep(0.015)
        for b in range(200, 0, -8):
            for i in range(LED_COUNT):
                strip.setPixelColor(i, Color(0, b, 0))
            strip.show()
            time.sleep(0.015)
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()


def wheel(pos):
    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)


def anim_arcenciel():
    for j in range(256):
        for i in range(LED_COUNT):
            strip.setPixelColor(i, wheel((i * 256 // LED_COUNT + j) & 255))
        strip.show()
        time.sleep(0.004)
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()


def anim_compteur():
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 150, 255))
        strip.show()
        time.sleep(0.012)
    time.sleep(0.2)
    for i in range(LED_COUNT - 1, -1, -1):
        strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()
        time.sleep(0.012)


def play_startup_animation():
    anim = config.get('startup_anim', 'vague')
    try:
        if anim == 'vague':
            anim_vague()
        elif anim == 'respiration':
            anim_respiration()
        elif anim == 'arcenciel':
            anim_arcenciel()
        elif anim == 'compteur':
            anim_compteur()
    except Exception as e:
        print(f"Erreur animation demarrage: {e}")
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def main():
    global current_db, smoothed_db, last_save_time, red_since, red_blink_active, red_alert_start

    init_db()
    play_startup_animation()

    t = threading.Thread(target=blink_thread, daemon=True)
    t.start()

    print("Sonometre demarre. Ctrl+C pour arreter.")
    config_check = 0

    with sd.InputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                        channels=1, dtype='int16',
                        device=DEVICE_INDEX) as stream:
        while True:
            data, _ = stream.read(BLOCK_SIZE)
            raw_db = compute_db(data)
            current_db = raw_db
            smoothed_db = smooth(raw_db, smoothed_db)

            db_rouge = config.get('db_rouge', 80)
            rouge_duree = config.get('rouge_duree', 3)
            rouge_duree_min = config.get('rouge_duree_min', 5)
            now = time.time()

            if smoothed_db >= db_rouge:
                if red_since is None:
                    red_since = now
                elapsed = now - red_since
                should_trigger = elapsed >= rouge_duree

                if should_trigger and not red_blink_active:
                    # Declenchement de l'alerte
                    red_blink_active = True
                    red_alert_start = now
                elif should_trigger and red_blink_active:
                    # Deja active, on la maintient
                    pass
            else:
                red_since = None
                if red_blink_active and red_alert_start is not None:
                    alert_elapsed = now - red_alert_start
                    if alert_elapsed >= rouge_duree_min:
                        # Duree minimale ecoulee et niveau redescendu -> on arrete
                        red_blink_active = False
                        red_alert_start = None
                    # sinon : on maintient le clignotement jusqu'a la duree minimale

            if red_blink_active:
                set_leds_red_alert(blink_state)
            else:
                set_leds_normal(smoothed_db, blink_state)

            if now - last_save_time >= 2:
                save_to_db(smoothed_db)
                last_save_time = now

            config_check += 1
            if config_check >= 50:
                refresh_config()
                config_check = 0

            time.sleep(0.02)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        for i in range(LED_COUNT):
            strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()
        print("\nArret propre.")
