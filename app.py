#!/usr/bin/env python3

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, Response
import sqlite3, json, os, time, functools, subprocess, shutil, csv, io, threading, zipfile

app = Flask(__name__)

# Clé secrète Flask - définir la variable d'environnement FLASK_SECRET_KEY en production
# Exemple : export FLASK_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change-this-in-production')

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, 'sonometer.db')
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
START_TIME  = time.time()

DEFAULT_CONFIG = {
    "db_min":40,"db_orange":70,"db_rouge":80,"db_max":90,
    "blink_speed":0.3,"username":"admin","password":"sonometer",
    "son_actif":True,"son_delai":5,"son_type":"gong",
    "graph_duree":60,
    "led_count":60,"attack":0.6,"release":0.08,
    "rouge_duree":3,"rouge_duree_min":5,"startup_anim":"vague"
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f: return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_PATH,'w') as f: json.dump(cfg,f,indent=2)

def login_required(f):
    @functools.wraps(f)
    def decorated(*args,**kwargs):
        if not session.get('logged_in'): return redirect(url_for('login'))
        return f(*args,**kwargs)
    return decorated

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def service_status(name):
    r = subprocess.run(['systemctl','is-active',name],capture_output=True,text=True)
    return r.stdout.strip()

def format_uptime(seconds):
    s=int(seconds); h=s//3600; m=(s%3600)//60; s=s%60
    if h>0: return f"{h}h {m}m"
    if m>0: return f"{m}m {s}s"
    return f"{s}s"

def get_cpu_temp():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return round(int(f.read().strip()) / 1000, 1)
    except:
        return None

def get_system_uptime():
    try:
        with open('/proc/uptime') as f:
            secs = float(f.read().split()[0])
            return format_uptime(secs)
    except:
        return None

@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ─────────────────────────────────────────
# ROUTES PAGES
# ─────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html', config=load_config())

@app.route('/history')
def history():
    return render_template('history.html')

@app.route('/status')
def status():
    return render_template('status.html')

@app.route('/public')
def public():
    return render_template('public.html', config=load_config())

@app.route('/editor')
@login_required
def editor():
    return render_template('editor.html', files=list(EDITABLE_FILES.keys()))

@app.route('/login', methods=['GET','POST'])
def login():
    config=load_config(); error=None
    if request.method=='POST':
        if request.form['username']==config['username'] and request.form['password']==config['password']:
            session['logged_in']=True
            return redirect(url_for('config_page'))
        error='Identifiants incorrects'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('index'))

@app.route('/config', methods=['GET','POST'])
@login_required
def config_page():
    config=load_config(); saved=False
    if request.method=='POST':
        config['db_min']       = int(request.form['db_min'])
        config['db_orange']    = int(request.form['db_orange'])
        config['db_rouge']     = int(request.form['db_rouge'])
        config['db_max']       = int(request.form['db_max'])
        config['blink_speed']  = float(request.form['blink_speed'])
        config['son_actif']    = request.form.get('son_actif') == 'on'
        config['son_delai']    = int(request.form.get('son_delai', 5))
        config['son_type']     = request.form.get('son_type', 'gong')
        config['graph_duree']  = int(request.form.get('graph_duree', 60))
        config['led_count']    = int(request.form.get('led_count', 60))
        config['attack']       = float(request.form.get('attack', 0.6))
        config['release']      = float(request.form.get('release', 0.08))
        config['rouge_duree']  = int(request.form.get('rouge_duree', 3))
        config['rouge_duree_min'] = int(request.form.get('rouge_duree_min', 5))
        config['startup_anim'] = request.form.get('startup_anim', 'vague')
        if request.form.get('new_password'): config['password']=request.form['new_password']
        save_config(config); saved=True
    return render_template('config.html', config=config, saved=saved)

# ─────────────────────────────────────────
# API - DONNEES
# ─────────────────────────────────────────

@app.route('/api/data')
def api_data():
    conn=get_db(); since=int(time.time())-60
    rows=conn.execute('SELECT timestamp,db_level FROM measures WHERE timestamp>? ORDER BY timestamp',(since,)).fetchall()
    conn.close()
    return jsonify([{'t':r['timestamp'],'db':r['db_level']} for r in rows])

@app.route('/api/data/range')
def api_data_range():
    minutes = int(request.args.get('minutes', 60))
    since   = int(time.time()) - minutes * 60
    conn    = get_db()
    total_secs = minutes * 60
    grain = max(10, total_secs // 60)
    rows = conn.execute('''
        SELECT (timestamp / ?) * ? as bucket,
               AVG(db_level) as avg_db,
               MAX(db_level) as max_db
        FROM measures
        WHERE timestamp > ?
        GROUP BY bucket
        ORDER BY bucket
    ''', (grain, grain, since)).fetchall()
    peak = conn.execute(
        'SELECT MAX(db_level) as m FROM measures WHERE timestamp > ?', (since,)
    ).fetchone()
    conn.close()
    return jsonify({
        'points': [{'t':r['bucket'],'avg':round(r['avg_db'],1),'max':round(r['max_db'],1)} for r in rows],
        'peak':   round(peak['m'],1) if peak and peak['m'] else 0,
        'grain':  grain
    })

@app.route('/api/current')
def api_current():
    conn=get_db()
    row=conn.execute('SELECT timestamp,db_level FROM measures ORDER BY timestamp DESC LIMIT 1').fetchone()
    conn.close()
    if row: return jsonify({'t':row['timestamp'],'db':row['db_level']})
    return jsonify({'t':0,'db':0})

@app.route('/api/history')
def api_history():
    now    = int(time.time())
    t_from = int(request.args.get('from', now - 86400))
    t_to   = int(request.args.get('to',   now))
    span   = t_to - t_from
    if 'grain' in request.args:
        grain = int(request.args.get('grain'))
    elif span <= 3600:
        grain = 60
    elif span <= 86400:
        grain = 3600
    elif span <= 86400 * 7:
        grain = 3600 * 3
    elif span <= 86400 * 31:
        grain = 86400
    else:
        grain = 86400 * 7

    conn = get_db()
    rows = conn.execute('''
        SELECT (timestamp / ?) * ? as bucket,
               AVG(db_level) as avg_db,
               MAX(db_level) as max_db,
               COUNT(*) as n
        FROM measures
        WHERE timestamp >= ? AND timestamp <= ?
        GROUP BY bucket ORDER BY bucket
    ''', (grain, grain, t_from, t_to)).fetchall()

    stats = conn.execute('''
        SELECT AVG(db_level) as avg_db, MAX(db_level) as max_db,
               MIN(db_level) as min_db, COUNT(*) as n
        FROM measures WHERE timestamp >= ? AND timestamp <= ?
    ''', (t_from, t_to)).fetchone()

    config   = load_config()
    db_rouge = config.get('db_rouge', 80)

    red_count = conn.execute('''
        SELECT COUNT(*) as n FROM measures
        WHERE timestamp >= ? AND timestamp <= ? AND db_level >= ?
    ''', (t_from, t_to, db_rouge)).fetchone()

    conn.close()
    total   = stats['n'] if stats['n'] else 1
    red_pct = round(red_count['n'] / total * 100, 1) if total > 0 else 0

    return jsonify({
        'points': [{'bucket':r['bucket'],'avg':round(r['avg_db'],1),'max':round(r['max_db'],1),'n':r['n']} for r in rows],
        'stats':  {'avg':round(stats['avg_db'],1) if stats['avg_db'] else 0,
                   'max':round(stats['max_db'],1) if stats['max_db'] else 0,
                   'min':round(stats['min_db'],1) if stats['min_db'] else 0,
                   'total':stats['n'] if stats['n'] else 0,'red_pct':red_pct},
        'grain':grain,'from':t_from,'to':t_to
    })

@app.route('/api/uptime')
def api_uptime():
    days = 7
    now = int(time.time())
    since = now - (days * 86400)
    conn = get_db()
    rows = conn.execute(
        'SELECT timestamp, is_active FROM service_uptime WHERE timestamp >= ? ORDER BY timestamp',
        (since,)
    ).fetchall()
    conn.close()

    data_map = {r['timestamp']: r['is_active'] for r in rows}
    blocks = []
    start_hour = (since // 3600) * 3600
    for i in range(days * 24):
        ts = start_hour + (i * 3600)
        if ts in data_map:
            status = 'up' if data_map[ts] == 1 else 'down'
        elif ts > now:
            status = 'future'
        else:
            status = 'unknown'
        blocks.append({'t': ts, 'status': status})

    total_known = sum(1 for b in blocks if b['status'] in ('up', 'down'))
    total_up = sum(1 for b in blocks if b['status'] == 'up')
    uptime_pct = round(total_up / total_known * 100, 2) if total_known > 0 else 100

    return jsonify({'blocks': blocks, 'uptime_pct': uptime_pct, 'days': days})

@app.route('/api/status')
def api_status():
    disk  = shutil.disk_usage('/')
    conn  = get_db()
    last  = conn.execute('SELECT timestamp,db_level FROM measures ORDER BY timestamp DESC LIMIT 1').fetchone()
    count = conn.execute('SELECT COUNT(*) as n FROM measures').fetchone()

    from datetime import datetime
    today_start = int(datetime.now().replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
    yesterday_start = today_start - 86400

    avg_today = conn.execute(
        'SELECT AVG(db_level) as a FROM measures WHERE timestamp >= ?', (today_start,)
    ).fetchone()
    avg_yesterday = conn.execute(
        'SELECT AVG(db_level) as a FROM measures WHERE timestamp >= ? AND timestamp < ?',
        (yesterday_start, today_start)
    ).fetchone()

    config   = load_config()
    db_rouge = config.get('db_rouge', 80)
    last_red = conn.execute(
        'SELECT timestamp FROM measures WHERE db_level >= ? ORDER BY timestamp DESC LIMIT 1',
        (db_rouge,)
    ).fetchone()

    conn.close()

    return jsonify({
        'sonometer':        service_status('sonometer'),
        'webapp_uptime':    format_uptime(time.time()-START_TIME),
        'system_uptime':    get_system_uptime(),
        'cpu_temp':         get_cpu_temp(),
        'disk_used_gb':     round(disk.used/1e9,1),
        'disk_total_gb':    round(disk.total/1e9,1),
        'disk_pct':         round(disk.used/disk.total*100,1),
        'last_measure_age': int(time.time())-last['timestamp'] if last else None,
        'last_measure_db':  last['db_level'] if last else None,
        'total_measures':   count['n'] if count else 0,
        'avg_today':        round(avg_today['a'],1) if avg_today and avg_today['a'] else None,
        'avg_yesterday':    round(avg_yesterday['a'],1) if avg_yesterday and avg_yesterday['a'] else None,
        'last_red_ts':      last_red['timestamp'] if last_red else None,
    })

@app.route('/api/service/<action>', methods=['POST'])
@login_required
def service_action(action):
    if action not in ('start','stop','restart'):
        return jsonify({'error':'action invalide'}),400
    subprocess.run(['systemctl',action,'sonometer'],capture_output=True)
    time.sleep(1)
    return jsonify({'status':service_status('sonometer')})

@app.route('/api/system/<action>', methods=['POST'])
@login_required
def system_action(action):
    if action not in ('reboot','shutdown'):
        return jsonify({'error':'action invalide'}),400
    if action=='reboot':
        subprocess.Popen(['sudo','reboot'])
        return jsonify({'ok':True,'message':'Redémarrage en cours...'})
    else:
        subprocess.Popen(['sudo','shutdown','now'])
        return jsonify({'ok':True,'message':'Extinction en cours...'})

@app.route('/api/export/csv')
@login_required
def export_csv():
    now    = int(time.time())
    t_from = int(request.args.get('from', now - 86400))
    t_to   = int(request.args.get('to',   now))
    conn   = get_db()
    rows   = conn.execute(
        'SELECT timestamp,db_level FROM measures WHERE timestamp>=? AND timestamp<=? ORDER BY timestamp',
        (t_from, t_to)
    ).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['datetime','timestamp','db_level'])
    for r in rows:
        dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['timestamp']))
        writer.writerow([dt, r['timestamp'], r['db_level']])
    output.seek(0)
    filename = f"sonometer_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition':f'attachment;filename={filename}'})

@app.route('/api/data/delete', methods=['POST'])
@login_required
def delete_data():
    scope = request.json.get('scope','all')
    conn  = get_db()
    now   = int(time.time())
    if scope=='all':
        conn.execute('DELETE FROM measures')
    elif scope=='today':
        from datetime import datetime
        t0 = int(datetime.now().replace(hour=0,minute=0,second=0).timestamp())
        conn.execute('DELETE FROM measures WHERE timestamp >= ?',(t0,))
    elif scope=='week':
        conn.execute('DELETE FROM measures WHERE timestamp >= ?',(now-86400*7,))
    elif scope=='month':
        conn.execute('DELETE FROM measures WHERE timestamp >= ?',(now-86400*30,))
    conn.commit()
    count = conn.execute('SELECT COUNT(*) as n FROM measures').fetchone()
    conn.close()
    return jsonify({'ok':True,'remaining':count['n']})

@app.route('/api/backup')
@login_required
def backup():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(DB_PATH):
            zf.write(DB_PATH, 'sonometer.db')
        if os.path.exists(CONFIG_PATH):
            zf.write(CONFIG_PATH, 'config.json')
        sonometer_py = os.path.join(BASE_DIR, 'sonometer.py')
        if os.path.exists(sonometer_py):
            zf.write(sonometer_py, 'sonometer.py')
        zf.write(__file__, 'app.py')
        templates_dir = os.path.join(BASE_DIR, 'templates')
        if os.path.exists(templates_dir):
            for fname in os.listdir(templates_dir):
                fpath = os.path.join(templates_dir, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, f'templates/{fname}')
    buffer.seek(0)
    filename = f"sonometer_backup_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    return Response(buffer.getvalue(), mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment;filename={filename}'})

# ─────────────────────────────────────────
# API - TEST LED
# ─────────────────────────────────────────

def _restart_sonometer_later(delay):
    threading.Timer(delay, lambda: subprocess.Popen(['sudo', 'systemctl', 'start', 'sonometer'])).start()

@app.route('/api/led/test', methods=['POST'])
@login_required
def led_test():
    data = request.get_json(silent=True) or {}
    count = int(data.get('count', 60))
    script = f"""
from rpi_ws281x import PixelStrip, Color
import time
strip = PixelStrip({count}, 18, 800000, 10, False, 150, 0)
strip.begin()
for i in range({count}):
    strip.setPixelColor(i, Color(0, 150, 255))
strip.show()
time.sleep(3)
for i in range({count}):
    strip.setPixelColor(i, Color(0,0,0))
strip.show()
"""
    subprocess.Popen(['sudo', 'systemctl', 'stop', 'sonometer'])
    time.sleep(0.5)
    subprocess.Popen(['python3', '-c', script])
    _restart_sonometer_later(4.0)
    return jsonify({'ok': True})

@app.route('/api/led/test-anim', methods=['POST'])
@login_required
def led_test_anim():
    data = request.get_json(silent=True) or {}
    anim = data.get('anim', 'vague')
    led_count = load_config().get('led_count', 60)
    script = f"""
from rpi_ws281x import PixelStrip, Color
import time
LED_COUNT = {led_count}
strip = PixelStrip(LED_COUNT, 18, 800000, 10, False, 150, 0)
strip.begin()
def wheel(pos):
    if pos < 85: return Color(pos*3, 255-pos*3, 0)
    elif pos < 170:
        pos -= 85; return Color(255-pos*3, 0, pos*3)
    else:
        pos -= 170; return Color(0, pos*3, 255-pos*3)
anim = '{anim}'
if anim == 'vague':
    for cycle in range(2):
        for i in range(LED_COUNT):
            strip.setPixelColor(i, Color(0,100,255))
            if i > 3: strip.setPixelColor(i-4, Color(0,0,0))
            strip.show(); time.sleep(0.015)
        for i in range(max(0,LED_COUNT-4), LED_COUNT):
            strip.setPixelColor(i, Color(0,0,0))
        strip.show()
elif anim == 'respiration':
    for _ in range(2):
        for b in range(0,200,8):
            for i in range(LED_COUNT): strip.setPixelColor(i, Color(0,b,0))
            strip.show(); time.sleep(0.015)
        for b in range(200,0,-8):
            for i in range(LED_COUNT): strip.setPixelColor(i, Color(0,b,0))
            strip.show(); time.sleep(0.015)
elif anim == 'arcenciel':
    for j in range(256):
        for i in range(LED_COUNT):
            strip.setPixelColor(i, wheel((i*256//LED_COUNT+j)&255))
        strip.show(); time.sleep(0.004)
elif anim == 'compteur':
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0,150,255))
        strip.show(); time.sleep(0.012)
    time.sleep(0.2)
    for i in range(LED_COUNT-1,-1,-1):
        strip.setPixelColor(i, Color(0,0,0))
        strip.show(); time.sleep(0.012)
for i in range(LED_COUNT):
    strip.setPixelColor(i, Color(0,0,0))
strip.show()
"""
    subprocess.Popen(['sudo', 'systemctl', 'stop', 'sonometer'])
    time.sleep(0.5)
    subprocess.Popen(['python3', '-c', script])
    _restart_sonometer_later(5.0)
    return jsonify({'ok': True})

# ─────────────────────────────────────────
# EDITEUR DE FICHIERS
# ─────────────────────────────────────────

EDITABLE_FILES = {
    'sonometer.py':   os.path.join(BASE_DIR, 'sonometer.py'),
    'app.py':         os.path.join(BASE_DIR, 'app.py'),
    'config.json':    os.path.join(BASE_DIR, 'config.json'),
    'index.html':     os.path.join(BASE_DIR, 'templates', 'index.html'),
    'history.html':   os.path.join(BASE_DIR, 'templates', 'history.html'),
    'status.html':    os.path.join(BASE_DIR, 'templates', 'status.html'),
    'config.html':    os.path.join(BASE_DIR, 'templates', 'config.html'),
    'public.html':    os.path.join(BASE_DIR, 'templates', 'public.html'),
    'login.html':     os.path.join(BASE_DIR, 'templates', 'login.html'),
    'editor.html':    os.path.join(BASE_DIR, 'templates', 'editor.html'),
}

@app.route('/api/editor/load')
@login_required
def editor_load():
    name = request.args.get('file')
    if name not in EDITABLE_FILES:
        return jsonify({'error':'fichier non autorisé'}),403
    with open(EDITABLE_FILES[name],'r') as f:
        return jsonify({'content':f.read(),'name':name})

@app.route('/api/editor/save', methods=['POST'])
@login_required
def editor_save():
    data    = request.json
    name    = data.get('file')
    content = data.get('content','')
    if name not in EDITABLE_FILES:
        return jsonify({'error':'fichier non autorisé'}),403
    with open(EDITABLE_FILES[name],'w') as f:
        f.write(content)
    if name=='sonometer.py':
        subprocess.run(['systemctl','restart','sonometer'],capture_output=True)
    if name=='app.py':
        subprocess.Popen(['systemctl','restart','webapp'])
    return jsonify({'ok':True})

if __name__=='__main__':
    if not os.path.exists(CONFIG_PATH): save_config(DEFAULT_CONFIG)
    app.run(host='0.0.0.0', port=5000, debug=False)
