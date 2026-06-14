from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, SpellConfig, Notification, GroupMessage
from functools import wraps
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import os, base64, random, math, time, traceback

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

app = Flask(__name__)
app.jinja_env.globals.update(getattr=getattr)

# ==========================================
# ⚙️ إعدادات قاعدة البيانات والسيرفر
# ==========================================
MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    raise Exception("MONGO_URI environment variable not set")

if 'retryWrites=true' not in MONGO_URI:
    sep = '&' if '?' in MONGO_URI else '?'
    MONGO_URI += f'{sep}retryWrites=true'

app.config['MONGODB_SETTINGS'] = {
    'host': MONGO_URI, 'connect': True, 'tls': True,
    'tlsAllowInvalidCertificates': True, 'connectTimeoutMS': 30000,
    'socketTimeoutMS': 30000, 'serverSelectionTimeoutMS': 30000, 'maxPoolSize': 10
}

# الجلسة ممتدة لـ 365 يوماً (حتى لا يتم تسجيل خروج اللاعبين عند تحديث السيرفر)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'SEPHAR_MAZE_IMMORTAL_SECRET_KEY_999')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
db.init_app(app)

# ==========================================
# 🛡️ الصلاحيات والمتغيرات العامة
# ==========================================
@app.context_processor
def inject_global_vars():
    return dict(current_user=getattr(g, 'user', None), settings=getattr(g, 'settings', None))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        u = User.objects(id=ObjectId(session['user_id'])).first()
        if not u or u.role != 'admin': return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 🗺️ خرائط ومهام الطابق الأول (سيفار)
# ==========================================
F1_MAP = {
    'ساحة التجمع': ['مرصد الظلال', 'مستوصف الأرواح', 'ترسانة الأسلحة القديمة'],
    'مرصد الظلال': ['ساحة التجمع', 'قاعة النور الأزلي', 'غرفة المراقبة'],
    'مستوصف الأرواح': ['ساحة التجمع', 'منبع الأنفاس'],
    'ترسانة الأسلحة القديمة': ['ساحة التجمع', 'قاعة البوصلة الفلكية'],
    'قاعة النور الأزلي': ['مرصد الظلال', 'غرفة دروع الطاقة'],
    'غرفة المراقبة': ['مرصد الظلال'],
    'منبع الأنفاس': ['مستوصف الأرواح', 'قاعة البوصلة الفلكية'],
    'قاعة البوصلة الفلكية': ['ترسانة الأسلحة القديمة', 'منبع الأنفاس', 'غرفة دروع الطاقة'],
    'غرفة دروع الطاقة': ['قاعة النور الأزلي', 'قاعة البوصلة الفلكية']
}

TASKS_BY_ROOM = {
    'ساحة التجمع': [{"name": "تجهيز البوق", "description": "نظف بوق التجمع الطارئ"}, {"name": "إشعال الشعلة", "description": "أضئ شعلة البداية"}],
    'مرصد الظلال': [{"name": "مسح العدسة", "description": "نظف عدسة الرؤية"}, {"name": "ترتيب المخطوطات", "description": "رتب سجلات الداخلين"}],
    'قاعة النور الأزلي': [{"name": "توجيه المرايا", "description": "اضبط مرايا النور"}, {"name": "إصلاح البلورة", "description": "أعد طاقة البلورة الزرقاء"}],
    'مستوصف الأرواح': [{"name": "فحص الروح", "description": "قف على منصة الفحص"}, {"name": "خلط الترياق", "description": "امزج الأعشاب المضيئة"}],
    'منبع الأنفاس': [{"name": "تنقية الهواء", "description": "أزل الشوائب من المنبع"}, {"name": "فتح الصمامات", "description": "حرر ضغط الهواء"}],
    'ترسانة الأسلحة القديمة': [{"name": "شحذ السيوف", "description": "اشحذ نصل السيف القديم"}, {"name": "تذخير الأقواس", "description": "رتب السهام"}],
    'قاعة البوصلة الفلكية': [{"name": "ضبط النجوم", "description": "وجه البوصلة للنجم القطبي"}, {"name": "تحديث الخريطة", "description": "ارسم المسار الجديد"}],
    'غرفة دروع الطاقة': [{"name": "شحن الدرع", "description": "حول الطاقة لمولد الدروع"}, {"name": "تفريغ الشحنات", "description": "أفرغ الشحنات الزائدة"}]
}

def compress_image(image_data, quality=70, max_size=(500, 500)):
    if not HAS_PIL: return image_data
    try:
        from io import BytesIO
        img = Image.open(BytesIO(image_data))
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        output = BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()
    except: return image_data

def assign_tasks_to_player(user):
    all_tasks = [{"room": r, "name": t["name"], "description": t["description"], "completed": False} for r, ts in TASKS_BY_ROOM.items() for t in ts]
    user.update(set__f1_tasks=random.sample(all_tasks, min(3, len(all_tasks))))

def execute_trap_effect(user, trap):
    if '_' not in trap.puzzle_type: return
    eff = trap.puzzle_type.split('_', 1)[1]
    if eff == 'give_points': user.update(inc__points=trap.reward_points, inc__intelligence_points=10); flash(f'نجاح! حصلت على {trap.reward_points} دنانير!', 'success')
    elif eff == 'steal_points': user.update(set__points=max(0, user.points - trap.trap_penalty_points), dec__intelligence_points=5); flash(f'فخ مرعب! سُرق منك {trap.trap_penalty_points} دنانير!', 'error')
    elif eff == 'give_item' and trap.reward_item: user.update(push__inventory=trap.reward_item); flash(f'نجاح! حصلت على الأداة: {trap.reward_item}', 'success')
    elif eff == 'steal_item':
        if user.inventory: stolen = random.choice(user.inventory); user.update(pull__inventory=stolen); flash(f'فخ مرعب! سُرقت منك الأداة: {stolen}', 'error')
    elif eff == 'give_seal' and trap.reward_item not in user.collected_seals: user.update(push__inventory=trap.reward_item); flash(f'نجاح أسطوري! حصلت على ختم: {trap.reward_item}', 'success')
    elif eff == 'quicksand': dur = trap.trap_duration_minutes or 5; user.update(set__quicksand_lock_until=datetime.utcnow() + timedelta(minutes=dur)); flash(f'وقعت في فخ الرمال! أنت مجمد لمدة {dur} دقائق.', 'error')

def wake_up_maze(settings, now):
    sleep_start = settings.sleep_start_time or now
    duration = now - sleep_start
    updates = {'set__sleep_mode_active': False, 'set__sleep_start_time': None}
    
    if settings.gates_end_time: updates['set__gates_end_time'] = settings.gates_end_time + duration
    if settings.war_end_time: updates['set__war_end_time'] = settings.war_end_time + duration
    if settings.vote_end_time: updates['set__vote_end_time'] = settings.vote_end_time + duration
    if getattr(settings, 'last_global_bleed', None): updates['set__last_global_bleed'] = settings.last_global_bleed + duration
    
    GlobalSettings.objects(setting_name='main_config').update_one(**updates)
    
    for u in User.objects(status__in=['active', 'inactive']):
        if getattr(u, 'last_active', None):
            u.update(set__last_active=u.last_active + duration)
            
    return duration

@app.before_request
def fast_health_check():
    if request.method == 'HEAD' or request.path == '/health': return "OK", 200

def check_lazy_death(user, settings):
    try:
        if not user or getattr(user, 'role', '') == 'admin' or getattr(user, 'status', '') not in ['active', 'dead_body']: return
        if user.hunter_id in [1000, 1001] or getattr(settings, 'sleep_mode_active', False): return
        now = datetime.utcnow()
        last_act = getattr(user, 'last_active', None) or getattr(user, 'created_at', None) or now
        if (now - last_act).total_seconds() / 3600.0 > 72: 
            user.update(set__health=0, set__status='eliminated', set__freeze_reason='ابتلعته الرمال بسبب الخمول')
    except: pass

@app.before_request
def pre_process():
    if request.endpoint in ['static', 'get_avatar', 'fast_health_check', 'login', 'register', 'logout']: return
    try: g.settings = GlobalSettings.objects(setting_name='main_config').first()
    except Exception as e: return f"<div style='direction:rtl; background:#0a0a0a; color:#e74c3c; padding:30px; text-align:center;'><h1>🚨 مشكلة اتصال بقاعدة البيانات</h1><p>{str(e)}</p></div>", 503

    settings = g.settings
    now = datetime.utcnow()
    user_is_admin = False
    if 'user_id' in session:
        try:
            u = User.objects(id=ObjectId(session['user_id'])).first()
            if u and u.role == 'admin': user_is_admin = True
        except: pass

    if settings:
        # نظام الجدولة الزمنية للسبات
        if settings.scheduled_sleep_start and settings.scheduled_sleep_end:
            current_time_str = now.strftime('%H:%M')
            s_start = settings.scheduled_sleep_start
            s_end = settings.scheduled_sleep_end
            is_sleeping_time = s_start <= current_time_str < s_end if s_start < s_end else current_time_str >= s_start or current_time_str < s_end
            if is_sleeping_time and not settings.sleep_mode_active:
                GlobalSettings.objects(setting_name='main_config').update_one(set__sleep_mode_active=True, set__sleep_start_time=now)
                settings.sleep_mode_active = True
            elif not is_sleeping_time and settings.sleep_mode_active:
                wake_up_maze(settings, now)
                settings.sleep_mode_active = False

        if settings.sleep_mode_active and not user_is_admin and request.endpoint not in ['static', 'login', 'logout']:
            return render_template('locked.html', message='الليل خيّم على سيفار... الزمن متوقف والمتاهة في سبات 🌙')

        if not settings.sleep_mode_active:
            # 1. النزيف الشامل (الطابق 2)
            if settings.war_mode:
                bleed_rate = getattr(settings, 'bleed_rate_minutes', 60)
                bleed_amt = getattr(settings, 'bleed_amount', 1)
                last_global_bleed = getattr(settings, 'last_global_bleed', now)
                minutes_passed = (now - last_global_bleed).total_seconds() / 60.0
                if minutes_passed >= bleed_rate and bleed_rate > 0:
                    cycles = math.floor(minutes_passed / bleed_rate)
                    total_damage = cycles * bleed_amt
                    active_users = User.objects(status='active', hunter_id__nin=[1000, 1001])
                    for u in active_users:
                        new_hp = max(0, u.health - total_damage)
                        if new_hp <= 0:
                            u.update(set__health=0, set__status='eliminated', set__freeze_reason='مات نزفاً في الحرب الشاملة')
                            GlobalSettings.objects(setting_name='main_config').update_one(inc__dead_count=1)
                        else: u.update(set__health=new_hp)
                    GlobalSettings.objects(setting_name='main_config').update_one(set__last_global_bleed=now - timedelta(minutes=(minutes_passed % bleed_rate)))
                if settings.war_end_time and now >= settings.war_end_time: GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False)

            # 2. إعدام المتخاذلين (البوابات)
            if settings.gates_mode_active and settings.gates_end_time and now >= settings.gates_end_time:
                lazy_users = User.objects(status='active', chosen_gate=0, hunter_id__nin=[1000, 1001])
                lazy_users.update(set__status='eliminated', set__freeze_reason='أُعدم لرفضه دخول بوابات القدر')
                hidden_users = User.objects(status='active', gate_status__startswith='hidden_')
                for hu in hidden_users:
                    real_fate = hu.gate_status.split('_')[1]
                    if real_fate == 'passed': hu.update(set__zone='الطابق الأول', set__gate_status='passed')
                    elif real_fate == 'death': hu.update(set__status='eliminated', set__freeze_reason='سُحق في فخ البوابة', set__gate_status='death')
                    elif real_fate == 'testing': hu.update(set__gate_status='testing')
                GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=False)

            # 3. محرك الطابق الأول (فوز الملعون أو فوز الأبرياء)
            if getattr(settings, 'floor1_mode_active', False):
                if getattr(settings, 'floor1_darkness_until', None) and now >= settings.floor1_darkness_until: GlobalSettings.objects(setting_name='main_config').update_one(set__floor1_darkness_until=None)
                if getattr(settings, 'floor1_locked_until', None) and now >= settings.floor1_locked_until: GlobalSettings.objects(setting_name='main_config').update_one(set__floor1_locked_room='', set__floor1_locked_until=None)

                win_percent = getattr(settings, 'f1_cursed_win_percent', 50)
                target_per_user = getattr(settings, 'floor1_individual_gems_target', 3)
                
                for gid in User.objects(status='active', group_id__gt=0).distinct('group_id'):
                    living = User.objects(group_id=gid, status='active')
                    total_living = living.count()
                    if total_living > 0:
                        cursed_count = living.filter(is_cursed=True).count()
                        innocents_count = total_living - cursed_count
                        
                        total_group_members = User.objects(group_id=gid, role='hunter').count() 
                        gems_needed = total_group_members * target_per_user
                        current_gems = sum([u.gems_collected for u in User.objects(group_id=gid)])
                        
                        if cursed_count > 0 and (cursed_count / total_living) * 100 >= win_percent:
                            living.update(set__zone='الطابق الثاني')
                            GroupMessage(group_id=gid, sender_name="النظام", message="🔪 سقط الأبرياء... ونجح الملعون! انتقل الأحياء للطابق الثاني.", is_system_msg=True).save()
                            
                        elif cursed_count > 0 and current_gems >= gems_needed:
                            living.filter(is_cursed=True).update(set__status='eliminated', set__freeze_reason='احترق بنور الأحجار المجمعة')
                            living.filter(is_cursed=False).update(set__zone='الطابق الثاني')
                            GroupMessage(group_id=gid, sender_name="النظام", message="✨ اكتمل النور! احترق الملعون وفُتحت البوابة للناجين!", is_system_msg=True).save()
                            
                        elif cursed_count == 0 and innocents_count > 0:
                            living.update(set__zone='الطابق الثاني')
                            GroupMessage(group_id=gid, sender_name="النظام", message="✨ تم تطهير اللعنة بالكامل! البوابة مفتوحة للطابق الثاني للناجين.", is_system_msg=True).save()

            # 4. محرك الطابق الثالث
            if settings.floor3_mode_active and not getattr(settings, 'floor3_paused', False) and settings.vote_end_time and now >= settings.vote_end_time:
                slackers = User.objects(has_voted=False, status='active', role='hunter', hunter_id__nin=[1000, 1001])
                slackers.update(set__status='eliminated', set__freeze_reason='تخاذل في التصويت (المحكمة)')
                for u in User.objects(status='active', role='hunter', hunter_id__nin=[1000, 1001]).order_by('-survival_votes')[:settings.vote_top_n]: 
                    u.update(set__zone='المعركة الأخيرة')
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=False, set__floor3_results_active=True)

        # 5. الصيانة
        if settings.maintenance_mode and settings.maintenance_until and now > settings.maintenance_until:
            GlobalSettings.objects(setting_name='main_config').update_one(set__maintenance_mode=False, set__maintenance_pages=[])
        if settings.maintenance_mode and not user_is_admin:
            m_pages = settings.maintenance_pages or []
            if 'all' in m_pages or request.endpoint in m_pages: 
                return render_template('locked.html', message='المتاهة قيد الصيانة ⏳')

    user = None
    if 'user_id' in session:
        try: user = User.objects(id=ObjectId(session['user_id'])).first()
        except: user = None
        if not user: session.clear(); return redirect(url_for('login'))
        if not user.last_active or (now - user.last_active).total_seconds() > 1800: user.update(set__last_active=now)
        check_lazy_death(user, settings)
        if user.status == 'active' and getattr(user, 'quicksand_lock_until', None) and now < user.quicksand_lock_until: return render_template('locked.html', message=f'مقيّد في الرمال لمدة {(user.quicksand_lock_until - now).seconds // 60} دقائق')
        if getattr(user, 'gate_status', '') == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']: return render_template('gate_test.html', message=getattr(settings, 'gates_test_question', 'ما هو سر المتاهة؟'), user=user)

    g.user = user

# ==========================================
# 🏰 الساحة الرئيسية (Home)
# ==========================================
@app.route('/')
def home():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    user = getattr(g, 'user', None)
    
    winner_user = User.objects(hunter_id=settings.maze_winner_id).first() if settings and getattr(settings, 'maze_winner_id', 0) > 0 else None
    emperor = User.objects(hunter_id=1000).first()
    active_hunters = User.objects(status='active', role='hunter', hunter_id__nin=[1000, 1001], id__ne=user.id if user else None) if settings and settings.floor3_mode_active else []
        
    room_players, dead_bodies_in_room, adjacent_rooms, room_counts = [], [], [], {}
    is_dark, has_meeting, meeting_info = False, False, None
    total_gems, gems_needed = 0, 1
    
    if settings and getattr(settings, 'floor1_mode_active', False) and user and user.status == 'active' and user.group_id > 0:
        gid_str = str(user.group_id)
        if gid_str in getattr(settings, 'f1_active_meetings', {}): has_meeting = True; meeting_info = settings.f1_active_meetings[gid_str]
        if getattr(settings, 'floor1_darkness_until', None) and datetime.utcnow() < settings.floor1_darkness_until: is_dark = True
        
        total_group_members = User.objects(group_id=user.group_id, role='hunter').count()
        gems_needed = max(1, total_group_members * getattr(settings, 'floor1_individual_gems_target', 3))
        total_gems = sum([u.gems_collected for u in User.objects(group_id=user.group_id)])
        
        adjacent_rooms = F1_MAP.get(getattr(user, 'current_room', 'ساحة التجمع'), [])
        dead_bodies_in_room = User.objects(group_id=user.group_id, current_room=user.current_room, status='dead_body')

        if not is_dark:
            room_players = User.objects(group_id=user.group_id, current_room=user.current_room, status='active', id__ne=user.id, hunter_id__nin=[1000, 1001])
            if user.current_room == 'مرصد الظلال': 
                for r in F1_MAP.keys():
                    c = User.objects(group_id=user.group_id, current_room=r, status='active', hunter_id__nin=[1000, 1001]).count()
                    if c > 0: room_counts[r] = c
            elif user.current_room == 'غرفة المراقبة': 
                cam_rooms = ['منبع الأنفاس', 'مستوصف الأرواح', 'قاعة النور الأزلي']
                room_players = User.objects(group_id=user.group_id, current_room__in=cam_rooms, status='active', id__ne=user.id, hunter_id__nin=[1000, 1001])

    f3_users = User.objects(status='active', role='hunter', survival_votes__gt=0, hunter_id__nin=[1000, 1001]).order_by('-survival_votes')
    player_tasks = getattr(user, 'f1_tasks', []) if user else []
    current_room_tasks = [t for t in player_tasks if t.get('room') == user.current_room and not t.get('completed', False)] if user and user.current_room else []
    
    return render_template('index.html', 
        winner_user=winner_user, emperor=emperor, active_hunters=active_hunters, 
        room_players=room_players, room_counts=room_counts, dead_bodies_in_room=dead_bodies_in_room, 
        is_dark=is_dark, adjacent_rooms=adjacent_rooms, has_meeting=has_meeting, meeting_info=meeting_info, 
        f3_users=f3_users, f1_map=F1_MAP, player_tasks=player_tasks, current_room_tasks=current_room_tasks, 
        settings=settings, total_gems=total_gems, gems_needed=gems_needed
    )

# ==========================================
# 🔑 الدخول والتسجيل
# ==========================================
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
        if User.objects(username=request.form['username']).first(): flash('الاسم مستخدم مسبقاً.', 'error'); return redirect(url_for('register'))
        
        last_user = User.objects(hunter_id__nin=[1000, 1001]).order_by('-hunter_id').first()
        new_id = last_user.hunter_id + 1 if last_user and last_user.hunter_id >= 1002 else 1002
            
        User(hunter_id=new_id, username=request.form['username'], password_hash=generate_password_hash(request.form['password']), role='hunter', status='inactive', zone='البوابات', special_rank='مستكشف', facebook_link=fb_link).save()
        flash(f'تم التسجيل! حسابك قيد المراجعة. (ID: {new_id})', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ==========================================
# 👤 الملف الشخصي وإعدادات الهوية
# ==========================================
@app.route('/profile')
@login_required
def profile():
    user = g.user
    my_items = StoreItem.objects(name__in=getattr(user, 'inventory', []) or [])
    fresh_settings = GlobalSettings.objects(setting_name='main_config').first()
    return render_template(
        'profile.html', 
        user=user, 
        my_items=my_items, 
        my_seals=[i for i in my_items if getattr(i, 'item_type', '') == 'seal'], 
        settings=fresh_settings
    )

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
                    img_bytes = compress_image(data)
                    b64 = base64.b64encode(img_bytes).decode('utf-8')
                    user.update(set__avatar=f"data:image/jpeg;base64,{b64}")
                    flash('تم تحديث النقش!', 'success')

        elif action == 'change_name':
            new_name = request.form.get('new_name')
            if getattr(user, 'last_name_change', None) and (now - user.last_name_change).days < 7: 
                flash('تغيير الاسم متاح مرة كل 7 ايام!', 'error')
            elif User.objects(username=new_name).first(): 
                flash('الاسم مستخدم مسبقاً!', 'error')
            else: 
                user.update(set__username=new_name, set__last_name_change=now)
                flash('تم تغيير الاسم!', 'success')

        elif action == 'change_password':
            if check_password_hash(user.password_hash, request.form.get('old_password', '')) and request.form.get('new_password') == request.form.get('confirm_password'):
                user.update(set__password_hash=generate_password_hash(request.form.get('new_password')), set__last_password_change=now)
                flash('تم تغيير الختم السري!', 'success')
    except Exception as e: 
        flash('حدث خطأ في تحديث البيانات.', 'error')
        
    return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    # حماية ملف الإمبراطور (ID 1000)
    if target_id in [1000, 1001] and g.user.hunter_id not in [1000, 1001]:
        return f"<div style='background:#030202; color:#e74c3c; height:100vh; display:flex; align-items:center; justify-content:center; flex-direction:column; font-family:Cairo, sans-serif; text-align:center; padding:20px; box-shadow: inset 0 0 100px #000;'><h1 style='font-size:50px; margin:0; text-shadow: 0 0 20px #ff0000;'>👁️</h1><h2 style='text-shadow: 0 0 10px #e74c3c;'>هذا الحساب محجوب في طيات الظلام...</h2><p style='color:#aaa; font-size:18px;'>لا تقترب من العرش الإمبراطوري!</p><a href='/' style='color:#b59b4c; margin-top:30px; border:1px solid #b59b4c; padding:10px 30px; text-decoration:none; border-radius:5px;'>العودة للساحة</a></div>", 403
        
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']: 
        return redirect(url_for('home'))
        
    my_items = StoreItem.objects(name__in=getattr(g.user, 'inventory', []) or [])
    fresh_settings = GlobalSettings.objects(setting_name='main_config').first()
    
    return render_template(
        'hunter_profile.html', 
        target_user=target_user, 
        my_weapons=[i for i in my_items if getattr(i, 'item_type', '') == 'weapon'], 
        my_heals=[i for i in my_items if getattr(i, 'item_type', '') == 'heal'], 
        my_spies=[i for i in my_items if getattr(i, 'item_type', '') == 'spy'], 
        my_steals=[i for i in my_items if getattr(i, 'item_type', '') == 'steal'],
        my_totems=[i for i in my_items if getattr(i, 'item_type', '') == 'totem'],
        settings=fresh_settings
    )

# ==========================================
# 👥 التحالفات (الأصدقاء)
# ==========================================
@app.route('/friends', methods=['GET'])
@login_required
def friends():
    search_query = request.args.get('search')
    search_result = None
    
    if search_query: 
        if search_query in ['1000', '1001', 'الإمبراطور', 'مساعد الإمبراطور']:
            flash('👁️ الفضول قد يقتل صاحبه... لا تبحث عن الظلال.', 'error')
        elif search_query.isdigit(): 
            search_result = User.objects(hunter_id=int(search_query)).first()
        else: 
            search_result = User.objects(username__icontains=search_query, hunter_id__nin=[1000, 1001]).first()
    
    exclude_roles = ['ghost', 'cursed_ghost', 'admin']
    exclude_ids = [g.user.hunter_id, 1000, 1001] + getattr(g.user, 'friends', []) + getattr(g.user, 'friend_requests', [])
    suggested_hunters = User.objects(status='active', role__nin=exclude_roles, hunter_id__nin=exclude_ids).order_by('-last_active')[:30]
    
    friend_requests = User.objects(hunter_id__in=getattr(g.user, 'friend_requests', []))
    friends_list = User.objects(hunter_id__in=getattr(g.user, 'friends', []))
    
    return render_template('friends.html', user=g.user, search_result=search_result, friend_requests=friend_requests, friends=friends_list, suggested_hunters=suggested_hunters)

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = g.user
    target = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
    if user.status != 'active': return redirect(request.referrer or url_for('home'))
    if not target or target.status not in ['active', 'inactive']: return redirect(request.referrer or url_for('home'))
    if target.id == user.id or target.hunter_id in [1000, 1001]: return redirect(request.referrer or url_for('home'))
    
    if getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_answer=str(target.hunter_id), category='hidden').first()
        if trap and str(user.id) not in getattr(trap, 'winners_list', []) and getattr(trap, 'current_winners', 0) < getattr(trap, 'max_winners', 1):
            if trap.puzzle_type.startswith('ghost_'): 
                execute_trap_effect(user, trap)
                trap.update(inc__current_winners=1, push__winners_list=str(user.id))
        else: flash('اختفى الشبح أو نفدت المكافآت.', 'info')
    elif target.hunter_id not in getattr(user, 'friends', []) and user.hunter_id not in getattr(target, 'friend_requests', []): 
        target.update(push__friend_requests=user.hunter_id)
        user.update(push__sent_requests=target.hunter_id)
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
            user.update(pull__sent_requests=target.hunter_id)
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
        user.update(pull__sent_requests=target.hunter_id)
    return redirect(request.referrer or url_for('home'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = g.user
    friend = User.objects(hunter_id=friend_id).first()
    if user.status != 'active': return redirect(request.referrer or url_for('home'))
    if friend and friend.status in ['active', 'inactive'] and friend_id in getattr(user, 'friend_requests', []): 
        user.update(pull__friend_requests=friend_id, push__friends=friend_id)
        friend.update(push__friends=user.hunter_id, pull__sent_requests=user.hunter_id)
    return redirect(request.referrer or url_for('home'))

# ==========================================
# 🎁 الإمدادات واستخدام الأسلحة والتوتم
# ==========================================
@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    sender = g.user
    receiver = User.objects(hunter_id=target_id).first()
    if sender.status != 'active' or not receiver: 
        return redirect(request.referrer or url_for('home'))
        
    transfer_type = request.form.get('transfer_type')
    if transfer_type == 'points':
        try:
            amt = int(request.form.get('amount') or 0)
            if 0 < amt <= sender.points: 
                sender.update(dec__points=amt, inc__loyalty_points=2)
                receiver.update(inc__points=amt)
                flash(f'تم إرسال {amt} دنانير!', 'success')
        except: pass
    elif transfer_type == 'item':
        itm = request.form.get('item_name')
        if itm in getattr(sender, 'inventory', []): 
            sender.update(pull__inventory=itm, inc__loyalty_points=5)
            receiver.update(push__inventory=itm)
            flash(f'تم إرسال الأداة [{itm}]!', 'success')
            
    return redirect(request.referrer or url_for('home'))

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    attacker = g.user
    target = User.objects(hunter_id=target_id).first()
    settings = g.settings
    
    item_name = request.form.get('item_name')
    item = StoreItem.objects(name=item_name).first()
    if not item or item_name not in getattr(attacker, 'inventory', []): return redirect(request.referrer or url_for('home'))
    
    item_type = getattr(item, 'item_type', '')
    
    if attacker.status != 'active' and item_type != 'totem': 
        flash('حسابك معطل، الأطياف لا يمكنها الهجوم!', 'error')
        return redirect(request.referrer or url_for('home'))
        
    now = datetime.utcnow()

    # التوتم (يمكن للميت إحياء نفسه، أو يحييه شخص آخر)
    if item_type == 'totem':
        if not getattr(settings, 'war_mode', False):
            flash('التوتم لا تتفعل طاقته إلا في الطابق الثاني (الحرب الشاملة)!', 'error')
        elif target.status not in ['eliminated', 'dead_body']:
            flash('هذا اللاعب لا يزال حياً يُرزق!', 'error')
        elif target.hunter_id in [1000, 1001]:
            flash('لا يمكن استخدامه على الكيانات الإمبراطورية!', 'error')
        else:
            target.update(set__status='active', set__health=50, set__freeze_reason='')
            attacker.update(pull__inventory=item_name)
            if attacker.id == target.id: flash('🌟 انتفضت الروح! لقد أعدت نفسك للحياة بنصف قوتك!', 'success')
            else: flash(f'🌟 لقد منحت روحك للرحالة {target.username} وأعدته للحياة!', 'success')
        return redirect(request.referrer or url_for('home'))

    if not target or target.status != 'active': return redirect(request.referrer or url_for('home'))

    if item_type in ['weapon', 'steal', 'spy']:
        cooldown_mins = getattr(settings, 'attack_cooldown_minutes', 0)
        if cooldown_mins > 0 and attacker.last_action_time and (now - attacker.last_action_time).total_seconds() < (cooldown_mins * 60):
            flash(f'⏳ انتظر {int((cooldown_mins*60) - (now - attacker.last_action_time).total_seconds())} ثانية.', 'error')
            return redirect(request.referrer or url_for('home'))

    if getattr(settings, 'final_battle_mode', False) and target.hunter_id != 1000 and item_type in ['weapon', 'steal', 'spy']: 
        flash('الإمبراطور هو عدوك الوحيد الآن! وجّه ضربتك نحو العرش!', 'error')
        return redirect(request.referrer or url_for('home'))
    
    if item_type == 'weapon':
        if getattr(target, 'role', '') == 'admin' and not getattr(settings, 'final_battle_mode', False): 
            flash('الإمبراطور محصن حالياً ولا يمكن استهدافه!', 'error')
        elif getattr(target, 'has_shield', False): 
            target.update(set__has_shield=False)
            flash('انكسر درع الهدف وضاعت ضربتك!', 'error')
        else:
            new_hp = target.health - getattr(item, 'effect_amount', 0)
            if new_hp <= 0:
                target.update(set__health=0, set__status='eliminated', set__freeze_reason='سقط في المعركة')
                GlobalSettings.objects(setting_name='main_config').update_one(inc__dead_count=1)
                if getattr(target, 'role', '') == 'admin': 
                    GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=False, set__war_mode=False, set__maze_winner_id=attacker.hunter_id)
            else: target.update(set__health=new_hp)
            flash('تمت الضربة بنجاح!', 'success')
        attacker.update(pull__inventory=item_name, set__last_action_time=now)
        
    elif item_type == 'heal':
        heal_amt = getattr(item, 'effect_amount', 0)
        new_hp = target.health + heal_amt if getattr(target, 'role', '') == 'admin' else min(100, target.health + heal_amt)
        target.update(set__health=new_hp)
        if target.id != attacker.id: attacker.update(inc__loyalty_points=5)
        attacker.update(pull__inventory=item_name, set__last_action_time=now)
        flash('تم العلاج بنجاح!', 'success')
            
    elif item_type == 'spy':
        if getattr(target, 'has_shield', False): 
            attacker.update(pull__inventory=item_name, set__last_action_time=now); flash('الهدف محصن ضد التجسس!', 'error')
        else: 
            attacker.update(set__tajis_eye_until=now + timedelta(hours=1), pull__inventory=item_name, set__last_action_time=now); flash('تجسست بنجاح! يمكنك رؤية خباياه.', 'success')
            
    elif item_type == 'steal':
        stolen_item = request.form.get('target_item')
        if stolen_item in getattr(target, 'inventory', []):
            if getattr(target, 'has_shield', False): 
                attacker.update(pull__inventory=item_name, set__last_action_time=now); flash('الهدف محمي! ضاعت محاولتك.', 'error')
            else: 
                target.update(pull__inventory=stolen_item)
                attacker.update(push__inventory=stolen_item, pull__inventory=item_name, inc__intelligence_points=5, set__last_action_time=now)
                flash(f'تمت سرقة [{stolen_item}] بنجاح!', 'success')
                
    elif item_type == 'seal':
        if target.id == attacker.id:
            collected = getattr(attacker, 'collected_seals', [])
            if item_name not in collected:
                attacker.update(push__collected_seals=item_name, pull__inventory=item_name)
                attacker.reload()
                if len(attacker.collected_seals) >= 4:
                    if settings: GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False, set__final_battle_mode=False, set__maze_winner_id=attacker.hunter_id)
                    User.objects(status='active', hunter_id__nin=[1000, 1001]).update(set__health=100)
                    flash('🔥 جمعت الأختام الأربعة الفريدة! لقد فزت بالمتاهة!', 'success')
                else: flash('تم تحطيم الختم ودمجه بروحك!', 'success')
            else: 
                attacker.update(pull__inventory=item_name)
                flash('لقد فعلت هذا الختم مسبقاً! تبخر بلا فائدة.', 'error')
                
    return redirect(request.referrer or url_for('home'))

# ==========================================
# 🕵️ محرك الطابق الأول (مهارات الملعون، المهام، القتل)
# ==========================================
@app.route('/f1/move', methods=['POST'])
@login_required
def f1_move():
    user = g.user; settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or user.status != 'active': return redirect(url_for('home'))
    
    new_room = request.form.get('room')
    
    if getattr(settings, 'floor1_locked_room', '') == new_room and settings.floor1_locked_until and datetime.utcnow() < settings.floor1_locked_until:
        flash('🚪 هذه الغرفة مقفلة بإحكام حالياً بقوة سحرية!', 'error'); return redirect(url_for('home'))
    if getattr(settings, 'floor1_locked_room', '') == user.current_room and settings.floor1_locked_until and datetime.utcnow() < settings.floor1_locked_until:
        flash('🚪 أنت محتجز في هذه الغرفة ولا يمكنك الخروج منها الآن!', 'error'); return redirect(url_for('home'))
        
    if not new_room or new_room not in F1_MAP.get(user.current_room, []): return redirect(url_for('home'))
    
    now = datetime.utcnow()
    last_move = getattr(user, 'f1_last_move', None)
    cooldown = getattr(settings, 'floor1_move_cooldown', 30)
    if last_move and (now - last_move).total_seconds() < cooldown:
        flash(f'⏳ الإرهاق يمنعك من الركض. انتظر {int(cooldown - (now - last_move).total_seconds())} ثانية.', 'error')
        return redirect(url_for('home'))
        
    user.update(set__current_room=new_room, set__f1_last_move=now)
    return redirect(url_for('home'))

@app.route('/f1/task', methods=['POST'])
@login_required
def f1_task():
    user = g.user; settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or user.status != 'active': return redirect(url_for('home'))
    
    task_name = request.form.get('task_name')
    tasks = getattr(user, 'f1_tasks', [])
    updated = False
    
    for t in tasks:
        if t.get('name') == task_name and t.get('room') == user.current_room and not t.get('completed', False):
            t['completed'] = True
            updated = True
            break
            
    if updated:
        user.update(set__f1_tasks=tasks, inc__gems_collected=1)
        flash('✨ استخرجت حجراً كريماً بنجاح!', 'success')
    return redirect(url_for('home'))

@app.route('/f1/kill', methods=['POST'])
@login_required
def f1_kill():
    attacker = g.user; settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or attacker.status != 'active' or not getattr(attacker, 'is_cursed', False): return redirect(url_for('home'))
    
    target_id = int(request.form.get('target_id', 0))
    target = User.objects(hunter_id=target_id, group_id=attacker.group_id, status='active', current_room=attacker.current_room).first()
    if not target: return redirect(url_for('home'))
        
    now = datetime.utcnow()
    last_kill = getattr(attacker, 'f1_last_kill', None)
    kill_cooldown = getattr(settings, 'floor1_kill_cooldown', 60)
    if last_kill and (now - last_kill).total_seconds() < kill_cooldown:
        flash(f'⏳ نصلك يحتاج للراحة {int(kill_cooldown - (now - last_kill).total_seconds())} ثانية.', 'error')
        return redirect(url_for('home'))

    occupants = User.objects(group_id=attacker.group_id, current_room=attacker.current_room, status='active').count()
    if occupants > 2:
        flash('⚠️ احذر! لقد قتلت بوجود شهود! جريمتك علنية ومفضوحة!', 'error')

    target.update(set__status='dead_body', set__freeze_reason='مات مقتولاً')
    attacker.update(set__f1_last_kill=now, inc__stats_ghosts_caught=1)
    flash(f'🔪 غدرت بـ {target.username} بنجاح!', 'success')
    return redirect(url_for('home'))

@app.route('/f1/sabotage', methods=['POST'])
@login_required
def f1_sabotage():
    user = g.user; settings = g.settings
    if not getattr(settings, 'floor1_mode_active', False) or user.status != 'active' or not getattr(user, 'is_cursed', False): return redirect(url_for('home'))
    
    sab_type = request.form.get('sabotage_type')
    now = datetime.utcnow()
    
    if sab_type == 'lights' and not getattr(user, 'used_lights', False):
        GlobalSettings.objects(setting_name='main_config').update_one(set__floor1_darkness_until=now + timedelta(minutes=1))
        user.update(set__used_lights=True)
        GroupMessage(group_id=user.group_id, sender_name="النظام", message="⚠️ انطفأت أنوار المتاهة! الظلام يعم المكان.", is_system_msg=True).save()
        flash('انطفأت الأنوار!', 'success')
        
    elif sab_type == 'doors' and not getattr(user, 'used_doors', False):
        room = request.form.get('target_room')
        GlobalSettings.objects(setting_name='main_config').update_one(set__floor1_locked_room=room, set__floor1_locked_until=now + timedelta(seconds=30))
        user.update(set__used_doors=True)
        flash(f'تم إقفال {room} لمدة 30 ثانية!', 'success')
        
    elif sab_type == 'vent' and not getattr(user, 'used_vent', False):
        room = request.form.get('target_room')
        user.update(set__current_room=room, set__used_vent=True)
        flash(f'قفزت من النفق إلى {room}!', 'success')
        
    return redirect(url_for('home'))

# ==========================================
# 📜 المراسيم، النقوش، والروابط السرية
# ==========================================
@app.route('/news')
@login_required
def news(): 
    return render_template('news.html', news_list=News.objects(category='news', status='approved').order_by('-created_at'))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    user = g.user; settings = g.settings
    if request.method == 'POST':
        if user.status != 'active': flash('حسابك موقوف عن اللعب.', 'error'); return redirect(url_for('puzzles'))
        guess = request.form.get('guess')
        puzzle = News.objects(id=request.form.get('puzzle_id')).first()
        if puzzle and str(guess) == str(getattr(puzzle, 'puzzle_answer', '')) and str(user.id) not in getattr(puzzle, 'winners_list', []):
            if getattr(puzzle, 'current_winners', 0) < getattr(puzzle, 'max_winners', 1):
                user.update(inc__points=getattr(puzzle, 'reward_points', 0), inc__stats_puzzles_solved=1, inc__intelligence_points=10)
                puzzle.update(push__winners_list=str(user.id), inc__current_winners=1)
                flash('إجابة صحيحة!', 'success')
        else: flash('إجابة خاطئة أو أنك حللته مسبقاً!', 'error')
        return redirect(url_for('puzzles'))
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = g.user
    if user.status != 'active': return redirect(url_for('home'))
    try: puzzle = News.objects(id=puzzle_id).first()
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
        if user.status != 'active': flash('حسابك موقوف عن النشر.', 'error'); return redirect(url_for('declarations'))
        img = ''
        file = request.files.get('image_file')
        if file and file.filename != '': img = f"data:image/jpeg;base64,{base64.b64encode(compress_image(file.read())).decode('utf-8')}"
        News(title=f"تصريح من {user.username}", content=request.form.get('content', '').strip(), image_data=img, category='declaration', author=user.username, status='approved' if user.role == 'admin' else 'pending').save()
        flash('تم النشر بنجاح!', 'success')
        return redirect(url_for('declarations'))
    
    avatars = {u.username: u.hunter_id for u in User.objects(username__in=set([d.author for d in News.objects(category='declaration')]))}
    return render_template('declarations.html', approved_decs=News.objects(category='declaration', status='approved').order_by('-created_at'), pending_decs=News.objects(category='declaration', status='pending') if user.role == 'admin' else [], my_pending_decs=News.objects(category='declaration', status='pending', author=user.username).order_by('-created_at'), current_user=user, avatars=avatars)

==================
# 🛒 السوق، المقبرة، البوابات، والمذبح
# ==========================================
@app.route('/store')
@login_required
def store(): 
    return render_template('store.html', items=StoreItem.objects())

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    user = g.user
    if user.status != 'active': flash('حسابك موقوف.', 'error'); return redirect(url_for('store'))
    try: item = StoreItem.objects(id=ObjectId(item_id)).first()
    except: return redirect(url_for('store'))
    
    if user and item and user.points >= item.price:
        if getattr(item, 'is_mirage', False): 
            user.update(dec__points=item.price, dec__intelligence_points=10)
            flash(getattr(item, 'mirage_message', 'فخ سراب! خسرت الدنانير.'), 'error')
        else:
            user.update(dec__points=item.price)
            if getattr(item, 'is_luck', False): 
                outcome = random.randint(getattr(item, 'luck_min', 0), getattr(item, 'luck_max', 0))
                user.update(inc__points=outcome)
                flash(f'صندوق حظ: النتيجة {outcome} دنانير!', 'success' if outcome >= 0 else 'error')
            else: 
                user.update(push__inventory=item.name, inc__stats_items_bought=1)
                flash(f'تم شراء [{item.name}] بنجاح!', 'success')
    else: flash('دنانيرك لا تكفي!', 'error')
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated', hunter_id__nin=[1000, 1001]).order_by('-id'))

@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    user = g.user; settings = g.settings
    if user.status == 'active' and getattr(settings, 'gates_mode_active', False) and getattr(user, 'chosen_gate', 0) == 0: 
        user.update(set__chosen_gate=int(request.form.get('gate_num') or 0), set__gate_status='waiting')
        flash('سُجل اختيارك! انتظر نهاية الوقت.', 'info')
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    if g.user.gate_status == 'testing': g.user.update(set__gate_test_answer=request.form.get('test_answer', '')); flash('سُلمت الإجابة.', 'success')
    return redirect(url_for('home'))

# ==========================================
# 👑 لوحة الإدارة الشاملة
# ==========================================
@app.route('/admin_hard_delete/<int:target_id>', methods=['POST'])
@admin_required
def admin_hard_delete(target_id):
    if target_id not in [1000, 1001]:
        u = User.objects(hunter_id=target_id).first()
        if u: u.delete(); flash('تم طمس أثر اللاعب!', 'success')
    return redirect(request.referrer)

@app.route('/admin_delete_item', methods=['POST'])
@admin_required
def admin_delete_item():
    tid = int(request.form.get('target_id', 0))
    item = request.form.get('item_name')
    u = User.objects(hunter_id=tid).first()
    if u and item in u.inventory:
        u.update(pull__inventory=item)
        flash(f'تم سحب {item} من حقيبته.', 'success')
    return redirect(request.referrer)

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    
    if request.method == 'POST':
        act = request.form.get('action')
        
        # ===> مسار طمس المراسيم والألغاز (منع 404) <===
        if act == 'delete_news':
            news_id = request.form.get('news_id')
            if news_id:
                News.objects(id=ObjectId(news_id)).delete()
                flash('تم طمس المرسوم/اللغز بنجاح!', 'success')
                
        elif act == 'hard_delete_single':
            tid = request.form.get('target_id')
            if tid and tid.isdigit() and int(tid) not in [1000, 1001]:
                u = User.objects(hunter_id=int(tid)).first()
                if u: u.delete(); flash('تم طمس اللاعب نهائياً!', 'success')
        
        elif act == 'bulk_action':
            bt = request.form.get('bulk_type')
            selected_ids = request.form.getlist('selected_users')
            for uid in selected_ids:
                u = User.objects(id=ObjectId(uid)).first()
                if u and u.hunter_id not in [1000, 1001]:
                    if bt == 'hard_delete': u.delete()
                    elif bt == 'activate': u.update(set__status='active', set__health=100)
                    elif bt == 'eliminate': u.update(set__status='eliminated', set__freeze_reason='قرار إداري')
                    elif bt == 'move_zone': u.update(set__zone=request.form.get('bulk_zone', 'الطابق الأول'))
            flash('تم تنفيذ الأمر الجماعي!', 'success')
            
        elif act == 'toggle_sys_mode':
            mode = request.form.get('sys_mode_type')
            if settings.sleep_mode_active:
                wake_up_maze(settings, datetime.utcnow())
                flash('استيقظت المتاهة وزُيح الزمن للعدل.', 'success')
            elif mode == 'sleep':
                GlobalSettings.objects(setting_name='main_config').update_one(set__sleep_mode_active=True, set__sleep_start_time=datetime.utcnow(), set__scheduled_sleep_start=request.form.get('scheduled_sleep_start',''), set__scheduled_sleep_end=request.form.get('scheduled_sleep_end',''))
                flash('المتاهة في سبات! الزمن متوقف.', 'success')
            elif mode == 'maintenance':
                GlobalSettings.objects(setting_name='main_config').update_one(set__maintenance_mode=True, set__maintenance_pages=[request.form.get('maint_page', 'all')], set__maintenance_until=datetime.utcnow() + timedelta(hours=int(request.form.get('maint_hours', 1))))
                flash('دخلت المتاهة في وضع الصيانة.', 'success')
                
        elif act == 'toggle_gates':
            if getattr(settings, 'gates_mode_active', False):
                GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=False)
                User.objects(status='active', hunter_id__nin=[1000, 1001]).update(set__chosen_gate=0, set__gate_status='')
                flash('تم إغلاق البوابات وتصفير الاختيارات.', 'success')
            else:
                gh = int(request.form.get('gates_hours') or 0)
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__gates_mode_active=True, 
                    set__gates_end_time=datetime.utcnow() + timedelta(hours=gh) if gh > 0 else None,
                    set__gates_description=request.form.get('desc', ''), set__gate_1_name=request.form.get('g1', ''), set__gate_2_name=request.form.get('g2', ''), set__gate_3_name=request.form.get('g3', '')
                )
                flash('فُتحت البوابات!', 'success')
                
        elif act == 'execute_gates_fate':
            gn = int(request.form.get('target_gate') or 0)
            fate = request.form.get('fate_decision')
            User.objects(status='active', chosen_gate=gn).update(set__gate_status=f'hidden_{fate}')
            flash(f'سُجل المصير السري للبوابة {gn}.', 'success')
            
        elif act == 'toggle_floor1':
            if getattr(settings, 'floor1_mode_active', False):
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor1_mode_active=False, set__f1_active_meetings={})
                User.objects.update(set__f1_tasks=[], set__current_room='ساحة التجمع', set__group_id=0, set__is_cursed=False, set__gems_collected=0, set__used_vent=False, set__used_lights=False, set__used_doors=False)
                flash('أُوقف الطابق الأول وصُفرت اللعنات.', 'success')
            else:
                active_users = list(User.objects(status='active', hunter_id__nin=[1000, 1001]))
                random.shuffle(active_users)
                gs = int(request.form.get('group_size', 5))
                group_id = 1
                for i in range(0, len(active_users), gs):
                    members = active_users[i:i + gs]
                    if members:
                        cursed_idx = random.randint(0, len(members) - 1)
                        for j, m in enumerate(members): 
                            assign_tasks_to_player(m)
                            m.update(set__group_id=group_id, set__is_cursed=(j == cursed_idx), set__current_room='ساحة التجمع', set__f1_has_voted=False, set__f1_votes_received=0, set__gems_collected=0, set__used_vent=False, set__used_lights=False, set__used_doors=False, set__f1_last_move=None)
                        group_id += 1
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor1_mode_active=True, set__floor1_move_cooldown=int(request.form.get('move_cooldown', 30)), set__floor1_kill_cooldown=int(request.form.get('kill_cooldown', 60)), set__floor1_individual_gems_target=int(request.form.get('gems_target', 3)), set__f1_cursed_win_percent=int(request.form.get('f1_cursed_win_percent', 50)), set__f1_active_meetings={})
                flash('بدأ الاستنتاج ووُزعت اللعنات!', 'success')
                
        elif act == 'toggle_war':
            ns = not getattr(settings, 'war_mode', False)
            wh = int(request.form.get('war_hours') or 0)
            GlobalSettings.objects(setting_name='main_config').update_one(
                set__war_mode=ns, set__war_end_time=datetime.utcnow() + timedelta(hours=wh) if wh > 0 and ns else None,
                set__war_kill_target=int(request.form.get('war_kill_target') or 15) if ns else settings.war_kill_target,
                set__bleed_rate_minutes=int(request.form.get('bleed_rate_minutes') or 60) if ns else settings.bleed_rate_minutes,
                set__bleed_amount=int(request.form.get('bleed_amount') or 1) if ns else settings.bleed_amount,
                set__attack_cooldown_minutes=int(request.form.get('attack_cooldown_minutes') or 5) if ns else settings.attack_cooldown_minutes,
                set__last_global_bleed=datetime.utcnow() if ns else settings.last_global_bleed
            )
            if not ns: User.objects(status='active', hunter_id__nin=[1000, 1001]).update(set__health=100)
            flash('تغيرت حالة الحرب الشاملة!', 'success')
            
        elif act == 'toggle_floor3':
            if getattr(settings, 'floor3_mode_active', False):
                tl = (settings.vote_end_time - datetime.utcnow()).total_seconds() if settings.vote_end_time else 0
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=False, set__floor3_paused=True, set__floor3_time_left=max(0, int(tl)))
                flash('جُمدت المحكمة!', 'success')
            elif getattr(settings, 'floor3_paused', False):
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=True, set__floor3_paused=False, set__vote_end_time=datetime.utcnow() + timedelta(seconds=settings.floor3_time_left))
                flash('اسْتُؤنفت المحكمة!', 'success')
            else:
                vh = int(request.form.get('vote_hours') or 0)
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=True, set__floor3_results_active=False, set__vote_end_time=datetime.utcnow() + timedelta(hours=vh) if vh > 0 else None, set__vote_top_n=int(request.form.get('top_n', 5)))
                flash('بدأت المحكمة الكبرى!', 'success')
                
        elif act == 'toggle_final_battle': 
            ns = not getattr(settings, 'final_battle_mode', False)
            if ns:
                ehp = int(request.form.get('emperor_hp') or 100000)
                User.objects(hunter_id=1000).update(set__health=ehp)
                GlobalSettings.objects(setting_name='main_config').update_one(set__emperor_max_hp=ehp)
            GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=ns)
            flash('تغيرت حالة المعركة الأخيرة!', 'success')
            
        elif act == 'update_home_settings':
            GlobalSettings.objects(setting_name='main_config').update_one(set__home_title=request.form.get('home_title', 'البوابة'), set__global_news_active=bool(request.form.get('global_news_active')), set__global_news_text=request.form.get('global_news_text', ''))
            f = request.files.get('banner_file')
            if f and f.filename != '': 
                GlobalSettings.objects(setting_name='main_config').update_one(set__banner_url=f"data:{f.content_type};base64,{base64.b64encode(compress_image(f.read())).decode('utf-8')}")
            flash('تم تحديث الواجهة!', 'success')
            
        elif act == 'add_store_item':
            StoreItem(name=request.form.get('name'), description=request.form.get('desc', ''), price=int(request.form.get('price', 0)), item_type=request.form.get('item_type', 'weapon'), effect_amount=int(request.form.get('effect_amount', 0)), is_mirage=bool(request.form.get('is_mirage')), mirage_message=request.form.get('mirage_msg', ''), is_luck=bool(request.form.get('is_luck')), luck_min=int(request.form.get('luck_min', 0)), luck_max=int(request.form.get('luck_max', 0))).save()
            flash('تم زرع الأداة في السوق!', 'success')
            
        elif act == 'add_standalone_puzzle':
            cat = request.form.get('trap_category')
            ans = request.form.get('puzzle_answer')
            News(title="كيان", content="خفي", category='hidden', puzzle_type=f"{cat}_{request.form.get('trap_effect')}", puzzle_answer=ans, reward_points=int(request.form.get('reward_points') or 0), trap_penalty_points=int(request.form.get('trap_penalty') or 0), reward_item=request.form.get('reward_item', ''), trap_duration_minutes=int(request.form.get('trap_duration') or 0), max_winners=int(request.form.get('max_winners') or 1)).save()
            if cat == 'ghost': User(hunter_id=int(ans), username=f"شبح_{ans}", password_hash="dummy", role='ghost', status='active').save()
            flash('زرع الكيان المخفي نجح!', 'success')
            
        elif act == 'add_spell':
            SpellConfig(spell_word=request.form.get('spell_word', '').strip(), spell_type=request.form.get('spell_type', ''), effect_value=int(request.form.get('effect_value') or 0), item_name=request.form.get('item_name', ''), max_uses=int(request.form.get('max_uses') or 1), expires_at=datetime.utcnow() + timedelta(hours=int(request.form.get('spell_hours') or 24)) if request.form.get('spell_hours') else None).save()
            flash('نُقشت التعويذة في المذبح!', 'success')
            
        elif act == 'update_poneglyph':
            GlobalSettings.objects(setting_name='main_config').update_one(set__poneglyph_text=request.form.get('poneglyph_text', ''))
            flash('نُقش البونغليف!', 'success')

        return redirect(url_for('admin_panel'))
    
    users_query = User.objects(hunter_id__nin=[1000, 1001])
    search_query = request.args.get('search_user', '').strip() 
    if search_query:
        if search_query.isdigit(): users_query = users_query.filter(hunter_id=int(search_query))
        else: users_query = users_query.filter(username__icontains=search_query)

    stats = {'total': users_query.count(), 'alive': users_query.filter(status='active').count(), 'dead': users_query.filter(status__in=['eliminated', 'dead_body']).count(), 'points': User.objects.sum('points') or 0}
    gate_counts = {1: User.objects(status='active', chosen_gate=1).count(), 2: User.objects(status='active', chosen_gate=2).count(), 3: User.objects(status='active', chosen_gate=3).count()}
    
    return render_template('admin.html', users=users_query.order_by('-last_active')[:100], settings=settings, search_query=search_query, hidden_traps=News.objects(category='hidden'), all_news=News.objects(category__in=['news', 'puzzle', 'declaration']).order_by('-created_at'), spells=SpellConfig.objects().order_by('-created_at'), stats=stats, gate_counts=gate_counts)

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
            elif action == 'reset_avatar': target_user.update(set__avatar='')
            flash('تم التعديل الإمبراطوري!', 'success')
        except: flash('حدث خطأ في الإدخال', 'error')
    return redirect(request.referrer)

# ==========================================
# 🖼️ نظام الصور والألقاب والتشغيل
# ==========================================
@app.route('/avatar/<int:hunter_id>')
def get_avatar(hunter_id):
    u = User.objects(hunter_id=hunter_id).first()
    if u and getattr(u, 'avatar', ''):
        try:
            header, encoded = u.avatar.split(",", 1)
            return Response(base64.b64decode(encoded), mimetype=header.split(';')[0].split(':')[1])
        except: pass
    default_svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#d4af37"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>'''
    return Response(default_svg, mimetype='image/svg+xml')

@app.route('/set_title', methods=['POST'])
@login_required
def set_title():
    title = request.form.get('title', '')
    if title in getattr(g.user, 'achievements', []) or title == '':
        g.user.update(set__special_rank=title)
        flash('تم تثبيت اللقب المعروض!', 'success')
    return redirect(url_for('profile'))

@app.errorhandler(Exception)
def handle_exception(e):
    if "404" in str(e): return f"<div style='direction:rtl; text-align:center; padding:50px; background:#000; color:#fff;'><h2>الصفحة غير موجودة!</h2><a href='/' style='color:#d4af37;'>العودة</a></div>", 404
    return f"<div style='direction:ltr; background:#0a0a0a; color:#ff5555; padding:20px; text-align:left;'><h2>🚨 خطأ برمجي</h2><pre>{traceback.format_exc()}</pre></div>", 200

if __name__ == '__main__': 
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
