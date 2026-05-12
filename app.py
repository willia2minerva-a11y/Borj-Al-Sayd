from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, g, jsonify
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

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'SEPHAR_MAZE_IMMORTAL_SECRET_KEY_999')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
db.init_app(app)

_settings_cache = {'data': None, 'timestamp': 0}
_SETTINGS_CACHE_TTL = 10  
_user_cache = {} # ذاكرة التخزين المؤقت لتسريع الموقع

# 🗺️ خريطة المتاهة - أسماء مناسبة للمتاهة
F1_MAP = {
    'قاعة العروش': ['دهليز الأجداد', 'مخزن الآثار', 'مكتبة الأسرار', 'معبد الطلاسم'],
    'دهليز الأجداد': ['قاعة العروش', 'مرصد الأبراج', 'مكتبة الأسرار'],
    'مخزن الآثار': ['قاعة العروش', 'غرفة البصيرة'],
    'مكتبة الأسرار': ['قاعة العروش', 'دهليز الأجداد'],
    'معبد الطلاسم': ['قاعة العروش', 'بوابة النور'],
    'غرفة البصيرة': ['مخزن الآثار'],
    'مرصد الأبراج': ['دهليز الأجداد'],
    'بوابة النور': ['معبد الطلاسم']
}

# 📜 المهام المتاحة للطابق الأول (Among Us)
TASKS_BY_ROOM = {
    'قاعة العروش': [
        {"name": "إصلاح العرش المتصدع", "description": "أصلح العرش الملكي المتضرر"},
        {"name": "تنظيف القاعة", "description": "أزل الغبار والأوساخ من القاعة"}
    ],
    'مكتبة الأسرار': [
        {"name": "فك تشفير المخطوطة", "description": "قم بفك رموز المخطوطة القديمة"},
        {"name": "ترتيب الرفوف", "description": "رتب الكتب في أماكنها الصحيحة"},
        {"name": "إشعال البخور", "description": "أشعل بخور المعرفة"}
    ],
    'معبد الطلاسم': [
        {"name": "رسم دائرة التعاويذ", "description": "ارسم دائرة الحماية السحرية"},
        {"name": "ترتيب التماثيل", "description": "أعد ترتيب التماثيل الطقسية"}
    ],
    'مخزن الآثار': [
        {"name": "جرد القطع الأثرية", "description": "قم بإحصاء القطع الأثرية الثمينة"},
        {"name": "تنظيف الصناديق", "description": "نظف صناديق الآثار القديمة"}
    ],
    'دهليز الأجداد': [
        {"name": "إضاءة المشاعل", "description": "أشعل المشاعل في الدهليز المظلم"},
        {"name": "إصلاح الجدار", "description": "صلح الشقوق في جدار الدهليز"}
    ],
    'مرصد الأبراج': [
        {"name": "توجيه العدسات", "description": "اضبط عدسات المرصد بدقة"},
        {"name": "تسجيل الأبراج", "description": "دوّن مواقع الأبراج في السماء"}
    ],
    'غرفة البصيرة': [
        {"name": "تأمل البلورة", "description": "تأمل في بلورة البصيرة"},
        {"name": "قراءة الطالع", "description": "اقرأ طالع المستقبل"}
    ]
}

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

def assign_tasks_to_player(user):
    all_tasks = []
    for room, tasks in TASKS_BY_ROOM.items():
        for task in tasks:
            all_tasks.append({"room": room, "name": task["name"], "description": task["description"], "completed": False})
    random_tasks = random.sample(all_tasks, min(3, len(all_tasks)))
    user.update(set__f1_tasks=random_tasks)

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
    elif eff == 'quicksand':
        dur = trap.trap_duration_minutes or 5
        user.update(set__quicksand_lock_until=datetime.utcnow() + timedelta(minutes=dur))
        flash(f'وقعت في فخ الرمال! أنت مجمد لمدة {dur} دقائق.', 'error')

@app.before_request
def fast_health_check():
    if request.method == 'HEAD' or request.path == '/health': 
        return Response("OK", 200)

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
                end_time_str = meeting_data.get('end_time', meeting_data) if isinstance(meeting_data, dict) else meeting_data
                if now >= datetime.fromisoformat(end_time_str):
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
        uid = str(u.id)
        now = datetime.utcnow()
        
        # تنظيف الكاش القديم
        if random.random() < 0.05:
            keys_to_del = [k for k, v in _user_cache.items() if (now - v['time']).total_seconds() > 300]
            for k in keys_to_del: del _user_cache[k]
                
        if uid in _user_cache and (now - _user_cache[uid]['time']).total_seconds() < 45:
            notifs.update(_user_cache[uid]['counts'])
        else:
            try:
                counts = {
                    'un_news': News.objects(category='news', status='approved', created_at__gt=(u.last_seen_news or now)).count(),
                    'un_puz': News.objects(category='puzzle', status='approved', created_at__gt=(u.last_seen_puzzles or now)).count(),
                    'un_dec': News.objects(category='declaration', status='approved', created_at__gt=(u.last_seen_decs or now)).count(),
                    'un_store': StoreItem.objects(created_at__gt=(u.last_seen_store or now)).count(),
                    'unread_notifs': Notification.objects(target_hunter_id=u.hunter_id, is_read=False).count()
                }
                _user_cache[uid] = {'time': now, 'counts': counts}
                notifs.update(counts)
            except: pass
            
    notifs['default_avatar'] = "data:image/svg+xml;base64," + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#110d09"/><circle cx="50" cy="35" r="20" fill="#d4af37"/><path d="M20 90c0-20 15-35 30-35s30 15 30 35" fill="#d4af37"/></svg>').decode('utf-8')
    return notifs

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
        adjacent_rooms = F1_MAP.get(getattr(user, 'current_room', 'قاعة العروش'), [])
        Notification.objects(target_hunter_id=user.hunter_id, is_read=False).update(set__is_read=True)

        if user.current_room == 'غرفة البصيرة':
            for u in User.objects(group_id=user.group_id, status__in=['active', 'dead_body']):
                if u.current_room not in admin_dots: admin_dots[u.current_room] = []
                admin_dots[u.current_room].append({"hunter_id": u.hunter_id, "is_dead": u.status == 'dead_body'})
        elif user.current_room == 'مرصد الأبراج':
            monitored_rooms = ['دهليز الأجداد', 'قاعة العروش', 'مكتبة الأسرار']
            for u in User.objects(group_id=user.group_id, status='active', current_room__in=monitored_rooms):
                if u.current_room not in camera_feeds: camera_feeds[u.current_room] = []
                camera_feeds[u.current_room].append({"username": u.username, "hunter_id": u.hunter_id})

    f3_users = User.objects(status='active', role='hunter', survival_votes__gt=0).order_by('-survival_votes')
    player_tasks = getattr(user, 'f1_tasks', []) if user else []
    current_room_tasks = []
    if user and user.current_room:
        for task in player_tasks:
            if task.get('room') == user.current_room and not task.get('completed', False):
                current_room_tasks.append(task)
    
    return render_template('index.html', emperor=emperor, test_winner=test_winner, active_hunters=active_hunters, room_players=room_players, dead_bodies_in_room=dead_bodies_in_room, is_dark=is_dark, adjacent_rooms=adjacent_rooms, has_meeting=has_meeting, meeting_info=meeting_info, admin_dots=admin_dots, camera_feeds=camera_feeds, f3_users=f3_users, f1_map=F1_MAP, player_tasks=player_tasks, current_room_tasks=current_room_tasks)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(getattr(user, 'password_hash', ''), request.form['password']):
            session.permanent = True
            session['user_id'] = str(user.id)
            user.update(set__last_active=datetime.utcnow())
            if user.status == 'inactive': flash('حسابك قيد المراجعة.', 'info')
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

@app.route('/f1/move', methods=['POST'])
@login_required
def f1_move():
    user = g.user
    settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or user.status != 'active':
        flash('الطابق الأول غير نشط أو حسابك غير فعال!', 'error')
        return redirect(url_for('home'))
    new_room = request.form.get('room')
    if not new_room or new_room not in F1_MAP.get(user.current_room, []):
        flash('لا يمكنك الذهاب إلى هناك!', 'error')
        return redirect(url_for('home'))
    now = datetime.utcnow()
    last_move = getattr(user, 'f1_last_move', None)
    cooldown = getattr(settings, 'floor1_move_cooldown', 30)
    if last_move and (now - last_move).total_seconds() < cooldown:
        remaining = int(cooldown - (now - last_move).total_seconds())
        flash(f'⏳ يجب أن تنتظر {remaining} ثانية!', 'error')
        return redirect(url_for('home'))
    user.update(set__current_room=new_room, set__f1_last_move=now)
    flash(f'✨ انتقلت إلى {new_room} ✨', 'success')
    return redirect(url_for('home'))

@app.route('/f1/complete_task/<int:task_index>', methods=['POST'])
@login_required
def f1_complete_task(task_index):
    user = g.user
    settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or user.status != 'active': return redirect(url_for('home'))
    tasks = list(getattr(user, 'f1_tasks', []))
    if task_index >= len(tasks): return redirect(url_for('home'))
    task = tasks[task_index]
    if task.get('completed', False): return redirect(url_for('home'))
    if task.get('room') != user.current_room: return redirect(url_for('home'))
    reward = random.randint(10, 30)
    tasks[task_index]['completed'] = True
    user.update(inc__points=reward, inc__gems_collected=1, set__f1_tasks=tasks)
    flash(f'✅ أنجزت المهمة!', 'success')
    total_gems = sum([u.gems_collected for u in User.objects(group_id=user.group_id)])
    gems_target = getattr(settings, 'floor1_gems_target', 10)
    if total_gems >= gems_target:
        User.objects(group_id=user.group_id, is_cursed=True).update(set__status='eliminated', set__freeze_reason='احترقت اللعنة')
        GroupMessage(group_id=user.group_id, sender_name="النظام", message=f"✨ فازت المجموعة وفُتحت البوابة! ✨", is_system_msg=True).save()
        User.objects(group_id=user.group_id, status='active').update(set__zone='الطابق 2')
    return redirect(url_for('home'))

@app.route('/f1/emergency_meeting', methods=['POST'])
@login_required
def f1_emergency_meeting():
    user = g.user
    settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or user.status != 'active': return redirect(url_for('home'))
    gid_str = str(user.group_id)
    meetings = getattr(settings, 'f1_active_meetings', {})
    if gid_str in meetings: return redirect(url_for('home'))
    if getattr(user, 'emergency_used', False): return redirect(url_for('home'))
    end_time = datetime.utcnow() + timedelta(minutes=5)
    meetings[gid_str] = {'end_time': end_time.isoformat(), 'called_by': user.username, 'type': 'emergency', 'caller_hunter_id': user.hunter_id}
    GlobalSettings.objects(setting_name='main_config').update_one(set__f1_active_meetings=meetings)
    user.update(set__emergency_used=True)
    GroupMessage(group_id=user.group_id, sender_name="النظام", message=f"🚨 {user.username} استدعى اجتماعاً طارئاً!", is_system_msg=True).save()
    flash('🚨 تم عقد الاجتماع الطارئ!', 'success')
    return redirect(url_for('home'))

@app.route('/f1/report_body', methods=['POST'])
@login_required
def f1_report_body():
    user = g.user
    settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or user.status != 'active': return redirect(url_for('home'))
    gid_str = str(user.group_id)
    meetings = getattr(settings, 'f1_active_meetings', {})
    if gid_str in meetings: return redirect(url_for('home'))
    body_hunter_id = int(request.form.get('body_id', 0))
    body = User.objects(hunter_id=body_hunter_id, group_id=user.group_id, status='dead_body').first()
    if not body: return redirect(url_for('home'))
    end_time = datetime.utcnow() + timedelta(minutes=5)
    meetings[gid_str] = {'end_time': end_time.isoformat(), 'called_by': user.username, 'type': 'report', 'body': body.username, 'body_hunter_id': body.hunter_id, 'caller_hunter_id': user.hunter_id}
    GlobalSettings.objects(setting_name='main_config').update_one(set__f1_active_meetings=meetings)
    GroupMessage(group_id=user.group_id, sender_name="النظام", message=f"⚠️ {user.username} عثر على جثة {body.username}!", is_system_msg=True).save()
    flash(f'⚠️ أبلغت عن جثة {body.username}!', 'success')
    return redirect(url_for('home'))

@app.route('/f1/kill', methods=['POST'])
@login_required
def f1_kill():
    attacker = g.user
    settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or attacker.status != 'active' or not getattr(attacker, 'is_cursed', False): return redirect(url_for('home'))
    target_id = int(request.form.get('target_id', 0))
    target = User.objects(hunter_id=target_id, group_id=attacker.group_id, status='active', current_room=attacker.current_room).first()
    if not target: return redirect(url_for('home'))
    now = datetime.utcnow()
    last_kill = getattr(attacker, 'f1_last_kill', None)
    kill_cooldown = getattr(settings, 'floor1_kill_cooldown', 60)
    if last_kill and (now - last_kill).total_seconds() < kill_cooldown: return redirect(url_for('home'))
    target.update(set__status='dead_body', set__freeze_reason=f'قُتل على يد {attacker.username}')
    attacker.update(set__f1_last_kill=now, inc__stats_ghosts_caught=1)
    for p in User.objects(group_id=attacker.group_id, current_room=attacker.current_room, status='active'):
        if p.id != attacker.id: Notification(target_hunter_id=p.hunter_id, message=f'💀 تم اغتيال {target.username} أمامك!', notif_type='danger').save()
    GroupMessage(group_id=attacker.group_id, sender_name="النظام", message=f"💀 {target.username} قُتل في {attacker.current_room}! 💀", is_system_msg=True).save()
    flash(f'🔪 قتلت {target.username} بنجاح!', 'success')
    return redirect(url_for('home'))

@app.route('/f1/vent', methods=['POST'])
@login_required
def f1_vent():
    user = g.user
    settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or user.status != 'active' or not getattr(user, 'is_cursed', False): return redirect(url_for('home'))
    if getattr(user, 'used_vent', False): return redirect(url_for('home'))
    vent_rooms = ['دهليز الأجداد', 'مخزن الآثار']
    if user.current_room not in vent_rooms: return redirect(url_for('home'))
    possible_rooms = ['قاعة العروش', 'مكتبة الأسرار', 'معبد الطلاسم']
    new_room = random.choice(possible_rooms)
    user.update(set__current_room=new_room, set__used_vent=True)
    flash(f'🕳️ ظهرت فجأة في {new_room}!', 'success')
    return redirect(url_for('home'))

@app.route('/f1/vote', methods=['POST'])
@login_required
def f1_vote():
    user = g.user
    settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or user.status != 'active': return redirect(url_for('home'))
    gid_str = str(user.group_id)
    meetings = getattr(settings, 'f1_active_meetings', {})
    if gid_str not in meetings or getattr(user, 'f1_has_voted', False): return redirect(url_for('home'))
    target_name = request.form.get('target')
    target = User.objects(username=target_name, group_id=user.group_id, status__in=['active', 'dead_body']).first()
    if not target or target.id == user.id: return redirect(url_for('home'))
    user.update(set__f1_has_voted=True)
    target.update(inc__f1_votes_received=1)
    GroupMessage(group_id=user.group_id, sender_name="النظام", message=f"🗳️ {user.username} صوت ضد {target.username}", is_system_msg=True).save()
    flash('🗳️ تم تسجيل صوتك بنجاح!', 'success')
    return redirect(url_for('home'))

@app.route('/f1/meeting_room')
@login_required
def f1_meeting_room():
    user = g.user
    settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False): return redirect(url_for('home'))
    gid_str = str(user.group_id)
    meetings = getattr(settings, 'f1_active_meetings', {})
    if gid_str not in meetings: return redirect(url_for('home'))
    meeting_info = meetings[gid_str]
    members = User.objects(group_id=user.group_id, status__in=['active', 'dead_body'])
    has_voted = getattr(user, 'f1_has_voted', False)
    return render_template('f1_meeting.html', meeting_info=meeting_info, members=members, has_voted=has_voted)

@app.route('/f3/cast_vote', methods=['POST'])
@login_required
def f3_cast_vote():
    user = g.user
    settings = g.settings
    if not getattr(settings, 'floor3_mode_active', False) or user.status != 'active' or user.role != 'hunter' or getattr(user, 'has_voted', False): return redirect(url_for('home'))
    target_id = int(request.form.get('target_id') or 0)
    target = User.objects(hunter_id=target_id, status='active', role='hunter').first()
    if not target or target.id == user.id or target.hunter_id == 1000: return redirect(url_for('home'))
    user.update(set__has_voted=True, set__f3_vote_target=target.hunter_id)
    target.update(inc__survival_votes=1.0)
    flash(f'صوتك سُجل لصالح {target.username}!', 'success')
    return redirect(url_for('home'))

@app.route('/f3/results')
@login_required
def f3_results():
    if not getattr(g.settings, 'floor3_results_active', False): return redirect(url_for('home'))
    winners = User.objects(status='active', role='hunter', zone='المعركة الأخيرة').order_by('-survival_votes')
    return render_template('f3_results.html', winners=winners)

@app.route('/submit_floor3_votes', methods=['POST'])
@login_required
def submit_floor3_votes():
    user = g.user
    settings = g.settings
    if not getattr(settings, 'floor3_mode_active', False) or user.status != 'active' or getattr(user, 'has_voted', False): return redirect(url_for('home'))
    votes = {}
    total = 0
    targets = set()
    for i in range(1, 6):
        target_id = request.form.get(f'target_{i}')
        amount = int(request.form.get(f'amount_{i}', 0))
        if not target_id or amount < 1 or target_id in targets: return redirect(url_for('home'))
        target = User.objects(hunter_id=int(target_id)).first()
        if not target: return redirect(url_for('home'))
        targets.add(target_id)
        total += amount
        votes[target_id] = {'name': target.username, 'amount': amount}
    if total != 100: return redirect(url_for('home'))
    user.update(set__has_voted=True, set__f3_votes_cast=votes)
    for target_id, vote_data in votes.items(): User.objects(hunter_id=int(target_id)).update(inc__survival_votes=vote_data['amount'])
    flash('تم تسجيل أصواتك!', 'success')
    return redirect(url_for('home'))
@app.route('/f1/meeting_room')
@login_required
def f1_meeting_room():
    user = g.user
    settings = g.settings
    
    if not getattr(settings, 'floor1_mode_active', False):
        return redirect(url_for('home'))
        
    gid_str = str(user.group_id)
    meetings = getattr(settings, 'f1_active_meetings', {})
    
    if gid_str not in meetings:
        flash('لا يوجد اجتماع نشط في مجموعتك!', 'error')
        return redirect(url_for('home'))
        
    meeting_info = meetings[gid_str]
    members = User.objects(group_id=user.group_id, status__in=['active', 'dead_body'])
    has_voted = getattr(user, 'f1_has_voted', False)
    
    return render_template('f1_meeting.html', meeting_info=meeting_info, members=members, has_voted=has_voted)

# ==========================================
# 🎮 أوامر الطابق الثالث (المحكمة)
# ==========================================
@app.route('/f3/cast_vote', methods=['POST'])
@login_required
def f3_cast_vote():
    user = g.user
    settings = g.settings
    
    if not getattr(settings, 'floor3_mode_active', False) or user.status != 'active' or user.role != 'hunter':
        flash('لا يمكنك التصويت حالياً!', 'error')
        return redirect(url_for('home'))
        
    if getattr(user, 'has_voted', False):
        flash('لقد صوت مسبقاً!', 'error')
        return redirect(url_for('home'))
        
    target_id = int(request.form.get('target_id') or 0)
    target = User.objects(hunter_id=target_id, status='active', role='hunter').first()
    
    if not target or target.id == user.id:
        flash('هدف غير صالح!', 'error')
        return redirect(url_for('home'))
        
    if target.hunter_id == 1000:
        flash('لا يمكن التصويت ضد الإمبراطور!', 'error')
        return redirect(url_for('home'))
        
    user.update(
        set__has_voted=True,
        set__f3_vote_target=target.hunter_id
    )
    
    target.update(inc__survival_votes=1.0)
    
    flash(f'صوتك سُجل لصالح الصياد رقم {target.hunter_id}!', 'success')
    return redirect(url_for('home'))

@app.route('/f3/results')
@login_required
def f3_results():
    if not getattr(g.settings, 'floor3_results_active', False):
        return redirect(url_for('home'))
        
    winners = User.objects(status='active', role='hunter', zone='المعركة الأخيرة').order_by('-survival_votes')
    return render_template('f3_results.html', winners=winners)

@app.route('/submit_floor3_votes', methods=['POST'])
@login_required
def submit_floor3_votes():
    user = g.user
    settings = g.settings
    
    if not getattr(settings, 'floor3_mode_active', False) or user.status != 'active':
        flash('لا يمكنك التصويت الآن!', 'error')
        return redirect(url_for('home'))
        
    if getattr(user, 'has_voted', False):
        flash('لقد صوت مسبقاً!', 'error')
        return redirect(url_for('home'))
        
    votes = {}
    total = 0
    targets = set()
    
    for i in range(1, 6):
        target_id = request.form.get(f'target_{i}')
        amount = int(request.form.get(f'amount_{i}', 0))
        
        if not target_id or amount < 1:
            flash('يرجى إدخال قيم صحيحة لجميع الخيارات!', 'error')
            return redirect(url_for('home'))
            
        if target_id in targets:
            flash('لا يمكنك التصويت لنفس الشخص مرتين!', 'error')
            return redirect(url_for('home'))
            
        target = User.objects(hunter_id=int(target_id)).first()
        if not target:
            flash('أحد الأهداف غير موجود!', 'error')
            return redirect(url_for('home'))
            
        targets.add(target_id)
        total += amount
        votes[target_id] = {'name': target.username, 'amount': amount}
        
    if total != 100:
        flash(f'مجموع الأصوات يجب أن يكون 100 بالضبط! مجموعك الحالي: {total}', 'error')
        return redirect(url_for('home'))
        
    user.update(
        set__has_voted=True,
        set__f3_votes_cast=votes
    )
    
    # إضافة الأصوات للمستهدفين
    for target_id, vote_data in votes.items():
        User.objects(hunter_id=int(target_id)).update(inc__survival_votes=vote_data['amount'])
        
    flash('تم تسجيل أصواتك بنجاح!', 'success')
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

@app.route('/f1/meeting_room')
@login_required
def f1_meeting_room():
    user = g.user
    settings = g.settings
    
    if not getattr(settings, 'floor1_mode_active', False):
        return redirect(url_for('home'))
        
    gid_str = str(user.group_id)
    meetings = getattr(settings, 'f1_active_meetings', {})
    
    if gid_str not in meetings:
        flash('لا يوجد اجتماع نشط في مجموعتك!', 'error')
        return redirect(url_for('home'))
        
    meeting_info = meetings[gid_str]
    members = User.objects(group_id=user.group_id, status__in=['active', 'dead_body'])
    has_voted = getattr(user, 'f1_has_voted', False)
    
    return render_template('f1_meeting.html', meeting_info=meeting_info, members=members, has_voted=has_voted)

# ==========================================
# 🎮 أوامر الطابق الثالث (المحكمة)
# ==========================================
@app.route('/f3/cast_vote', methods=['POST'])
@login_required
def f3_cast_vote():
    user = g.user
    settings = g.settings
    
    if not getattr(settings, 'floor3_mode_active', False) or user.status != 'active' or user.role != 'hunter':
        flash('لا يمكنك التصويت حالياً!', 'error')
        return redirect(url_for('home'))
        
    if getattr(user, 'has_voted', False):
        flash('لقد صوت مسبقاً!', 'error')
        return redirect(url_for('home'))
        
    target_id = int(request.form.get('target_id') or 0)
    target = User.objects(hunter_id=target_id, status='active', role='hunter').first()
    
    if not target or target.id == user.id:
        flash('هدف غير صالح!', 'error')
        return redirect(url_for('home'))
        
    if target.hunter_id == 1000:
        flash('لا يمكن التصويت ضد الإمبراطور!', 'error')
        return redirect(url_for('home'))
        
    user.update(
        set__has_voted=True,
        set__f3_vote_target=target.hunter_id
    )
    
    target.update(inc__survival_votes=1.0)
    
    flash(f'صوتك سُجل لصالح الصياد رقم {target.hunter_id}!', 'success')
    return redirect(url_for('home'))

@app.route('/f3/results')
@login_required
def f3_results():
    if not getattr(g.settings, 'floor3_results_active', False):
        return redirect(url_for('home'))
        
    winners = User.objects(status='active', role='hunter', zone='المعركة الأخيرة').order_by('-survival_votes')
    return render_template('f3_results.html', winners=winners)

@app.route('/submit_floor3_votes', methods=['POST'])
@login_required
def submit_floor3_votes():
    user = g.user
    settings = g.settings
    
    if not getattr(settings, 'floor3_mode_active', False) or user.status != 'active':
        flash('لا يمكنك التصويت الآن!', 'error')
        return redirect(url_for('home'))
        
    if getattr(user, 'has_voted', False):
        flash('لقد صوت مسبقاً!', 'error')
        return redirect(url_for('home'))
        
    votes = {}
    total = 0
    targets = set()
    
    for i in range(1, 6):
        target_id = request.form.get(f'target_{i}')
        amount = int(request.form.get(f'amount_{i}', 0))
        
        if not target_id or amount < 1:
            flash('يرجى إدخال قيم صحيحة لجميع الخيارات!', 'error')
            return redirect(url_for('home'))
            
        if target_id in targets:
            flash('لا يمكنك التصويت لنفس الشخص مرتين!', 'error')
            return redirect(url_for('home'))
            
        target = User.objects(hunter_id=int(target_id)).first()
        if not target:
            flash('أحد الأهداف غير موجود!', 'error')
            return redirect(url_for('home'))
            
        targets.add(target_id)
        total += amount
        votes[target_id] = {'name': target.username, 'amount': amount}
        
    if total != 100:
        flash(f'مجموع الأصوات يجب أن يكون 100 بالضبط! مجموعك الحالي: {total}', 'error')
        return redirect(url_for('home'))
        
    user.update(
        set__has_voted=True,
        set__f3_votes_cast=votes
    )
    
    # إضافة الأصوات للمستهدفين
    for target_id, vote_data in votes.items():
        User.objects(hunter_id=int(target_id)).update(inc__survival_votes=vote_data['amount'])
        
    flash('تم تسجيل أصواتك بنجاح!', 'success')
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

