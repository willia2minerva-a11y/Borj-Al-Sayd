from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, g
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, SpellConfig, Notification, GroupMessage
from functools import wraps
from datetime import datetime, timedelta
import os, base64, random, math, time, traceback

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

app = Flask(__name__)
app.jinja_env.globals.update(getattr=getattr)

MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    raise Exception("MONGO_URI environment variable not set")

if 'retryWrites=true' not in MONGO_URI:
    sep = '&' if '?' in MONGO_URI else '?'
    MONGO_URI += f'{sep}retryWrites=true'

app.config['MONGODB_SETTINGS'] = {
    'host': MONGO_URI,
    'connect': True,
    'tls': True,
    'tlsAllowInvalidCertificates': True,
    'connectTimeoutMS': 30000,
    'socketTimeoutMS': 30000,
    'serverSelectionTimeoutMS': 30000,
    'maxPoolSize': 10
}

# 🔒 حماية الجلسات الخالدة
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'SEPHAR_MAZE_IMMORTAL_SECRET_KEY_999')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
db.init_app(app)

_settings_cache = {'data': None, 'timestamp': 0}
_SETTINGS_CACHE_TTL = 10  

# 🗺️ خريطة المتاهة المعمارية للطابق الأول (لا يمكن التنقل إلا للغرف المجاورة)
F1_MAP = {
    'الساحة': ['الممر العظيم', 'قبو التخزين', 'قاعة المخطوطات', 'مذبح الطلاسم'],
    'الممر العظيم': ['الساحة', 'مرصد النجوم', 'قاعة المخطوطات'],
    'قبو التخزين': ['الساحة', 'غرفة البصيرة'],
    'قاعة المخطوطات': ['الساحة', 'الممر العظيم'],
    'مذبح الطلاسم': ['الساحة', 'بوابة الطابق 2'],
    'غرفة البصيرة': ['قبو التخزين'],
    'مرصد النجوم': ['الممر العظيم'],
    'بوابة الطابق 2': ['مذبح الطلاسم']
}

# 📜 المهام المتاحة للطابق الأول
TASKS_POOL = [
    {"room": "قاعة المخطوطات", "name": "فك تشفير الرموز"},
    {"room": "قاعة المخطوطات", "name": "ترميم المخطوطة"},
    {"room": "مذبح الطلاسم", "name": "إشعال البخور"},
    {"room": "مذبح الطلاسم", "name": "رسم دائرة التعاويذ"},
    {"room": "قبو التخزين", "name": "ترتيب صناديق الآثار"},
    {"room": "قبو التخزين", "name": "جرد المؤن"},
    {"room": "الساحة", "name": "إصلاح النافورة"},
    {"room": "الساحة", "name": "تنظيف الحجر القديم"},
    {"room": "الممر العظيم", "name": "إضاءة المشاعل"},
    {"room": "مرصد النجوم", "name": "توجيه العدسات"}
]

def get_cached_settings():
    now = time.time()
    if _settings_cache['data'] is None or (now - _settings_cache['timestamp']) > _SETTINGS_CACHE_TTL:
        try:
            settings = GlobalSettings.objects(setting_name='main_config').first()
            if not settings: 
                settings = GlobalSettings(setting_name='main_config').save()
            _settings_cache['data'] = settings
            _settings_cache['timestamp'] = now
        except: 
            return None
    return _settings_cache['data']

def compress_image(image_data, quality=70, max_size=(500, 500)):
    if not HAS_PIL: 
        return image_data
    try:
        from io import BytesIO
        img = Image.open(BytesIO(image_data))
        if img.mode in ("RGBA", "P"): 
            img = img.convert("RGB")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        output = BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()
    except: 
        return image_data

def process_f1_meeting_end(settings, gid_str):
    gid = int(gid_str)
    members = User.objects(group_id=gid, status='active')
    if members:
        max_votes = 0
        kicked_user = None
        tie = False
        
        for m in members:
            if m.f1_votes_received > max_votes: 
                max_votes = m.f1_votes_received
                kicked_user = m
                tie = False
            elif m.f1_votes_received == max_votes and max_votes > 0: 
                tie = True
                
        if kicked_user and not tie:
            kicked_user.update(set__status='eliminated', set__freeze_reason='طُرد بتصويت المجموعة')
            GroupMessage(group_id=gid, sender_name="النظام", message=f"⚖️ تم طرد {kicked_user.username} بالأغلبية!", is_system_msg=True).save()
            
            if getattr(kicked_user, 'is_cursed', False):
                GroupMessage(group_id=gid, sender_name="النظام", message="✨ لقد طردتم الملعون! فازت المجموعة وفُتحت البوابة!", is_system_msg=True).save()
                User.objects(group_id=gid, status='active').update(set__zone='الطابق 2')
        else:
            GroupMessage(group_id=gid, sender_name="النظام", message="⚖️ انتهى التصويت بالتعادل أو تم التخطي. لم يُطرد أحد!", is_system_msg=True).save()
            
        members.update(set__f1_has_voted=False, set__f1_votes_received=0)
    
    User.objects(group_id=gid, status='dead_body').update(set__status='eliminated')
    meetings = settings.f1_active_meetings
    if gid_str in meetings: 
        del meetings[gid_str]
    GlobalSettings.objects(setting_name='main_config').update_one(set__f1_active_meetings=meetings)

def execute_trap_effect(user, trap):
    if '_' not in trap.puzzle_type: 
        return
    eff = trap.puzzle_type.split('_', 1)[1]
    
    if eff == 'give_points':
        user.update(inc__points=trap.reward_points, inc__intelligence_points=10)
        flash(f'نجاح! حصلت على {trap.reward_points} دنانير!', 'success')
    elif eff == 'steal_points':
        user.update(set__points=max(0, user.points - trap.trap_penalty_points), dec__intelligence_points=5)
        flash(f'فخ مرعب! سُرق منك {trap.trap_penalty_points} دنانير!', 'error')
    elif eff == 'give_item':
        if trap.reward_item: 
            user.update(push__inventory=trap.reward_item)
            flash(f'نجاح! حصلت على الأداة: {trap.reward_item}', 'success')
    elif eff == 'steal_item':
        if user.inventory:
            stolen = random.choice(user.inventory)
            user.update(pull__inventory=stolen)
            flash(f'فخ مرعب! سُرقت منك الأداة: {stolen}', 'error')
        else: 
            flash('نجوت! حاول الفخ سرقتك لكن حقيبتك فارغة.', 'info')
    elif eff == 'give_seal':
        if trap.reward_item and trap.reward_item not in user.collected_seals:
            user.update(push__inventory=trap.reward_item)
            flash(f'نجاح أسطوري! حصلت على ختم: {trap.reward_item}', 'success')
        else: 
            flash('حصلت على ختم تملكه مسبقاً!', 'info')
    elif eff == 'quicksand':
        dur = trap.trap_duration_minutes or 5
        user.update(set__quicksand_lock_until=datetime.utcnow() + timedelta(minutes=dur))
        flash(f'وقعت في فخ الرمال! أنت مجمد لمدة {dur} دقائق.', 'error')

@app.before_request
def fast_health_check():
    if request.method == 'HEAD' or request.path == '/health': 
        return "OK", 200

def check_achievements(user):
    try:
        new_ach = []
        user_achs = getattr(user, 'achievements', []) or []
        if getattr(user, 'stats_ghosts_caught', 0) >= 5 and 'صائد الأشباح 👻' not in user_achs:
            user.update(push__achievements='صائد الأشباح 👻', inc__intelligence_points=10)
            new_ach.append('صائد الأشباح 👻')
        if getattr(user, 'stats_puzzles_solved', 0) >= 5 and 'حكيم سيفار 📜' not in user_achs:
            user.update(push__achievements='حكيم سيفار 📜', inc__intelligence_points=20)
            new_ach.append('حكيم سيفار 📜')
        if len(getattr(user, 'friends', []) or []) >= 5 and 'حليف القوم 🤝' not in user_achs:
            user.update(push__achievements='حليف القوم 🤝', inc__loyalty_points=15)
            new_ach.append('حليف القوم 🤝')
        if new_ach: 
            flash(f'🏆 إنجاز جديد: {", ".join(new_ach)}', 'success')
    except: 
        pass

def check_lazy_death_and_bleed(user, settings):
    try:
        if not user or getattr(user, 'role', '') == 'admin' or getattr(user, 'status', '') not in ['active', 'dead_body']: 
            return
            
        now = datetime.utcnow()
        last_act = getattr(user, 'last_active', None) or getattr(user, 'created_at', None) or now
        
        if (now - last_act).total_seconds() / 3600.0 > 72: 
            user.update(set__health=0, set__status='eliminated', set__freeze_reason='ابتلعته الرمال')
            return
            
        if getattr(settings, 'war_mode', False) and user.status == 'active':
            safe_until = (getattr(user, 'last_action_time', None) or now) + timedelta(minutes=getattr(settings, 'safe_time_minutes', 120))
            if now > safe_until:
                start_bleed_time = max(getattr(user, 'last_health_check', None) or safe_until, safe_until)
                minutes_passed = (now - start_bleed_time).total_seconds() / 60.0
                bleed_rate = getattr(settings, 'bleed_rate_minutes', 60)
                
                if bleed_rate > 0 and minutes_passed >= bleed_rate:
                    cycles = math.floor(minutes_passed / bleed_rate)
                    new_health = max(0, user.health - (cycles * getattr(settings, 'bleed_amount', 1)))
                    
                    if new_health <= 0:
                        user.update(set__health=0, set__status='eliminated', set__freeze_reason='نزف حتى الموت', set__last_health_check=now)
                        GlobalSettings.objects(setting_name='main_config').update_one(inc__dead_count=1)
                        if (getattr(settings, 'dead_count', 0) + 1) >= getattr(settings, 'war_kill_target', 15):
                            GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False)
                            User.objects(status='active', role='hunter', hunter_id__ne=1000).update(set__zone='الطابق 2')
                    else: 
                        user.update(set__health=new_health, set__last_health_check=now)
    except: 
        pass

@app.before_request
def pre_process():
    if request.endpoint in ['static', 'get_avatar', 'fast_health_check', 'login', 'register', 'logout']: 
        return
        
    try: 
        g.settings = get_cached_settings()
    except Exception as e: 
        return f"<div style='direction:rtl; background:#0a0a0a; color:#e74c3c; padding:30px; text-align:center;'><h1>🚨 مشكلة اتصال</h1><p>{str(e)}</p></div>", 503

    settings = g.settings
    now = datetime.utcnow()
    
    if settings:
        if settings.war_mode and settings.war_end_time and now >= settings.war_end_time:
            GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False)
            User.objects(status='active').update(set__health=100)
            _settings_cache['timestamp'] = 0
            
        if settings.gates_mode_active and settings.gates_end_time and now >= settings.gates_end_time:
            User.objects(status='active', chosen_gate=0, hunter_id__ne=1000).update(set__status='eliminated', set__freeze_reason='انتهى وقت البوابات')
            GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=False)
            _settings_cache['timestamp'] = 0
            
        if settings.floor3_mode_active and not getattr(settings, 'floor3_paused', False) and settings.vote_end_time and now >= settings.vote_end_time:
            all_active = User.objects(status='active', role='hunter', hunter_id__ne=1000)
            slackers = User.objects(has_voted=False, status='active', role='hunter', hunter_id__ne=1000)
            
            if slackers.count() > 0 and all_active.count() > 0:
                bonus_votes = (slackers.count() * 100.0) / all_active.count()
                for v in all_active: 
                    v.update(inc__survival_votes=bonus_votes)
                    
            slackers.update(set__status='eliminated', set__freeze_reason='تخاذل في المحكمة')
            for u in User.objects(status='active', role='hunter', hunter_id__ne=1000).order_by('-survival_votes')[:settings.vote_top_n]: 
                u.update(set__zone='المعركة الأخيرة')
            GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=False, set__floor3_results_active=True)
            _settings_cache['timestamp'] = 0

        if getattr(settings, 'floor1_mode_active', False) and getattr(settings, 'f1_active_meetings', {}):
            for gid_str, meeting_data in list(settings.f1_active_meetings.items()):
                if now >= datetime.fromisoformat(meeting_data['end_time']):
                    process_f1_meeting_end(settings, gid_str)
            _settings_cache['timestamp'] = 0

        if getattr(settings, 'floor1_darkness_until', None) and now >= settings.floor1_darkness_until:
            GlobalSettings.objects(setting_name='main_config').update_one(unset__floor1_darkness_until=1)
            _settings_cache['timestamp'] = 0
            
        if getattr(settings, 'floor1_locked_until', None) and now >= settings.floor1_locked_until:
            GlobalSettings.objects(setting_name='main_config').update_one(set__floor1_locked_room='', unset__floor1_locked_until=1)
            _settings_cache['timestamp'] = 0

        if settings.maintenance_mode and settings.maintenance_until and now > settings.maintenance_until:
            GlobalSettings.objects(setting_name='main_config').update_one(set__maintenance_mode=False, set__maintenance_pages=[])
            
        if settings.maintenance_mode:
            if 'user_id' not in session or not User.objects(id=session['user_id']).first() or User.objects(id=session['user_id']).first().role != 'admin':
                m_pages = settings.maintenance_pages or []
                if 'all' in m_pages or request.endpoint in m_pages: 
                    return render_template('locked.html', message='المتاهة قيد الصيانة ⏳')

    user = None
    if 'user_id' in session:
        user = User.objects(id=session['user_id']).first()
        if not user: 
            session.clear()
            return redirect(url_for('login'))
            
        if getattr(user, 'hunter_id', None) is None:
            existing_ids = [u.hunter_id for u in User.objects.only('hunter_id').order_by('hunter_id') if u.hunter_id is not None]
            new_id = 1000
            for eid in existing_ids:
                if eid == new_id: new_id += 1
                elif eid > new_id: break
            user.update(set__hunter_id=new_id)
            user.reload()
            flash('تم تحديث هويتك تلقائياً.', 'info')
            return redirect(request.path)

        if not user.last_active or (now - user.last_active).total_seconds() > 3600: 
            user.update(set__last_active=now)
            
        check_lazy_death_and_bleed(user, settings)

        if user.zone in ['الطابق 3', 'المعركة الأخيرة']:
            if getattr(user, 'totem_self', False): 
                user.update(set__totem_self=False)
                flash('🔥 احترق توتم إعادة الحياة بفعل قوى الطابق!', 'error')
            if getattr(user, 'has_shield', False): 
                user.update(set__has_shield=False)
                flash('🛡️ احترق وشاح الحماية بفعل قوى الطابق!', 'error')

        if user.status == 'active' and user.quicksand_lock_until and now < user.quicksand_lock_until:
            tl = user.quicksand_lock_until - now
            return render_template('locked.html', message=f'مقيّد في الرمال لـ {tl.seconds // 60}د')
            
        if user.gate_status == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']: 
            return render_template('gate_test.html', message=getattr(settings, 'gates_test_message', 'الاختبار'), user=user)

    g.user = user

@app.route('/avatar/<int:hunter_id>')
def get_avatar(hunter_id):
    try:
        user = User.objects(hunter_id=hunter_id).only('avatar', 'status').first()
        if user:
            if getattr(user, 'status', '') in ['eliminated', 'dead_body']: 
                return Response('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#110d09"/><text x="50" y="55" font-size="60" text-anchor="middle" dominant-baseline="middle">💀</text></svg>''', mimetype="image/svg+xml", headers={'Cache-Control': 'public, max-age=31536000'})
            if getattr(user, 'status', '') == 'frozen': 
                return Response('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#110d09"/><text x="50" y="55" font-size="60" text-anchor="middle" dominant-baseline="middle">🧊</text></svg>''', mimetype="image/svg+xml", headers={'Cache-Control': 'public, max-age=31536000'})
            if getattr(user, 'avatar', '') and user.avatar.startswith('data:image'):
                header, encoded = user.avatar.split(",", 1)
                mime = header.split(":")[1].split(";")[0]
                return Response(base64.b64decode(encoded), mimetype=mime)
    except: pass
    return Response('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#110d09"/><circle cx="50" cy="35" r="20" fill="#d4af37"/><path d="M20 90c0-20 15-35 30-35s30 15 30 35" fill="#d4af37"/></svg>''', mimetype="image/svg+xml", headers={'Cache-Control': 'public, max-age=31536000'})

@app.context_processor
def inject_globals():
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'unread_notifs': 0, 'current_user': getattr(g, 'user', None), 'settings': getattr(g, 'settings', None)}
    if notifs['current_user']:
        u = notifs['current_user']
        now = datetime.utcnow()
        try:
            notifs['un_news'] = News.objects(category='news', status='approved', created_at__gt=(getattr(u, 'last_seen_news', None) or now)).count()
            notifs['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=(getattr(u, 'last_seen_puzzles', None) or now)).count()
            notifs['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=(getattr(u, 'last_seen_decs', None) or now)).count()
            notifs['un_store'] = StoreItem.objects(created_at__gt=(getattr(u, 'last_seen_store', None) or now)).count()
            notifs['unread_notifs'] = Notification.objects(target_hunter_id=u.hunter_id, is_read=False).count()
        except: pass
    return {**notifs, 'default_avatar': "data:image/svg+xml;base64," + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#110d09"/><circle cx="50" cy="35" r="20" fill="#d4af37"/><path d="M20 90c0-20 15-35 30-35s30 15 30 35" fill="#d4af37"/></svg>').decode('utf-8')}

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if getattr(g, 'user', None) is None or g.user.role != 'admin': return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def home():
    settings = getattr(g, 'settings', None)
    user = getattr(g, 'user', None)
    test_winner = User.objects(hunter_id=int(request.args.get('test_victory'))).first() if user and user.role == 'admin' and request.args.get('test_victory') and request.args.get('test_victory').isdigit() else None
    emperor = User.objects(hunter_id=1000).first()
    active_hunters = User.objects(status='active', role='hunter', hunter_id__ne=1000, id__ne=user.id if user else None) if settings and settings.floor3_mode_active else []
        
    room_players = []
    dead_bodies_in_room = []
    is_dark = False
    adjacent_rooms = []
    has_meeting = False
    meeting_info = None
    admin_dots = {}
    camera_feeds = {}
    
    if settings and getattr(settings, 'floor1_mode_active', False) and user and user.status == 'active':
        gid_str = str(user.group_id)
        if gid_str in getattr(settings, 'f1_active_meetings', {}):
            has_meeting = True
            meeting_info = settings.f1_active_meetings[gid_str]
            
        if getattr(settings, 'floor1_darkness_until', None) and datetime.utcnow() < settings.floor1_darkness_until: 
            is_dark = True
        
        if not is_dark: 
            room_players = User.objects(group_id=user.group_id, current_room=user.current_room, status='active', id__ne=user.id)
            
        dead_bodies_in_room = User.objects(group_id=user.group_id, current_room=user.current_room, status='dead_body')
        adjacent_rooms = F1_MAP.get(getattr(user, 'current_room', 'الساحة'), [])
        Notification.objects(target_hunter_id=user.hunter_id, is_read=False).update(set__is_read=True)

        if user.current_room == 'غرفة البصيرة':
            for u in User.objects(group_id=user.group_id, status__in=['active', 'dead_body']):
                admin_dots[u.current_room] = admin_dots.get(u.current_room, 0) + 1
        elif user.current_room == 'مرصد النجوم':
            for u in User.objects(group_id=user.group_id, status='active', current_room__in=['الممر العظيم', 'الساحة', 'قاعة المخطوطات']):
                if u.current_room not in camera_feeds: camera_feeds[u.current_room] = []
                camera_feeds[u.current_room].append(u.username)

    f3_users = User.objects(status='active', role='hunter', survival_votes__gt=0).order_by('-survival_votes')
    return render_template('index.html', emperor=emperor, test_winner=test_winner, active_hunters=active_hunters, room_players=room_players, dead_bodies_in_room=dead_bodies_in_room, is_dark=is_dark, adjacent_rooms=adjacent_rooms, has_meeting=has_meeting, meeting_info=meeting_info, admin_dots=admin_dots, camera_feeds=camera_feeds, f3_users=f3_users)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(getattr(user, 'password_hash', ''), request.form['password']):
            session.permanent = True
            session['user_id'] = str(user.id)
            user.update(set__last_active=datetime.utcnow())
            if user.status == 'inactive': flash('حسابك قيد المراجعة. التصفح متاح.', 'info')
            if user.status in ['eliminated', 'frozen', 'dead_body']: flash('حسابك موقوف عن اللعب.', 'error')
            return redirect(url_for('home'))
        flash('البيانات خاطئة.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fb_link = request.form.get('facebook_link', '').strip()
        if not fb_link: flash('رابط الفيسبوك إلزامي!', 'error'); return redirect(url_for('register'))
        if User.objects(username=request.form['username']).first(): flash('الاسم مستخدم.', 'error'); return redirect(url_for('register'))
        
        existing_ids = [u.hunter_id for u in User.objects.only('hunter_id').order_by('hunter_id') if u.hunter_id is not None]
        new_id = 1000
        for eid in existing_ids:
            if eid == new_id: new_id += 1
            elif eid > new_id: break
            
        User(hunter_id=new_id, username=request.form['username'], password_hash=generate_password_hash(request.form['password']), role='admin' if new_id == 1000 else 'hunter', status='active' if new_id == 1000 else 'inactive', zone='البوابات', special_rank='مستكشف', facebook_link=fb_link).save()
        flash('تم التسجيل! حسابك قيد المراجعة.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    user = g.user
    my_items = StoreItem.objects(name__in=getattr(user, 'inventory', []) or [])
    return render_template('profile.html', user=user, my_items=my_items, my_seals=[i for i in my_items if getattr(i, 'item_type', '') == 'seal'])

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = g.user
    action = request.form.get('action')
    now = datetime.utcnow()
    try:
        if action == 'change_avatar':
            file = request.files.get('avatar_file')
            if file and file.filename != '':
                data = file.read()
                if len(data) > 2 * 1024 * 1024: flash('الصورة كبيرة جداً.', 'error')
                else: user.update(set__avatar=f"data:image/jpeg;base64,{base64.b64encode(compress_image(data)).decode('utf-8')}"); flash('تم تحديث النقش!', 'success')
        elif action == 'change_name':
            new_name = request.form.get('new_name')
            if getattr(user, 'last_name_change', None) and (now - user.last_name_change).days < 15: flash('تغيير الاسم مرة كل 15 يوم!', 'error')
            elif User.objects(username=new_name).first(): flash('الاسم مستخدم!', 'error')
            else: user.update(set__username=new_name, set__last_name_change=now); flash('تم التغيير!', 'success')
        elif action == 'change_password':
            if check_password_hash(user.password_hash, request.form.get('old_password', '')) and request.form.get('new_password') == request.form.get('confirm_password'):
                user.update(set__password_hash=generate_password_hash(request.form.get('new_password')), set__last_password_change=now); flash('تم التغيير!', 'success')
    except: flash('خطأ!', 'error')
    return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']: return redirect(url_for('home'))
    my_items = StoreItem.objects(name__in=getattr(g.user, 'inventory', []) or [])
    return render_template('hunter_profile.html', target_user=target_user, my_weapons=[i for i in my_items if getattr(i, 'item_type', '')=='weapon'], my_heals=[i for i in my_items if getattr(i, 'item_type', '')=='heal'], my_spies=[i for i in my_items if getattr(i, 'item_type', '')=='spy'], my_steals=[i for i in my_items if getattr(i, 'item_type', '')=='steal'])

@app.route('/friends', methods=['GET'])
@login_required
def friends():
    search_query = request.args.get('search')
    search_result = None
    if search_query: 
        if search_query.isdigit(): search_result = User.objects(hunter_id=int(search_query)).first()
        else: search_result = User.objects(username__icontains=search_query).first()
    
    exclude_roles = ['ghost', 'cursed_ghost', 'admin']
    exclude_ids = [g.user.hunter_id] + getattr(g.user, 'friends', []) + getattr(g.user, 'friend_requests', [])
    suggested_hunters = User.objects(status='active', role__nin=exclude_roles, hunter_id__nin=exclude_ids).order_by('-last_active')[:30]
    
    return render_template('friends.html', user=g.user, search_result=search_result, friend_requests=User.objects(hunter_id__in=getattr(g.user, 'friend_requests', [])), friends=User.objects(hunter_id__in=getattr(g.user, 'friends', [])), suggested_hunters=suggested_hunters)

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = g.user
    target = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
    if user.status != 'active': flash('حسابك موقوف عن اللعب.', 'error'); return redirect(request.referrer or url_for('home'))
    if not target or target.status not in ['active', 'inactive']: return redirect(request.referrer or url_for('home'))
    if target.id == user.id: flash('لا يمكنك التحالف مع نفسك!', 'error'); return redirect(request.referrer or url_for('home'))
    
    if getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_answer=str(target.hunter_id), category='hidden').first()
        if trap and str(user.id) not in getattr(trap, 'winners_list', []) and getattr(trap, 'current_winners', 0) < getattr(trap, 'max_winners', 1):
            if trap.puzzle_type.startswith('ghost_'): 
                execute_trap_effect(user, trap)
                trap.update(inc__current_winners=1, push__winners_list=str(user.id))
        else: flash('اختفى الشبح.', 'info')
    elif target.hunter_id not in getattr(user, 'friends', []) and user.hunter_id not in getattr(target, 'friend_requests', []): 
        target.update(push__friend_requests=user.hunter_id); flash('أُرسل الطلب.', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = g.user; target = User.objects(hunter_id=target_id).first()
    if target:
        if user.hunter_id in getattr(target, 'friend_requests', []): 
            target.update(pull__friend_requests=user.hunter_id)
        elif target.hunter_id in getattr(user, 'friends', []): 
            user.update(pull__friends=target.hunter_id, dec__loyalty_points=20)
            target.update(pull__friends=user.hunter_id)
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_request', methods=['POST'])
@login_required
def cancel_request():
    user = g.user; target = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
    if target and user.hunter_id in getattr(target, 'friend_requests', []): 
        target.update(pull__friend_requests=user.hunter_id); flash('تم السحب.', 'info')
    return redirect(request.referrer or url_for('home'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = g.user; friend = User.objects(hunter_id=friend_id).first()
    if user.status != 'active': flash('حسابك موقوف.', 'error'); return redirect(request.referrer or url_for('home'))
    if friend and friend.status in ['active', 'inactive'] and friend_id in getattr(user, 'friend_requests', []): 
        user.update(pull__friend_requests=friend_id, push__friends=friend_id)
        friend.update(push__friends=user.hunter_id)
        check_achievements(user)
    return redirect(request.referrer or url_for('home'))

# ==========================================
# 👑 لوحة الإدارة (Admin Panel)
# ==========================================
@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    if request.method == 'POST':
        act = request.form.get('action')
        
        if act == 'toggle_gates':
            if getattr(settings, 'gates_mode_active', False):
                GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=False)
                flash('تم إيقاف البوابات.', 'success')
            else:
                gates_hours = int(request.form.get('gates_hours') or 0)
                g_end = datetime.utcnow() + timedelta(hours=gates_hours) if gates_hours > 0 else None
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__gates_mode_active=True, set__gates_end_time=g_end,
                    set__gates_description=request.form.get('desc', ''),
                    set__gate_1_name=request.form.get('g1', ''),
                    set__gate_2_name=request.form.get('g2', ''),
                    set__gate_3_name=request.form.get('g3', '')
                )
                flash('تم فتح البوابات!', 'success')
        
        elif act == 'toggle_floor1':
            if getattr(settings, 'floor1_mode_active', False):
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor1_mode_active=False, set__f1_active_meetings={})
                flash('تم إيقاف الطابق الأول.', 'success')
            else:
                active_users = list(User.objects(status='active', hunter_id__ne=1000))
                random.shuffle(active_users)
                group_size = int(request.form.get('group_size', 5))
                group_id = 1
                for i in range(0, len(active_users), group_size):
                    members = active_users[i:i + group_size]
                    if members:
                        cursed_idx = random.randint(0, len(members) - 1)
                        for j, m in enumerate(members): 
                            random_tasks = random.sample(TASKS_POOL, 3)
                            m.update(
                                set__group_id=group_id, set__is_cursed=(j==cursed_idx), 
                                set__current_room='الساحة', set__f1_has_voted=False, 
                                set__f1_votes_received=0, set__f1_tasks=random_tasks,
                                set__gems_collected=0, set__used_vent=False, set__emergency_used=False
                            )
                        group_id += 1
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__floor1_mode_active=True, 
                    set__floor1_move_cooldown=int(request.form.get('move_cooldown', 30)), 
                    set__f1_active_meetings={}
                )
                flash('بدأ الطابق الأول ووزعت اللعنات والمهام!', 'success')
        
        elif act == 'cancel_f1_meeting':
            gid = request.form.get('group_id')
            if gid and str(gid) in settings.f1_active_meetings:
                meetings = settings.f1_active_meetings
                del meetings[str(gid)]
                GlobalSettings.objects(setting_name='main_config').update_one(set__f1_active_meetings=meetings)
                User.objects(group_id=int(gid)).update(set__f1_has_voted=False, set__f1_votes_received=0)
                flash(f'تم إلغاء اجتماع المجموعة {gid} بنجاح!', 'success')
            else: 
                flash('هذه المجموعة ليست في اجتماع!', 'error')

        elif act == 'toggle_war':
            new_state = not getattr(settings, 'war_mode', False)
            war_hours = int(request.form.get('war_hours') or 0)
            end_time = datetime.utcnow() + timedelta(hours=war_hours) if war_hours > 0 and new_state else None
            GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=new_state, set__war_end_time=end_time)
            if not new_state: 
                User.objects(status='active').update(set__health=100)
            flash('تغيرت حالة الحرب الشاملة!', 'success')
            
        elif act == 'toggle_floor3':
            if getattr(settings, 'floor3_mode_active', False):
                time_left = (settings.vote_end_time - datetime.utcnow()).total_seconds() if settings.vote_end_time else 0
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__floor3_mode_active=False, set__floor3_paused=True, set__floor3_time_left=max(0, int(time_left))
                )
                flash('تم إيقاف/تجميد المحكمة وحفظ الوقت!', 'success')
            elif getattr(settings, 'floor3_paused', False):
                new_end = datetime.utcnow() + timedelta(seconds=settings.floor3_time_left)
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__floor3_mode_active=True, set__floor3_paused=False, set__vote_end_time=new_end
                )
                flash('تم استئناف المحكمة الكبرى!', 'success')
            else:
                vote_hours = int(request.form.get('vote_hours') or 0)
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__floor3_mode_active=True, set__floor3_results_active=False, 
                    set__vote_end_time=datetime.utcnow() + timedelta(hours=vote_hours) if vote_hours > 0 else None, 
                    set__vote_top_n=int(request.form.get('top_n', 5))
                )
                flash('بدأت المحكمة الكبرى!', 'success')
                
        elif act == 'reset_floor3':
            User.objects(role='hunter').update(set__has_voted=False, set__survival_votes=0.0, set__f3_votes_cast={})
            GlobalSettings.objects(setting_name='main_config').update_one(
                set__floor3_mode_active=False, set__floor3_paused=False, set__floor3_results_active=False
            )
            flash('تم تصفير محكمة الطابق الثالث بالكامل!', 'success')
            
        elif act == 'toggle_final_battle': 
            new_state = not getattr(settings, 'final_battle_mode', False)
            if new_state:
                emp_hp = int(request.form.get('emperor_hp') or 100000)
                User.objects(hunter_id=1000).update(set__health=emp_hp)
            GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=new_state)
            flash('تغيرت حالة المعركة الأخيرة!', 'success')

        elif act == 'add_standalone_puzzle':
            cat = request.form.get('trap_category')
            eff = request.form.get('trap_effect')
            ans = request.form.get('puzzle_answer')
            News(
                title="كيان مخفي", content="خفي", category='hidden', 
                puzzle_type=f"{cat}_{eff}", puzzle_answer=ans, 
                reward_points=int(request.form.get('reward_points') or 0), 
                trap_penalty_points=int(request.form.get('trap_penalty') or 0), 
                reward_item=request.form.get('reward_item', ''), 
                trap_duration_minutes=int(request.form.get('trap_duration') or 0), 
                max_winners=int(request.form.get('max_winners') or 1)
            ).save()
            if cat == 'ghost': 
                User(hunter_id=int(ans), username=f"شبح_{ans}", password_hash="dummy", role='ghost', status='active').save()
            flash('تم زرع الفخ/الشبح بذكاء!', 'success')
            
        elif act == 'bulk_action':
            bt = request.form.get('bulk_type')
            for uid in request.form.getlist('selected_users'):
                u = User.objects(id=uid).first()
                if u and u.hunter_id != 1000:
                    if bt == 'hard_delete': u.delete()
                    elif bt == 'activate': u.update(set__status='active', set__health=100)
                    elif bt == 'eliminate': u.update(set__status='eliminated', set__freeze_reason='قرار إداري')
                    elif bt == 'freeze': u.update(set__status='frozen')
                    elif bt == 'move_zone': u.update(set__zone=request.form.get('bulk_zone', 'الطابق 1'))
            flash('تم التنفيذ بنجاح!', 'success')

        elif act == 'update_home_settings':
            GlobalSettings.objects(setting_name='main_config').update_one(
                set__home_title=request.form.get('home_title', 'البوابة'), 
                set__global_news_active=bool(request.form.get('global_news_active')), 
                set__global_news_text=request.form.get('global_news_text', '')
            )
            file = request.files.get('banner_file')
            if file and file.filename != '': 
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__banner_url=f"data:{file.content_type};base64,{base64.b64encode(compress_image(file.read())).decode('utf-8')}"
                )
            flash('تم تحديث الإعدادات!', 'success')

        return redirect(url_for('admin_panel'))
    
    users_query = User.objects(hunter_id__ne=1000)
    search_query = request.args.get('search_user', '').strip() 
    if search_query:
        if search_query.isdigit(): users_query = users_query.filter(hunter_id=int(search_query))
        else: users_query = users_query.filter(username__icontains=search_query)
        
    hidden_traps = News.objects(category='hidden')
    all_news = News.objects(category__in=['news', 'puzzle', 'declaration']).order_by('-created_at')
    spells = SpellConfig.objects().order_by('-created_at')
    
    return render_template('admin.html', users=users_query.order_by('-last_active')[:100], settings=settings, search_query=search_query, hidden_traps=hidden_traps, all_news=all_news, spells=spells)

@app.route('/admin_update_profile/<int:target_id>', methods=['POST'])
@admin_required
def admin_update_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if target_user:
        try:
            action = request.form.get('action')
            val = request.form.get('new_val')
            if action == 'edit_name': target_user.update(set__username=val)
            elif action == 'edit_points': target_user.update(set__points=int(val or 0))
            elif action == 'edit_hp': target_user.update(set__health=int(val or 0), set__status='eliminated' if int(val or 0) <= 0 else 'active')
            elif action == 'edit_iq': target_user.update(set__intelligence_points=int(val or 0))
            elif action == 'edit_loyalty': target_user.update(set__loyalty_points=int(val or 0))
            elif action == 'edit_zone': target_user.update(set__zone=val)
            flash('تم التعديل!', 'success')
        except: 
            flash('حدث خطأ في الإدخال', 'error')
    return redirect(request.referrer)

# ==========================================
# 👤 الهوية الشخصية والملفات 
# ==========================================
@app.route('/profile')
@login_required
def profile():
    user = g.user
    my_items = StoreItem.objects(name__in=getattr(user, 'inventory', []) or [])
    return render_template('profile.html', user=user, my_items=my_items, my_seals=[i for i in my_items if getattr(i, 'item_type', '') == 'seal'])

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = g.user
    action = request.form.get('action')
    now = datetime.utcnow()
    try:
        if action == 'change_avatar':
            file = request.files.get('avatar_file')
            if file and file.filename != '':
                data = file.read()
                if len(data) > 2 * 1024 * 1024: 
                    flash('الصورة كبيرة جداً.', 'error')
                else: 
                    user.update(set__avatar=f"data:image/jpeg;base64,{base64.b64encode(compress_image(data)).decode('utf-8')}")
                    flash('تم تحديث النقش!', 'success')
        elif action == 'change_name':
            new_name = request.form.get('new_name')
            if getattr(user, 'last_name_change', None) and (now - user.last_name_change).days < 15: 
                flash('تغيير الاسم متاح مرة كل 15 يوم!', 'error')
            elif User.objects(username=new_name).first(): 
                flash('الاسم مستخدم مسبقاً!', 'error')
            else: 
                user.update(set__username=new_name, set__last_name_change=now)
                flash('تم تغيير الاسم!', 'success')
        elif action == 'change_password':
            if check_password_hash(user.password_hash, request.form.get('old_password', '')) and request.form.get('new_password') == request.form.get('confirm_password'):
                user.update(set__password_hash=generate_password_hash(request.form.get('new_password')), set__last_password_change=now)
                flash('تم تغيير الختم السري!', 'success')
    except: 
        flash('حدث خطأ!', 'error')
    return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']: 
        return redirect(url_for('home'))
    my_items = StoreItem.objects(name__in=getattr(g.user, 'inventory', []) or [])
    return render_template('hunter_profile.html', target_user=target_user, 
                           my_weapons=[i for i in my_items if getattr(i, 'item_type', '')=='weapon'], 
                           my_heals=[i for i in my_items if getattr(i, 'item_type', '')=='heal'], 
                           my_spies=[i for i in my_items if getattr(i, 'item_type', '')=='spy'], 
                           my_steals=[i for i in my_items if getattr(i, 'item_type', '')=='steal'])

# ==========================================
# 🤝 التحالفات، النقل، والأدوات
# ==========================================
@app.route('/friends', methods=['GET'])
@login_required
def friends():
    search_query = request.args.get('search')
    search_result = None
    if search_query: 
        if search_query.isdigit(): search_result = User.objects(hunter_id=int(search_query)).first()
        else: search_result = User.objects(username__icontains=search_query).first()
    
    exclude_roles = ['ghost', 'cursed_ghost', 'admin']
    exclude_ids = [g.user.hunter_id] + getattr(g.user, 'friends', []) + getattr(g.user, 'friend_requests', [])
    suggested_hunters = User.objects(status='active', role__nin=exclude_roles, hunter_id__nin=exclude_ids).order_by('-last_active')[:30]
    
    return render_template('friends.html', user=g.user, search_result=search_result, 
                           friend_requests=User.objects(hunter_id__in=getattr(g.user, 'friend_requests', [])), 
                           friends=User.objects(hunter_id__in=getattr(g.user, 'friends', [])), 
                           suggested_hunters=suggested_hunters)

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = g.user
    target = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
    if user.status != 'active': 
        flash('حسابك موقوف عن اللعب.', 'error')
        return redirect(request.referrer or url_for('home'))
        
    if not target or target.status not in ['active', 'inactive']: 
        return redirect(request.referrer or url_for('home'))
        
    if target.id == user.id: 
        flash('لا يمكنك التحالف مع نفسك!', 'error')
        return redirect(request.referrer or url_for('home'))
    
    if getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_answer=str(target.hunter_id), category='hidden').first()
        if trap and str(user.id) not in getattr(trap, 'winners_list', []) and getattr(trap, 'current_winners', 0) < getattr(trap, 'max_winners', 1):
            if trap.puzzle_type.startswith('ghost_'): 
                execute_trap_effect(user, trap)
                trap.update(inc__current_winners=1, push__winners_list=str(user.id))
        else: 
            flash('اختفى الشبح أو نفدت المكافآت.', 'info')
    elif target.hunter_id not in getattr(user, 'friends', []) and user.hunter_id not in getattr(target, 'friend_requests', []): 
        target.update(push__friend_requests=user.hunter_id)
        flash('أُرسل طلب التحالف.', 'success')
        
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = g.user
    target = User.objects(hunter_id=target_id).first()
    if target:
        if user.hunter_id in getattr(target, 'friend_requests', []): 
            target.update(pull__friend_requests=user.hunter_id)
        elif target.hunter_id in getattr(user, 'friends', []): 
            user.update(pull__friends=target.hunter_id, dec__loyalty_points=20)
            target.update(pull__friends=user.hunter_id)
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_request', methods=['POST'])
@login_required
def cancel_request():
    user = g.user
    target = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
    if target and user.hunter_id in getattr(target, 'friend_requests', []): 
        target.update(pull__friend_requests=user.hunter_id)
        flash('تم سحب الطلب.', 'info')
    return redirect(request.referrer or url_for('home'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = g.user
    friend = User.objects(hunter_id=friend_id).first()
    if user.status != 'active': 
        flash('حسابك موقوف عن اللعب.', 'error')
        return redirect(request.referrer or url_for('home'))
        
    if friend and friend.status in ['active', 'inactive'] and friend_id in getattr(user, 'friend_requests', []): 
        user.update(pull__friend_requests=friend_id, push__friends=friend_id)
        friend.update(push__friends=user.hunter_id)
        check_achievements(user)
        
    return redirect(request.referrer or url_for('home'))

@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    sender = g.user
    receiver = User.objects(hunter_id=target_id).first()
    if sender.status != 'active': 
        flash('لا يمكنك التنفيذ.', 'error')
        return redirect(request.referrer or url_for('home'))
        
    if not receiver or receiver.status != 'active' or receiver.hunter_id not in getattr(sender, 'friends', []): 
        return redirect(request.referrer or url_for('home'))
        
    transfer_type = request.form.get('transfer_type')
    if transfer_type == 'points':
        try:
            amt = int(request.form.get('amount') or 0)
            if 0 < amt <= sender.points: 
                sender.update(dec__points=amt, inc__loyalty_points=2)
                receiver.update(inc__points=amt)
                flash('تم إرسال الدنانير!', 'success')
        except: pass
    elif transfer_type == 'item':
        itm = request.form.get('item_name')
        if itm in getattr(sender, 'inventory', []): 
            sender.update(pull__inventory=itm, inc__loyalty_points=5)
            receiver.update(push__inventory=itm)
            flash('تم إرسال الأداة!', 'success')
            
    return redirect(request.referrer or url_for('home'))

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    attacker = g.user
    target = User.objects(hunter_id=target_id).first()
    settings = g.settings
    
    if attacker.status != 'active': 
        flash('حسابك معطل عن اللعب.', 'error')
        return redirect(request.referrer or url_for('home'))
        
    item_name = request.form.get('item_name')
    item = StoreItem.objects(name=item_name).first()
    
    if not item or item_name not in getattr(attacker, 'inventory', []) or not target or target.status != 'active': 
        return redirect(request.referrer or url_for('home'))
        
    now = datetime.utcnow()
    item_type = getattr(item, 'item_type', '')
    
    if item_type in ['weapon', 'steal', 'spy']:
        cooldown_mins = getattr(settings, 'attack_cooldown_minutes', 0)
        if cooldown_mins > 0 and attacker.last_action_time and (now - attacker.last_action_time).total_seconds() < (cooldown_mins * 60):
            flash(f'الرجاء الانتظار {int((cooldown_mins*60) - (now - attacker.last_action_time).total_seconds())} ثانية.', 'error')
            return redirect(request.referrer or url_for('home'))

    if getattr(settings, 'final_battle_mode', False) and target.hunter_id != 1000 and item_type in ['weapon', 'steal', 'spy']: 
        flash('الإمبراطور هو عدوك الوحيد الآن!', 'error')
        return redirect(request.referrer or url_for('home'))
    
    if item_type == 'weapon':
        if getattr(target, 'role', '') == 'admin' and not getattr(settings, 'final_battle_mode', False): 
            flash('الإمبراطور محصن!', 'error')
        elif getattr(target, 'has_shield', False): 
            target.update(set__has_shield=False)
            flash('انكسر درع الهدف وضاعت ضربتك!', 'error')
        else:
            new_hp = target.health - getattr(item, 'effect_amount', 0)
            if new_hp <= 0:
                target.update(set__health=0, set__status='eliminated', set__freeze_reason='سقط في المعركة')
                GlobalSettings.objects(setting_name='main_config').update_one(inc__dead_count=1)
                if getattr(target, 'role', '') == 'admin': 
                    GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=False, set__war_mode=False)
            else: 
                target.update(set__health=new_hp)
            flash('تمت الضربة بنجاح!', 'success')
        attacker.update(pull__inventory=item_name, set__last_action_time=now)
        
    elif item_type == 'heal':
        if target.id == attacker.id or target.hunter_id in getattr(attacker, 'friends', []):
            heal_amt = getattr(item, 'effect_amount', 0)
            new_hp = target.health + heal_amt if getattr(target, 'role', '') == 'admin' else min(100, target.health + heal_amt)
            target.update(set__health=new_hp)
            if target.id != attacker.id: 
                attacker.update(inc__loyalty_points=5)
            attacker.update(pull__inventory=item_name, set__last_action_time=now)
            flash('تم العلاج!', 'success')
            
    elif item_type == 'spy':
        if getattr(target, 'has_shield', False): 
            attacker.update(pull__inventory=item_name, set__last_action_time=now)
            flash('الهدف محصن ضد التجسس!', 'error')
        else: 
            attacker.update(set__tajis_eye_until=now + timedelta(hours=1), pull__inventory=item_name, set__last_action_time=now)
            flash('تجسست بنجاح!', 'success')
            
    elif item_type == 'steal':
        stolen_item = request.form.get('target_item')
        if stolen_item in getattr(target, 'inventory', []):
            if getattr(target, 'has_shield', False): 
                attacker.update(pull__inventory=item_name, set__last_action_time=now)
                flash('الهدف محمي!', 'error')
            else: 
                target.update(pull__inventory=stolen_item)
                attacker.update(push__inventory=stolen_item, pull__inventory=item_name, inc__intelligence_points=5, set__last_action_time=now)
                flash(f'تمت سرقة {stolen_item} بنجاح!', 'success')
                
    elif item_type == 'seal':
        if target.id == attacker.id:
            collected = getattr(attacker, 'collected_seals', [])
            if item_name not in collected:
                attacker.update(push__collected_seals=item_name, pull__inventory=item_name)
                attacker.reload()
                if len(attacker.collected_seals) >= 4:
                    if settings: 
                        GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False, set__final_battle_mode=False)
                    User.objects(status='active').update(set__health=100)
                    flash('🔥 جمعت الأختام الأربعة الفريدة! لقد فزت!', 'success')
                else: 
                    flash('فُعل الختم!', 'success')
            else: 
                attacker.update(pull__inventory=item_name)
                flash('فعلت هذا النوع مسبقاً! تبخر الختم بلا فائدة.', 'error')
                
    return redirect(request.referrer or url_for('home'))

# ==========================================
# 📜 المراسيم، النقوش، والتصريحات
# ==========================================
@app.route('/news')
@login_required
def news(): 
    g.user.update(set__last_seen_news=datetime.utcnow())
    return render_template('news.html', news_list=News.objects(category='news', status='approved').order_by('-created_at'))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    user = g.user
    settings = g.settings
    if request.method == 'POST':
        if user.status != 'active': 
            flash('حسابك موقوف عن اللعب.', 'error')
            return redirect(url_for('puzzles'))
            
        guess = request.form.get('guess')
        puzzle = News.objects(id=request.form.get('puzzle_id')).first()
        
        if puzzle and str(guess) == str(getattr(puzzle, 'puzzle_answer', '')) and str(user.id) not in getattr(puzzle, 'winners_list', []):
            if getattr(puzzle, 'current_winners', 0) < getattr(puzzle, 'max_winners', 1):
                user.update(inc__points=getattr(puzzle, 'reward_points', 0), inc__stats_puzzles_solved=1, inc__intelligence_points=10)
                puzzle.update(push__winners_list=str(user.id), inc__current_winners=1)
                flash('إجابة صحيحة!', 'success')
                
                if settings and getattr(settings, 'floor1_mode_active', False):
                    user.update(inc__gems_collected=1)
                    Notification(target_hunter_id=user.hunter_id, message='💎 حصلت على حجر كريم من اللغز!', notif_type='success').save()
                    total_gems = sum([u.gems_collected for u in User.objects(group_id=user.group_id)])
                    if total_gems >= getattr(settings, 'floor1_gems_target', 10):
                        User.objects(group_id=user.group_id, is_cursed=True).update(set__status='eliminated', set__freeze_reason='احترقت اللعنة')
                        GroupMessage(group_id=user.group_id, sender_name="النظام", message="✨ اكتمل النور وفُتحت البوابة!", is_system_msg=True).save()
                        User.objects(group_id=user.group_id, status='active').update(set__zone='الطابق 2')
        else: 
            flash('إجابة خاطئة أو أنك حللته مسبقاً!', 'error')
        return redirect(url_for('puzzles'))
        
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = g.user
    if user.status != 'active': return redirect(url_for('home'))
    try: 
        puzzle = News.objects(id=puzzle_id).first()
    except: return redirect(url_for('home'))
    
    if puzzle and str(user.id) not in getattr(puzzle, 'winners_list', []) and getattr(puzzle, 'current_winners', 0) < getattr(puzzle, 'max_winners', 1):
        if puzzle.puzzle_type.startswith('link_'): 
            execute_trap_effect(user, puzzle)
            puzzle.update(inc__current_winners=1, push__winners_list=str(user.id))
    return redirect(request.referrer or url_for('home'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = g.user
    if request.method == 'POST':
        if user.status != 'active': 
            flash('حسابك موقوف عن النشر.', 'error')
            return redirect(url_for('declarations'))
        img = ''
        file = request.files.get('image_file')
        if file: 
            img = f"data:image/jpeg;base64,{base64.b64encode(compress_image(file.read())).decode('utf-8')}"
        News(
            title=f"تصريح من {user.username}", content=request.form.get('content', '').strip(), 
            image_data=img, category='declaration', author=user.username, 
            status='approved' if user.role == 'admin' else 'pending'
        ).save()
        return redirect(url_for('declarations'))
        
    user.update(set__last_seen_decs=datetime.utcnow())
    approved = News.objects(category='declaration', status='approved').order_by('-created_at')
    pending = News.objects(category='declaration', status='pending') if user.role == 'admin' else []
    my_pending = News.objects(category='declaration', status='pending', author=user.username).order_by('-created_at')
    avatars = {u.username: u.hunter_id for u in User.objects(username__in=set([d.author for d in News.objects(category='declaration')]))}
    return render_template('declarations.html', approved_decs=approved, pending_decs=pending, my_pending_decs=my_pending, current_user=user, avatars=avatars)

@app.route('/react_declaration/<dec_id>/<react_type>', methods=['POST'])
@login_required
def react_declaration(dec_id, react_type):
    try:
        from bson.objectid import ObjectId
        coll = News._get_collection()
        dec_data = coll.find_one({'_id': ObjectId(dec_id)})
        if dec_data and react_type in ['like', 'laugh']:
            uid = str(g.user.id)
            likes = dec_data.get('likes', [])
            laughs = dec_data.get('laughs', [])
            if react_type == 'like':
                if uid in likes: likes.remove(uid)
                else: 
                    likes.append(uid)
                    if uid in laughs: laughs.remove(uid)
            elif react_type == 'laugh':
                if uid in laughs: laughs.remove(uid)
                else: 
                    laughs.append(uid)
                    if uid in likes: likes.remove(uid)
            coll.update_one({'_id': ObjectId(dec_id)}, {'$set': {'likes': likes, 'laughs': laughs}})
    except: pass
    return redirect(url_for('declarations'))

@app.route('/delete_declaration/<dec_id>', methods=['POST'])
@login_required
def delete_declaration(dec_id):
    user = g.user
    dec = News.objects(id=dec_id).first()
    if dec and (dec.author == user.username or user.role == 'admin'): 
        dec.delete()
    return redirect(url_for('declarations'))

# ==========================================
# 🛒 السوق والمقبرة
# ==========================================
@app.route('/store')
@login_required
def store(): 
    g.user.update(set__last_seen_store=datetime.utcnow())
    return render_template('store.html', items=StoreItem.objects())

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    user = g.user
    if user.status != 'active': 
        flash('حسابك موقوف عن الشراء.', 'error')
        return redirect(url_for('store'))
    try: 
        item = StoreItem.objects(id=item_id).first()
    except: return redirect(url_for('store'))
    
    if user and item and user.points >= item.price:
        if getattr(item, 'is_mirage', False): 
            user.update(dec__points=item.price, dec__intelligence_points=10)
            flash(getattr(item, 'mirage_message', 'فخ سراب! خسرت الدنانير و 10 نقاط ذكاء.'), 'error')
        else:
            user.update(dec__points=item.price)
            if getattr(item, 'is_luck', False): 
                outcome = random.randint(getattr(item, 'luck_min', 0), getattr(item, 'luck_max', 0))
                user.update(inc__points=outcome)
                flash(f'صندوق حظ: النتيجة {outcome} دنانير!', 'success' if outcome >= 0 else 'error')
            else: 
                user.update(push__inventory=item.name, inc__stats_items_bought=1)
                flash(f'تم شراء [{item.name}] بنجاح!', 'success')
    else: 
        flash('دنانيرك لا تكفي!', 'error')
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): 
    return render_template('graveyard.html', users=User.objects(status='eliminated').order_by('-id'))

@app.route('/delete_store_item/<item_id>', methods=['POST'])
@admin_required
def delete_store_item(item_id):
    try: 
        StoreItem.objects(id=item_id).delete()
        flash('تم الحذف من السوق!', 'success')
    except: pass
    return redirect(url_for('store'))

@app.route('/delete_puzzle/<puzzle_id>', methods=['POST'])
@admin_required
def delete_puzzle(puzzle_id):
    try: 
        News.objects(id=puzzle_id).delete()
        flash('تم الحذف!', 'success')
    except: pass
    return redirect(request.referrer or url_for('puzzles'))

# ==========================================
# 🔮 مذبح الطلاسم والبونغليف
# ==========================================
@app.route('/altar', methods=['GET', 'POST'])
@login_required
def altar():
    user = g.user
    if request.method == 'POST':
        if user.status != 'active': 
            flash('حسابك موقوف عن اللعب.', 'error')
            return redirect(url_for('altar'))
            
        spell_word = request.form.get('spell_word', '').strip()
        spell = SpellConfig.objects(spell_word=spell_word).first()
        settings = g.settings
        
        if not spell: 
            flash('خطأ! كلمة لا معنى لها... المذبح صامت.', 'error')
            return redirect(url_for('altar'))
            
        now = datetime.utcnow()
        if getattr(spell, 'expires_at', None) and now > spell.expires_at: 
            flash('خطأ! تلاشت طاقة هذه التعويذة.', 'error')
            return redirect(url_for('altar'))
            
        used_list = getattr(spell, 'used_by', [])
        max_u = getattr(spell, 'max_uses', 0)
        
        if str(user.id) in used_list: 
            flash('خطأ! استخدمت التعويذة مسبقاً.', 'error')
            return redirect(url_for('altar'))
        if max_u > 0 and len(used_list) >= max_u: 
            flash('خطأ! استنفدت طاقة التعويذة.', 'error')
            return redirect(url_for('altar'))
            
        try:
            stype = getattr(spell, 'spell_type', '')
            val = getattr(spell, 'effect_value', 0)
            is_perc = getattr(spell, 'is_percentage', False)
            
            if stype == 'hp_loss':
                loss = int(user.health * (val / 100.0)) if is_perc else val
                new_hp = user.health - loss
                if new_hp <= 0: 
                    user.update(set__health=0, set__status='eliminated', set__freeze_reason='أحرقته تعويذة')
                else: 
                    user.update(set__health=new_hp)
                flash('ضريبة الدم! نقص من صحتك.', 'error')
                
            elif stype == 'hp_gain': 
                gain = int(user.health * (val / 100.0)) if is_perc else val
                user.update(set__health=min(100, user.health + gain))
                flash('نجاح! طاقة غريبة تشفيك.', 'success')
                
            elif stype == 'points_loss': 
                loss = int(user.points * (val / 100.0)) if is_perc else val
                user.update(set__points=max(0, user.points - loss))
                flash('خطأ! سحب منك المذبح دنانير.', 'error')
                
            elif stype == 'points_gain': 
                user.update(inc__points=val)
                flash('ثراء! دنانير تتدفق إليك!', 'success')
                
            elif stype == 'item_reward': 
                if getattr(spell, 'item_name', ''): 
                    user.update(push__inventory=getattr(spell, 'item_name', ''))
                    flash('نجاح! استدعيت أداة من العدم.', 'success')
                    
            elif stype == 'unlock_lore': 
                user.update(set__unlocked_lore_room=True)
                flash('نجاح! اهتزت الأرض.. ظهر بونغليف سيفار!', 'success')
                
            elif stype == 'unlock_top': 
                user.update(set__unlocked_top_room=True)
                flash('نجاح! اهتزت الأرض.. فُتحت قاعة الأساطير!', 'success')
                
            elif stype == 'kill_emperor':
                if getattr(settings, 'final_battle_mode', False): 
                    User.objects(hunter_id=1000).update(set__health=0, set__status='eliminated')
                    GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=False, set__war_mode=False)
                    flash('نجاح! التعويذة المحرمة.. سقط الإمبراطور.', 'success')
                else: 
                    flash('خطأ! الإمبراطور محصن حالياً.', 'error')
                    return redirect(url_for('altar'))
                    
            spell.update(push__used_by=str(user.id))
        except: 
            flash("خطأ في المذبح.", "error")
            
        return redirect(url_for('altar'))
    return render_template('altar.html')

@app.route('/poneglyph')
@login_required
def poneglyph():
    if getattr(g.user, 'role', '') != 'admin' and not getattr(g.user, 'unlocked_lore_room', False): 
        return redirect(url_for('home'))
    return render_template('poneglyph.html', poneglyph_text=getattr(g.settings, 'poneglyph_text', ''))

@app.route('/top_room')
@login_required
def top_room():
    if getattr(g.user, 'role', '') != 'admin' and not getattr(g.user, 'unlocked_top_room', False): 
        return redirect(url_for('home'))
    return render_template('top_room.html', 
                           top_iq=User.objects(hunter_id__ne=1000, status__in=['active', 'inactive']).order_by('-intelligence_points')[:10], 
                           top_loyal=User.objects(hunter_id__ne=1000, status__in=['active', 'inactive']).order_by('-loyalty_points')[:10], 
                           top_hp=User.objects(hunter_id__ne=1000, status__in=['active', 'inactive']).order_by('-health')[:10])

@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    user = g.user
    settings = g.settings
    if user.status != 'active': 
        return redirect(url_for('home'))
    if getattr(settings, 'gates_mode_active', False) and getattr(user, 'chosen_gate', 0) == 0: 
        user.update(set__chosen_gate=int(request.form.get('gate_num') or 0), set__gate_status='waiting')
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    if g.user.gate_status == 'testing': 
        g.user.update(set__gate_test_answer=request.form.get('test_answer', ''))
    return redirect(url_for('home'))

# ==========================================
# 🛑 الأخطاء والتشغيل
# ==========================================
@app.errorhandler(Exception)
def handle_exception(e):
    if "404" in str(e): 
        return f"<div style='direction:rtl; text-align:center; padding:50px; background:#000; color:#fff;'><h2>الصفحة غير موجودة!</h2><a href='/' style='color:#d4af37;'>العودة</a></div>", 404
    return f"<div style='direction:ltr; background:#0a0a0a; color:#ff5555; padding:20px; text-align:left;'><h2>🚨 خطأ برمجي</h2><pre>{traceback.format_exc()}</pre></div>", 200

if __name__ == '__main__': 
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
