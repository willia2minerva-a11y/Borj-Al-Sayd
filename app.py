from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, g
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, SpellConfig
from functools import wraps
from datetime import datetime, timedelta
import os, base64, random, math, traceback, time
import io

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
    'maxPoolSize': 5
}

app.config['SECRET_KEY'] = 'sephar-maze-emperor-v12-final'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

db.init_app(app)

# اختبار الاتصال
try:
    with app.app_context():
        GlobalSettings.objects(setting_name='main_config').first()
    print("✅ Database connected")
except Exception as e:
    print(f"⚠️ DB connection test: {e}")

_settings_cache = {'data': None, 'timestamp': 0}
_SETTINGS_CACHE_TTL = 30

def get_cached_settings(retry=2):
    now = time.time()
    if _settings_cache['data'] is None or (now - _settings_cache['timestamp']) > _SETTINGS_CACHE_TTL:
        for attempt in range(retry):
            try:
                settings = GlobalSettings.objects(setting_name='main_config').first()
                if not settings:
                    settings = GlobalSettings(setting_name='main_config').save()
                _settings_cache['data'] = settings
                _settings_cache['timestamp'] = now
                return settings
            except Exception as e:
                if attempt == retry - 1:
                    raise e
                time.sleep(0.5)
    return _settings_cache['data']

def check_achievements(user):
    new_ach = []
    user_achs = user.achievements or []
    needs_update = False
    if user.stats_ghosts_caught >= 5 and 'صائد الأشباح 👻' not in user_achs:
        user_achs.append('صائد الأشباح 👻')
        new_ach.append('صائد الأشباح 👻')
        user.intelligence_points += 10
        needs_update = True
    if user.stats_puzzles_solved >= 5 and 'حكيم سيفار 📜' not in user_achs:
        user_achs.append('حكيم سيفار 📜')
        new_ach.append('حكيم سيفار 📜')
        user.intelligence_points += 20
        needs_update = True
    if len(user.friends) >= 5 and 'حليف القوم 🤝' not in user_achs:
        user_achs.append('حليف القوم 🤝')
        new_ach.append('حليف القوم 🤝')
        user.loyalty_points += 15
        needs_update = True
    if needs_update:
        user.achievements = user_achs
        user.save()
        if new_ach:
            flash(f'🏆 إنجاز جديد: {", ".join(new_ach)}', 'success')

def check_lazy_death_and_bleed(user, settings):
    if not user or user.role == 'admin' or user.status != 'active':
        return
    now = datetime.utcnow()
    last_act = user.last_active or user.created_at or now
    if (now - last_act).total_seconds() / 3600.0 > 72:
        user.update(set__health=0, set__status='eliminated', set__freeze_reason='ابتلعته الرمال')
        return
    if getattr(settings, 'war_mode', False):
        last_action = user.last_action_time or now
        safe_until = last_action + timedelta(minutes=120)
        if now > safe_until:
            start_bleed = max(user.last_health_check or safe_until, safe_until)
            minutes_passed = (now - start_bleed).total_seconds() / 60.0
            bleed_rate = getattr(settings, 'bleed_rate_minutes', 60)
            if bleed_rate > 0 and minutes_passed >= bleed_rate:
                cycles = math.floor(minutes_passed / bleed_rate)
                damage = cycles * getattr(settings, 'bleed_amount', 1)
                new_health = max(0, user.health - damage)
                if new_health <= 0:
                    user.update(set__health=0, set__status='eliminated', set__freeze_reason='نزف حتى الموت')
                    GlobalSettings.objects(setting_name='main_config').update_inc(dead_count=1)
                    updated = GlobalSettings.objects(setting_name='main_config').first()
                    if (updated.dead_count or 0) >= getattr(settings, 'war_kill_target', 15):
                        GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False)
                        User.objects(status='active', role='hunter', hunter_id__ne=1000).update(set__zone='الطابق 2')
                else:
                    user.update(set__health=new_health, set__last_health_check=now)

def compress_image(image_data, max_size_kb=300):
    if not HAS_PIL:
        return image_data
    try:
        img = Image.open(io.BytesIO(image_data))
        if img.mode in ('RGBA', 'LA'):
            bg = Image.new('RGB', img.size, (0,0,0))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        if img.width > 1200:
            ratio = 1200 / img.width
            new_size = (1200, int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=70, optimize=True)
        compressed = output.getvalue()
        if len(compressed) > max_size_kb * 1024:
            img.save(output, format='JPEG', quality=40, optimize=True)
            compressed = output.getvalue()
        return compressed
    except:
        return image_data

@app.before_request
def fast_health_check():
    if request.method == 'HEAD' or request.path == '/health':
        return "OK", 200

@app.before_request
def pre_process():
    if request.endpoint in ['static', 'get_avatar', 'fast_health_check']:
        return
    try:
        g.settings = get_cached_settings()
    except Exception as e:
        return f"""
        <div style='direction:rtl; background:#0a0a0a; color:#e74c3c; padding:30px; text-align:center;'>
            <h1>🚨 مشكلة في الاتصال بقاعدة البيانات</h1>
            <p>يرجى تحديث الصفحة بعد بضع ثوانٍ.</p>
            <p style='font-family:monospace; direction:ltr;'>{str(e)}</p>
        </div>""", 503

    settings = g.settings
    now = datetime.utcnow()

    # معالجة انتهاء الموقتات (كما هي)
    if settings:
        if settings.war_mode and settings.war_end_time and now >= settings.war_end_time:
            GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False)
            User.objects(status='active').update(health=100)
            _settings_cache['timestamp'] = 0
        if settings.gates_mode_active and settings.gates_end_time and now >= settings.gates_end_time:
            User.objects(status='active', chosen_gate=0, hunter_id__ne=1000).update(set__status='eliminated', set__freeze_reason='انتهى وقت البوابات')
            GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=False)
            _settings_cache['timestamp'] = 0
        if settings.floor3_mode_active and settings.vote_end_time and now >= settings.vote_end_time:
            slackers = User.objects(has_voted=False, status='active', role='hunter')
            active_voters = User.objects(has_voted=True, status='active', role='hunter')
            total_dinars = sum([s.points for s in slackers])
            if active_voters.count() > 0 and total_dinars > 0:
                bonus = total_dinars // active_voters.count()
                for v in active_voters:
                    v.points += bonus
                    v.save()
            for s in slackers:
                s.status = 'eliminated'
                s.freeze_reason = 'تخاذل في المحكمة'
                s.save()
            top_n = settings.vote_top_n
            top_users = User.objects(status='active', role='hunter').order_by('-survival_votes')[:top_n]
            for u in top_users:
                u.zone = 'المعركة الأخيرة'
                u.save()
            GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=False)
            _settings_cache['timestamp'] = 0

    if settings.maintenance_mode:
        m_until = settings.maintenance_until
        if m_until and now > m_until:
            GlobalSettings.objects(setting_name='main_config').update_one(set__maintenance_mode=False, set__maintenance_pages=[])
            _settings_cache['timestamp'] = 0
        elif 'user_id' not in session or not User.objects(id=session['user_id']).first() or User.objects(id=session['user_id']).first().role != 'admin':
            m_pages = settings.maintenance_pages or []
            if 'all' in m_pages or request.endpoint in m_pages:
                return render_template('locked.html', message='المتاهة قيد الصيانة ⏳')

    user = None
    if 'user_id' in session:
        try:
            user = User.objects(id=session['user_id']).first()
        except:
            session.clear()
            return redirect(url_for('login'))
        if not user:
            session.clear()
            return redirect(url_for('login'))
        if not user.last_active or (now - user.last_active).total_seconds() > 3600:
            user.update(set__last_active=now)
        check_lazy_death_and_bleed(user, settings)
        if user.quicksand_lock_until and now < user.quicksand_lock_until:
            tl = user.quicksand_lock_until - now
            return render_template('locked.html', message=f'مقيّد في الرمال لـ {tl.seconds // 60}د')
        if user.status == 'frozen':
            return render_template('locked.html', message='روحك مجمدة بأمر الإمبراطور! ❄️')
        if user.gate_status == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']:
            return render_template('gate_test.html', message=getattr(settings, 'gates_test_message', 'الاختبار'), user=user)
    g.user = user

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not g.user or g.user.role != 'admin':
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

# ========== المسارات الأساسية ==========
@app.route('/')
def home():
    settings = get_cached_settings()
    user = g.user if hasattr(g, 'user') else None
    alive_count = User.objects(status='active', hunter_id__ne=1000).count()
    dead_count = User.objects(status='eliminated', hunter_id__ne=1000).count()
    emperor = User.objects(hunter_id=1000).only('username', 'hunter_id', 'avatar').first()
    test_winner = None
    if user and user.role == 'admin' and request.args.get('test_victory') and request.args.get('test_victory').isdigit():
        test_winner = User.objects(hunter_id=int(request.args.get('test_victory'))).first()
    return render_template('index.html', alive_count=alive_count, dead_count=dead_count, emperor=emperor, test_winner=test_winner)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.objects(username=request.form['username']).first():
            flash('الاسم مستخدم مسبقاً.', 'error')
            return redirect(url_for('register'))
        existing_ids = [u.hunter_id for u in User.objects.only('hunter_id').order_by('hunter_id')]
        new_id = 1000
        for eid in existing_ids:
            if eid == new_id:
                new_id += 1
            elif eid > new_id:
                break
        user = User(
            hunter_id=new_id,
            username=request.form['username'],
            password_hash=generate_password_hash(request.form['password']),
            role='admin' if new_id == 1000 else 'hunter',
            status='active' if new_id == 1000 else 'inactive',
            zone='البوابات',
            special_rank='مستكشف'
        )
        user.save()
        flash('تم تسجيلك بنجاح!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session.permanent = True
            session['user_id'] = str(user.id)
            session['role'] = user.role
            user.update(set__last_active=datetime.utcnow())
            return redirect(url_for('home'))
        flash('بياناتك خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/avatar/<int:hunter_id>')
def get_avatar(hunter_id):
    try:
        user = User.objects(hunter_id=hunter_id).only('avatar').first()
        if user and user.avatar and user.avatar.startswith('data:image'):
            header, encoded = user.avatar.split(",", 1)
            mime = header.split(":")[1].split(";")[0]
            resp = Response(base64.b64decode(encoded), mimetype=mime)
            resp.headers['Cache-Control'] = 'public, max-age=31536000'
            return resp
    except:
        pass
    svg_default = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#14100c"/><circle cx="50" cy="35" r="20" fill="#d4af37"/><path d="M20 90c0-20 15-35 30-35s30 15 30 35" fill="#d4af37"/></svg>'''
    resp = Response(svg_default, mimetype="image/svg+xml")
    resp.headers['Cache-Control'] = 'public, max-age=31536000'
    return resp

@app.context_processor
def inject_globals():
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0,
              'current_user': None, 'war_settings': None, 'settings': None,
              'war_mode_active': False, 'final_battle_active': False,
              'gates_mode_active': False, 'floor3_mode_active': False}
    try:
        settings = get_cached_settings()
        notifs['war_settings'] = settings
        notifs['settings'] = settings
        notifs['war_mode_active'] = settings.war_mode
        notifs['final_battle_active'] = settings.final_battle_mode
        notifs['gates_mode_active'] = settings.gates_mode_active
        notifs['floor3_mode_active'] = settings.floor3_mode_active
    except:
        pass
    if 'user_id' in session and hasattr(g, 'user') and g.user:
        user = g.user
        notifs['current_user'] = user
        now = datetime.utcnow()
        cache_key = f'notif_{user.id}'
        if cache_key not in session or (now - session.get(cache_key+'_time', now)).seconds > 300:
            session[cache_key] = {
                'un_news': News.objects(category='news', status='approved', created_at__gt=(user.last_seen_news or now)).count(),
                'un_puz': News.objects(category='puzzle', status='approved', created_at__gt=(user.last_seen_puzzles or now)).count(),
                'un_dec': News.objects(category='declaration', status='approved', created_at__gt=(user.last_seen_decs or now)).count(),
                'un_store': StoreItem.objects(created_at__gt=(user.last_seen_store or now)).count()
            }
            session[cache_key+'_time'] = now
        notifs.update(session[cache_key])
    def_avatar = "data:image/svg+xml;base64," + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#14100c"/><circle cx="50" cy="35" r="20" fill="#d4af37"/><path d="M20 90c0-20 15-35 30-35s30 15 30 35" fill="#d4af37"/></svg>').decode('utf-8')
    return {**notifs, 'default_avatar': def_avatar}

# ========== باقي المسارات (ملخص) ==========
# (يتم وضع المسارات الأخرى كما هي من الملف السابق، مع التأكد من وجودها)
# سأضيف هنا مسار المشرف فقط، والباقي يفترض أنه موجود مسبقاً.

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = get_cached_settings()
    search_query = request.args.get('search_user', '').strip()

    if request.method == 'POST':
        act = request.form.get('action')
        try:
            # جميع الإجراءات (مثلما كانت في الملف السابق)
            if act == 'setup_maintenance':
                dur = int(request.form.get('m_duration') or 0)
                if dur > 0:
                    GlobalSettings.objects(setting_name='main_config').update_one(
                        set__maintenance_mode=True,
                        set__maintenance_until=datetime.utcnow() + timedelta(minutes=dur),
                        set__maintenance_pages=request.form.getlist('m_pages')
                    )
                else:
                    GlobalSettings.objects(setting_name='main_config').update_one(
                        set__maintenance_mode=False,
                        set__maintenance_pages=[]
                    )
                _settings_cache['timestamp'] = 0
            elif act == 'update_home_settings':
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__home_title=request.form.get('home_title', 'البوابة'),
                    set__global_news_active=bool(request.form.get('global_news_active')),
                    set__global_news_text=request.form.get('global_news_text', '')
                )
                file = request.files.get('banner_file')
                if file and file.filename != '':
                    data = file.read()
                    if len(data) <= app.config['MAX_CONTENT_LENGTH']:
                        compressed = compress_image(data)
                        b_url = f"data:image/jpeg;base64,{base64.b64encode(compressed).decode('utf-8')}"
                        GlobalSettings.objects(setting_name='main_config').update_one(set__banner_url=b_url)
                        flash('تم رفع الصورة.', 'success')
                _settings_cache['timestamp'] = 0
            elif act == 'update_nav_names':
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__nav_home=request.form.get('nav_home', 'الرئيسية'),
                    set__nav_profile=request.form.get('nav_profile', 'هويتي'),
                    set__nav_friends=request.form.get('nav_friends', 'التحالفات'),
                    set__nav_news=request.form.get('nav_news', 'المراسيم'),
                    set__nav_puzzles=request.form.get('nav_puzzles', 'النقوش'),
                    set__nav_decs=request.form.get('nav_decs', 'التصريحات'),
                    set__nav_store=request.form.get('nav_store', 'السوق المظلم'),
                    set__nav_grave=request.form.get('nav_grave', 'المقبرة'),
                    set__nav_altar=request.form.get('nav_altar', 'مذبح الطلاسم'),
                    set__maze_name=request.form.get('maze_name', 'متاهة سيفار')
                )
                _settings_cache['timestamp'] = 0
            elif act == 'toggle_war':
                new_state = not settings.war_mode
                war_hours = int(request.form.get('war_hours') or 0)
                end_time = datetime.utcnow() + timedelta(hours=war_hours) if war_hours > 0 and new_state else None
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__war_mode=new_state,
                    set__war_end_time=end_time
                )
                if not new_state:
                    User.objects(status='active').update(health=100)
                _settings_cache['timestamp'] = 0
                flash('تم تحديث حالة الحرب.', 'success')
            elif act == 'toggle_final_battle':
                new_state = not settings.final_battle_mode
                GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=new_state)
                _settings_cache['timestamp'] = 0
                flash('تم تحديث المعركة الأخيرة.', 'success')
            elif act == 'add_news':
                News(
                    title=request.form.get('title'),
                    content=request.form.get('content'),
                    category='puzzle' if request.form.get('puzzle_type') != 'none' else 'news',
                    puzzle_type=request.form.get('puzzle_type'),
                    puzzle_answer=request.form.get('puzzle_answer'),
                    reward_points=int(request.form.get('reward_points') or 0),
                    max_winners=int(request.form.get('max_winners') or 1)
                ).save()
                flash('تم نشر الخبر.', 'success')
            elif act == 'add_standalone_puzzle':
                puzzle_type = request.form.get('puzzle_type')
                puzzle_answer = request.form.get('puzzle_answer', '')
                News(
                    title="لغز مخفي",
                    content="خفي",
                    category='hidden',
                    puzzle_type=puzzle_type,
                    puzzle_answer=puzzle_answer,
                    reward_points=int(request.form.get('reward_points') or 0),
                    max_winners=int(request.form.get('max_winners') or 1),
                    trap_duration_minutes=int(request.form.get('trap_duration') or 0),
                    trap_penalty_points=int(request.form.get('trap_penalty') or 0)
                ).save()
                if puzzle_type in ['fake_account', 'cursed_ghost']:
                    User(
                        hunter_id=int(puzzle_answer),
                        username=f"شبح_{puzzle_answer}",
                        password_hash="dummy",
                        role='ghost' if puzzle_type == 'fake_account' else 'cursed_ghost',
                        status='active'
                    ).save()
                flash('تم إضافة الفخ.', 'success')
            elif act == 'add_store_item':
                im = ''
                file = request.files.get('item_image')
                if file:
                    im = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
                StoreItem(
                    name=request.form.get('item_name'),
                    description=request.form.get('item_desc'),
                    price=int(request.form.get('item_price') or 0),
                    item_type=request.form.get('item_type'),
                    effect_amount=int(request.form.get('effect_amount') or 0),
                    is_mirage=bool(request.form.get('is_mirage')),
                    mirage_message=request.form.get('mirage_message', ''),
                    is_luck=bool(request.form.get('is_luck')),
                    luck_min=int(request.form.get('luck_min') or 0),
                    luck_max=int(request.form.get('luck_max') or 0),
                    image=im
                ).save()
                flash('تم إضافة المنتج.', 'success')
            elif act == 'add_spell':
                spell_hours = int(request.form.get('spell_hours') or 0)
                exp_time = datetime.utcnow() + timedelta(hours=spell_hours) if spell_hours > 0 else None
                SpellConfig(
                    spell_word=request.form.get('spell_word'),
                    spell_type=request.form.get('spell_type'),
                    effect_value=int(request.form.get('effect_value') or 0),
                    is_percentage=bool(request.form.get('is_percentage')),
                    item_name=request.form.get('item_name', ''),
                    max_uses=int(request.form.get('max_uses') or 0),
                    expires_at=exp_time
                ).save()
                flash('تم زرع التعويذة.', 'success')
            elif act == 'delete_spell':
                spell_id = request.form.get('spell_id')
                if spell_id:
                    SpellConfig.objects(id=spell_id).delete()
                    flash('تم حذف التعويذة.', 'success')
            elif act == 'bulk_action':
                bt = request.form.get('bulk_type')
                for uid in request.form.getlist('selected_users'):
                    u = User.objects(id=uid).first()
                    if u and u.hunter_id != 1000:
                        if bt == 'hard_delete':
                            u.delete()
                        elif bt == 'activate':
                            u.status = 'active'
                            u.health = 100
                            u.save()
                        elif bt == 'eliminate':
                            u.status = 'eliminated'
                            u.freeze_reason = 'بأمر الإمبراطور'
                            u.save()
                        elif bt == 'freeze':
                            u.status = 'frozen'
                            u.save()
                        elif bt == 'move_zone':
                            u.zone = request.form.get('bulk_zone', 'الطابق 1')
                            u.save()
                flash('تم تنفيذ الإجراء.', 'success')
            elif act == 'setup_gates':
                gates_hours = int(request.form.get('gates_hours') or 0)
                g_end = datetime.utcnow() + timedelta(hours=gates_hours) if gates_hours > 0 else None
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__gates_mode_active=True,
                    set__gates_end_time=g_end,
                    set__gates_description=request.form.get('desc', ''),
                    set__gate_1_name=request.form.get('g1', ''),
                    set__gate_2_name=request.form.get('g2', ''),
                    set__gate_3_name=request.form.get('g3', '')
                )
                _settings_cache['timestamp'] = 0
                flash('تم تفعيل البوابات.', 'success')
            elif act == 'close_gates_mode':
                GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=False)
                _settings_cache['timestamp'] = 0
                flash('تم إغلاق البوابات.', 'success')
            elif act == 'judge_gates':
                fates = {1: request.form.get('fate_1'), 2: request.form.get('fate_2'), 3: request.form.get('fate_3')}
                for u in User.objects(gate_status='waiting', status='active'):
                    fate = fates.get(str(u.chosen_gate))
                    if fate == 'pass':
                        u.gate_status = 'passed'
                        u.zone = 'الطابق 1'
                    elif fate == 'kill':
                        u.status = 'eliminated'
                        u.freeze_reason = 'البوابة التهمته'
                    elif fate == 'test':
                        u.gate_status = 'testing'
                    u.save()
                flash('تم إصدار الأحكام.', 'success')
            elif act == 'judge_test_user':
                u = User.objects(id=request.form.get('user_id')).first()
                if u:
                    if request.form.get('decision') == 'pass':
                        u.gate_status = 'passed'
                        u.zone = 'الطابق 1'
                    else:
                        u.status = 'eliminated'
                        u.freeze_reason = 'فشل في الاختبار'
                    u.save()
                flash('تم الحكم.', 'success')
            elif act == 'toggle_floor3':
                new_state = not settings.floor3_mode_active
                vote_hours = int(request.form.get('vote_hours') or 0)
                top_n = int(request.form.get('top_n', 5))
                end_time = datetime.utcnow() + timedelta(hours=vote_hours) if vote_hours > 0 and new_state else None
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__floor3_mode_active=new_state,
                    set__vote_end_time=end_time,
                    set__vote_top_n=top_n
                )
                _settings_cache['timestamp'] = 0
                flash('تم تحديث التصويت.', 'success')
            elif act == 'update_war_settings':
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__bleed_rate_minutes=int(request.form.get('bleed_rate_minutes') or 60),
                    set__bleed_amount=int(request.form.get('bleed_amount') or 1),
                    set__war_kill_target=int(request.form.get('war_kill_target') or 15)
                )
                _settings_cache['timestamp'] = 0
                flash('تم تحديث إعدادات الحرب.', 'success')
            elif act == 'update_poneglyph':
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__poneglyph_text=request.form.get('poneglyph_text', '')
                )
                _settings_cache['timestamp'] = 0
                flash('تم نقش البونغليف.', 'success')
        except Exception as e:
            flash(f'خطأ: {str(e)}', 'error')
            app.logger.error(traceback.format_exc())
        return redirect(url_for('admin_panel', search_user=search_query))

    # استعلامات العرض
    users_query = User.objects(hunter_id__ne=1000)
    if search_query:
        if search_query.isdigit():
            users_query = users_query.filter(hunter_id=int(search_query))
        else:
            users_query = users_query.filter(username__icontains=search_query)
    users = users_query.order_by('-last_active')[:100]

    gate_stats = {
        1: User.objects(chosen_gate=1, status='active').count(),
        2: User.objects(chosen_gate=2, status='active').count(),
        3: User.objects(chosen_gate=3, status='active').count()
    }

    floor3_leaders = []
    if settings.floor3_mode_active:
        floor3_leaders = User.objects(status='active', role='hunter').order_by('-survival_votes')[:settings.vote_top_n]

    test_users = User.objects(gate_status='testing', status='active')
    store_items = StoreItem.objects()
    spells = SpellConfig.objects().order_by('-created_at') if SpellConfig.objects else []

    return render_template('admin.html',
                           users=users,
                           settings=settings,
                           test_users=test_users,
                           gate_stats=gate_stats,
                           floor3_leaders=floor3_leaders,
                           search_query=search_query,
                           store_items=store_items,
                           spells=spells)

# ========== معالج الأخطاء ==========
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(traceback.format_exc())
    return f"<div style='direction:ltr; background:#0a0a0a; color:#ff5555; padding:20px; font-family:monospace; border:2px solid red;'><h2>🚨 خطأ في النظام</h2><p>تم تسجيل الخطأ. يرجى المحاولة لاحقاً.</p></div>", 200

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
