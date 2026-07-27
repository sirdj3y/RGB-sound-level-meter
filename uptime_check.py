#!/usr/bin/env python3
"""
Script lancé toutes les heures via cron (sudo crontab).
Enregistre l'état du service sonometer dans la base SQLite.

Cron :
    0 * * * * /usr/bin/python3 /home/USER/webapp/uptime_check.py
"""

import sqlite3
import subprocess
import time
import os

DB_PATH = os.path.expanduser('~/sonometer.db')


def service_active(name):
    r = subprocess.run(['systemctl', 'is-active', name],
                       capture_output=True, text=True)
    return r.stdout.strip() == 'active'


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS service_uptime (
            timestamp INTEGER,
            is_active INTEGER
        )
    ''')
    hour_bucket = (int(time.time()) // 3600) * 3600
    active = 1 if service_active('sonometer') else 0
    c.execute('INSERT INTO service_uptime VALUES (?, ?)', (hour_bucket, active))
    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
