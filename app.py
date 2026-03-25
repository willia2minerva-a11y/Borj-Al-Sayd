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

# ==================== إعدادات قاعدة البيانات ====================
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
    # 'auto_create_index' تم إزالته لأنه ليس خيار اتصال صالح
}

app.config['SECRET_KEY'] = 'sephar-maze-emperor-v12-final'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

db.init_app(app)

# تأكد من وجود GlobalSettings
try:
    with app.app_context():
        if not GlobalSettings.objects(setting_name='main_config').first():
            GlobalSettings(setting_name='main_config').save()
    print("✅ Database ready")
except Exception as e:
    print(f"⚠️ DB initialization: {e}")

# ==================== ذاكرة تخزين الإعدادات ====================
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

# ==================== دوال مساعدة ====================
def check_achievements(user):
    try:
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
    except Exception as e:
        app.logger.error(f"check_achievements error: {e}")

def check_lazy_death_and_bleed(user, settings):
    if not user or user.role == 'admin' or user.status != 'active':
        return
    try:
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
    except Exception as e:
        app.logger.error(f"check_lazy_death_and_bleed error: {e}")

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

# ==================== قبل كل طلب ====================
@app.before_request
def fast_health_check():
    if request.method == 'HEAD' or request.path == '/health':
        return "OK", 200

@app.before_request
def pre_process():
    # استثناء الصفحات العامة لمنع الحلقات
    if request.endpoint in ['static', 'get_avatar', 'fast_health_check', 'login', 'register', 'logout']:
        return

    try:
        g.settings = get_cached_settings()
    except Exception as e:
        app.logger.error(f"Settings fetch error: {e}")
        return f"""
        <div style='direction:rtl; background:#0a0a0a; color:#e74c3c; padding:30px; text-align:center;'>
            <h1>🚨 مشكلة في الاتصال بقاعدة البيانات</h1>
            <p>يرجى تحديث الصفحة بعد بضع ثوانٍ.</p>
            <p style='font-family:monospace; direction:ltr;'>{str(e)}</p>
        </div>""", 503

    settings = g.settings
    now = datetime.utcnow()

    # معالجة انتهاء الحرب والبوابات والطابق الثالث
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

    # صيانة الموقع
    if settings.maintenance_mode:
        m_until = settings.maintenance_until
        if m_until and now > m_until:
            GlobalSettings.objects(setting_name='main_config').update_one(set__maintenance_mode=False, set__maintenance_pages=[])
            _settings_cache['timestamp'] = 0
        elif 'user_id' not in session or not User.objects(id=session['user_id']).first() or User.objects(id=session['user_id']).first().role != 'admin':
            m_pages = settings.maintenance_pages or []
            if 'all' in m_pages or request.endpoint in m_pages:
                return render_template('locked.html', message='المتاهة قيد الصيانة ⏳')

    # معالجة المستخدم
    user = None
    if 'user_id' in session:
        try:
            user = User.objects(id=session['user_id']).only(
                'id', 'username', 'role', 'status', 'health', 'points', 'loyalty_points',
                'intelligence_points', 'zone', 'special_rank', 'avatar', 'inventory',
                'friends', 'friend_requests', 'achievements', 'created_at', 'last_active',
                'last_action_time', 'last_health_check', 'freeze_reason', 'chosen_gate',
                'gate_status', 'survival_votes', 'has_voted', 'quicksand_lock_until',
                'tajis_eye_until', 'unlocked_lore_room', 'unlocked_top_room',
                'stats_ghosts_caught', 'stats_puzzles_solved', 'stats_items_bought',
                'destroyed_seals', 'gate_test_answer', 'last_name_change',
                'last_password_change', 'last_seen_news', 'last_seen_decs',
                'last_seen_store', 'last_seen_puzzles', 'facebook_link',
                'secret_achievements', 'has_shield', 'totem_self'
            ).first()
        except Exception as e:
            app.logger.error(f"User fetch error: {e}")
            session.clear()
            return redirect(url_for('login'))

        if not user:
            session.clear()
            return redirect(url_for('login'))

        # ========== إصلاح hunter_id = None (للمستخدمين القدامى) ==========
        if user.hunter_id is None:
            existing_ids = [u.hunter_id for u in User.objects.only('hunter_id').order_by('hunter_id') if u.hunter_id is not None]
            new_id = 1000
            for eid in existing_ids:
                if eid == new_id:
                    new_id += 1
                elif eid > new_id:
                    break
            User.objects(id=user.id).update(set__hunter_id=new_id)
            user = User.objects(id=session['user_id']).first()
            if user:
                flash('تم تحديث هويتك تلقائياً.', 'info')
                return redirect(request.path)

        # تحديث آخر نشاط
        if not user.last_active or (now - user.last_active).total_seconds() > 3600:
            user.update(set__last_active=now)

        check_lazy_death_and_bleed(user, settings)

        # حرق التوتم والوشاح عند دخول الطابق الثالث
        if user.zone == 'الطابق 3' or user.zone == 'المعركة الأخيرة':
            if user.totem_self:
                user.totem_self = False
                user.save()
                flash('🔥 احترق توتم إعادة الحياة بفعل قوى الطابق الثالث!', 'error')
            if user.has_shield:
                user.has_shield = False
                user.save()
                flash('🛡️ احترق وشاح الحماية بفعل قوى الطابق الثالث!', 'error')

        if user.quicksand_lock_until and now < user.quicksand_lock_until:
            tl = user.quicksand_lock_until - now
            return render_template('locked.html', message=f'مقيّد في الرمال لـ {tl.seconds // 60}د')

        if user.status == 'frozen':
            return render_template('locked.html', message='روحك مجمدة بأمر الإمبراطور! ❄️')

        if user.gate_status == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']:
            return render_template('gate_test.html', message=getattr(settings, 'gates_test_message', 'الاختبار'), user=user)

    g.user = user

# دوال المصادقة
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not g.user:
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

# ==================== المسارات الأساسية ====================
@app.route('/')
def home():
    try:
        settings = get_cached_settings()
        user = g.user if hasattr(g, 'user') else None
        alive_count = User.objects(status='active', hunter_id__ne=1000).count()
        dead_count = User.objects(status='eliminated', hunter_id__ne=1000).count()
        emperor = User.objects(hunter_id=1000).only('username', 'hunter_id', 'avatar').first()
        test_winner = None
        if user and user.role == 'admin' and request.args.get('test_victory') and request.args.get('test_victory').isdigit():
            test_winner = User.objects(hunter_id=int(request.args.get('test_victory'))).first()
        return render_template('index.html', alive_count=alive_count, dead_count=dead_count, emperor=emperor, test_winner=test_winner)
    except Exception as e:
        app.logger.error(f"Home error: {traceback.format_exc()}")
        return "حدث خطأ في الصفحة الرئيسية", 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    try:
        if request.method == 'POST':
            if User.objects(username=request.form['username']).first():
                flash('الاسم مستخدم مسبقاً.', 'error')
                return redirect(url_for('register'))
            existing_ids = [u.hunter_id for u in User.objects.only('hunter_id').order_by('hunter_id') if u.hunter_id is not None]
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
    except Exception as e:
        app.logger.error(f"Register error: {traceback.format_exc()}")
        return "حدث خطأ أثناء التسجيل", 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
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
    except Exception as e:
        app.logger.error(f"Login error: {traceback.format_exc()}")
        return "حدث خطأ أثناء تسجيل الدخول", 500

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
        try:
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
        except Exception as e:
            app.logger.error(f"Notifications error: {e}")
    def_avatar = "data:image/svg+xml;base64," + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#14100c"/><circle cx="50" cy="35" r="20" fill="#d4af37"/><path d="M20 90c0-20 15-35 30-35s30 15 30 35" fill="#d4af37"/></svg>').decode('utf-8')
    return {**notifs, 'default_avatar': def_avatar}

# ==================== الملف الشخصي والإعدادات ====================
@app.route('/profile')
@login_required
def profile():
    try:
        user = g.user
        my_items = StoreItem.objects(name__in=user.inventory or [])
        return render_template('profile.html', user=user, my_items=my_items, my_seals=[i for i in my_items if i.item_type == 'seal'])
    except Exception as e:
        app.logger.error(f"Profile error: {traceback.format_exc()}")
        return "حدث خطأ في صفحة الملف الشخصي", 500

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
                if len(data) > app.config['MAX_CONTENT_LENGTH']:
                    flash('حجم الصورة كبير جداً.', 'error')
                else:
                    user.avatar = f"data:{file.content_type};base64,{base64.b64encode(data).decode('utf-8')}"
                    flash('تم تحديث النقش!', 'success')
        elif action == 'change_name':
            new_name = request.form.get('new_name')
            if user.last_name_change and (now - user.last_name_change).days < 15:
                flash('كل 15 يوماً فقط!', 'error')
            elif User.objects(username=new_name).first():
                flash('الاسم مستخدم مسبقاً!', 'error')
            else:
                user.username = new_name
                user.last_name_change = now
                flash('تم التغيير!', 'success')
        elif action == 'change_password':
            old_pw = request.form.get('old_password', '')
            new_pw = request.form.get('new_password', '')
            confirm_pw = request.form.get('confirm_password', '')
            if user.last_password_change and (now - user.last_password_change).days < 1:
                flash('مرة كل 24 ساعة!', 'error')
            elif not check_password_hash(user.password_hash, old_pw):
                flash('الكلمة القديمة خاطئة!', 'error')
            elif new_pw != confirm_pw:
                flash('غير متطابقتين!', 'error')
            else:
                user.password_hash = generate_password_hash(new_pw)
                user.last_password_change = now
                flash('تم التغيير!', 'success')
        user.save()
    except Exception as e:
        app.logger.error(f"Settings error: {e}")
        flash('حدث خطأ أثناء حفظ الإعدادات', 'error')
    return redirect(url_for('profile'))

# ==================== ملفات اللاعبين ====================
@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    try:
        target_user = User.objects(hunter_id=target_id).first()
        if not target_user or target_user.role in ['ghost', 'cursed_ghost']:
            return redirect(url_for('home'))
        settings = get_cached_settings()
        check_lazy_death_and_bleed(target_user, settings)
        current_user = g.user
        my_items = StoreItem.objects(name__in=current_user.inventory or [])
        return render_template('hunter_profile.html',
                               target_user=target_user,
                               my_weapons=[i for i in my_items if i.item_type == 'weapon'],
                               my_heals=[i for i in my_items if i.item_type == 'heal'],
                               my_spies=[i for i in my_items if i.item_type == 'spy'],
                               my_steals=[i for i in my_items if i.item_type == 'steal'])
    except Exception as e:
        app.logger.error(f"Hunter profile error: {traceback.format_exc()}")
        return "حدث خطأ في عرض الملف", 500

@app.route('/admin_update_profile/<int:target_id>', methods=['POST'])
@admin_required
def admin_update_profile(target_id):
    try:
        target_user = User.objects(hunter_id=target_id).first()
        if target_user:
            action = request.form.get('action')
            if action == 'edit_name':
                target_user.username = request.form.get('new_name')
            elif action == 'edit_points':
                target_user.points = int(request.form.get('new_points') or 0)
            elif action == 'edit_hp':
                target_user.health = int(request.form.get('new_hp') or 0)
                if target_user.health <= 0:
                    target_user.health = 0
                    target_user.status = 'eliminated'
                elif target_user.status == 'eliminated':
                    target_user.status = 'active'
            elif action == 'edit_details':
                target_user.zone = request.form.get('zone', '')
                target_user.special_rank = request.form.get('special_rank', '')
            target_user.save()
            flash('تم التعديل الإمبراطوري!', 'success')
    except Exception as e:
        app.logger.error(f"Admin update profile error: {e}")
        flash('خطأ في التعديل', 'error')
    return redirect(url_for('hunter_profile', target_id=target_id))

@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    try:
        sender = g.user
        receiver = User.objects(hunter_id=target_id).first()
        if sender.status != 'active' or not receiver or receiver.status != 'active' or receiver.hunter_id not in sender.friends:
            return redirect(request.referrer or url_for('home'))

        transfer_type = request.form.get('transfer_type')
        if transfer_type == 'points':
            amt = int(request.form.get('amount') or 0)
            if 0 < amt <= sender.points:
                sender.points -= amt
                receiver.points += amt
                sender.loyalty_points += 2
                sender.save()
                receiver.save()
                flash(f'تم إرسال {amt} دينار إلى {receiver.username}!', 'success')
        elif transfer_type == 'item':
            itm = request.form.get('item_name')
            if itm in sender.inventory:
                sender.inventory.remove(itm)
                receiver.inventory.append(itm)
                sender.loyalty_points += 5
                sender.save()
                receiver.save()
                flash(f'تم إرسال {itm} إلى {receiver.username}!', 'success')
    except Exception as e:
        app.logger.error(f"Transfer error: {e}")
        flash('حدث خطأ أثناء الإرسال', 'error')
    return redirect(request.referrer or url_for('home'))

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    try:
        attacker = g.user
        if attacker.status != 'active':
            return redirect(request.referrer or url_for('home'))
        target = User.objects(hunter_id=target_id).first()
        settings = get_cached_settings()
        item_name = request.form.get('item_name')
        item = StoreItem.objects(name=item_name).first()
        if not item or item_name not in attacker.inventory or target.status != 'active':
            return redirect(request.referrer or url_for('home'))

        now = datetime.utcnow()
        item_type = item.item_type

        # ========== الأختام ==========
        if item_type == 'seal':
            if target.id == attacker.id:
                attacker.destroyed_seals = attacker.destroyed_seals + 1
                attacker.inventory.remove(item_name)
                if attacker.destroyed_seals >= 4:
                    settings.war_mode = False
                    settings.final_battle_mode = False
                    settings.save()
                    User.objects(status='active').update(health=100)
                    _settings_cache['timestamp'] = 0
                    flash('دُمرت اللعنة النهائية وانتهت المعركة!', 'success')
                else:
                    flash(f'تم تدمير الختم! ({attacker.destroyed_seals}/4)', 'success')
                attacker.save()
            return redirect(request.referrer or url_for('home'))

        # ========== وشاح الحماية ==========
        if item_type == 'shield':
            if target.id == attacker.id:
                attacker.has_shield = True
                attacker.inventory.remove(item_name)
                attacker.save()
                flash('ارتديت وشاح الحماية! ستحمي من عين سيفار ويد الشبح حتى انكساره.', 'success')
            else:
                flash('يمكنك استخدام الوشاح على نفسك فقط.', 'error')
            return redirect(request.referrer or url_for('home'))

        # ========== توتم إعادة الحياة (لنفسك) ==========
        if item_type == 'totem_self':
            if target.id == attacker.id:
                attacker.totem_self = True
                attacker.inventory.remove(item_name)
                attacker.save()
                flash('التوتم الآن معك! إذا مت، ستعود للحياة مرة واحدة.', 'success')
            else:
                flash('يمكنك استخدام هذا التوتم على نفسك فقط.', 'error')
            return redirect(request.referrer or url_for('home'))

        # ========== توتم إحياء الآخرين ==========
        if item_type == 'totem_other':
            if target.id != attacker.id:
                if target.status == 'eliminated':
                    target.status = 'active'
                    target.health = 50
                    target.freeze_reason = ''
                    attacker.inventory.remove(item_name)
                    target.save()
                    attacker.save()
                    flash(f'لقد أعاد {attacker.username} الحياة إلى {target.username}!', 'success')
                else:
                    flash('الهدف لا يزال على قيد الحياة!', 'error')
            else:
                flash('لا يمكنك استخدام توتم إحياء الآخرين على نفسك.', 'error')
            return redirect(request.referrer or url_for('home'))

        # ========== استخدام السلاح ==========
        is_combat_active = settings.war_mode or settings.final_battle_mode
        if item_type == 'weapon' and is_combat_active and target.hunter_id not in attacker.friends:
            if target.hunter_id == 1000 and settings.war_mode and not settings.final_battle_mode:
                flash('🛡️ الإمبراطور محصن في الحرب الشاملة! لا يمكن استهدافه.', 'error')
                return redirect(request.referrer or url_for('home'))

            has_shield = False
            for inv_item in target.inventory:
                if 'درع' in inv_item or 'shield' in inv_item.lower():
                    target.inventory.remove(inv_item)
                    has_shield = True
                    break
            if has_shield:
                flash('الهدف يمتلك درعاً، لقد انكسر درعه وضاعت ضربتك!', 'error')
            else:
                target.health -= item.effect_amount
                if target.health <= 0:
                    has_totem = getattr(target, 'totem_self', False)
                    if has_totem and not settings.final_battle_mode and not settings.floor3_mode_active:
                        target.health = 50
                        target.totem_self = False
                        flash('استيقظ الهدف من الموت باستخدام توتم الخلود!', 'error')
                    else:
                        target.health = 0
                        target.status = 'eliminated'
                        GlobalSettings.objects(setting_name='main_config').update_inc(dead_count=1)
                        if target.role == 'admin':
                            GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=False, set__war_mode=False)
                            _settings_cache['timestamp'] = 0
                        flash(f'تم القضاء على {target.username}!', 'success')
                else:
                    flash(f'تم إصابة {target.username} وتضرر بـ {item.effect_amount} نقطة صحة!', 'success')
            attacker.inventory.remove(item_name)
            attacker.last_action_time = now
            attacker.save()
            target.save()
            return redirect(request.referrer or url_for('home'))

        # ========== الجرعة العلاجية ==========
        elif item_type == 'heal':
            if target.id == attacker.id or target.hunter_id in attacker.friends:
                heal_amount = item.effect_amount
                if target.role == 'admin':
                    target.health += heal_amount
                else:
                    target.health = min(100, target.health + heal_amount)
                if target.id != attacker.id:
                    attacker.loyalty_points += 5
                target.save()
                attacker.inventory.remove(item_name)
                attacker.last_action_time = now
                attacker.save()
                flash(f'تم شفاء {target.username} بـ {heal_amount} نقطة صحة!', 'success')
            else:
                flash('لا يمكنك علاج غير حلفائك.', 'error')
            return redirect(request.referrer or url_for('home'))

        # ========== عين سيفار (تجسس) ==========
        elif item_type == 'spy':
            if getattr(target, 'has_shield', False):
                attacker.inventory.remove(item_name)
                attacker.save()
                target.has_shield = False
                target.save()
                flash('الهدف يمتلك وشاح حماية! لقد انكسر الوشاح وضاعت عينك.', 'error')
            else:
                attacker.tajis_eye_until = now + timedelta(hours=1)
                attacker.inventory.remove(item_name)
                attacker.save()
                flash('تجسست بنجاح، ملفه مفتوح لك الآن لمدة ساعة!', 'success')
            return redirect(request.referrer or url_for('home'))

        # ========== يد الشبح (سرقة) ==========
        elif item_type == 'steal':
            stolen_item = request.form.get('target_item')
            if stolen_item in target.inventory:
                if getattr(target, 'has_shield', False):
                    attacker.inventory.remove(item_name)
                    attacker.save()
                    target.has_shield = False
                    target.save()
                    flash('الهدف يمتلك وشاح حماية! لقد انكسر الوشاح وضاعت يدك.', 'error')
                else:
                    target.inventory.remove(stolen_item)
                    attacker.inventory.append(stolen_item)
                    attacker.inventory.remove(item_name)
                    attacker.intelligence_points += 5
                    attacker.save()
                    target.save()
                    flash(f'تمت سرقة {stolen_item} من {target.username} بنجاح!', 'success')
            else:
                flash('العنصر غير موجود في حقيبة الهدف.', 'error')
            return redirect(request.referrer or url_for('home'))

        else:
            flash('هذا العنصر لا يمكن استخدامه بهذه الطريقة.', 'error')
            return redirect(request.referrer or url_for('home'))

    except Exception as e:
        app.logger.error(f"Use item error: {traceback.format_exc()}")
        flash('حدث خطأ أثناء استخدام الأداة', 'error')
    return redirect(request.referrer or url_for('home'))

# ==================== المذبح والتعاويذ ====================
@app.route('/altar', methods=['GET', 'POST'])
@login_required
def altar():
    try:
        user = g.user
        if user.status != 'active':
            return redirect(url_for('home'))
        if request.method == 'POST':
            spell_word = request.form.get('spell_word', '').strip()
            spell = SpellConfig.objects(spell_word=spell_word).first()
            settings = get_cached_settings()

            if not spell:
                flash('كلمة لا معنى لها... المذبح صامت.', 'error')
                return redirect(url_for('altar'))

            now = datetime.utcnow()
            if spell.expires_at and now > spell.expires_at:
                flash('لقد تلاشت طاقة هذه التعويذة ومر عليها الزمن!', 'error')
                return redirect(url_for('altar'))

            used_list = spell.used_by or []
            if str(user.id) in used_list:
                flash('لقد استخدمت هذه التعويذة مسبقاً! المذبح لا يستجيب مرتين لنفس الروح.', 'error')
                return redirect(url_for('altar'))
            if spell.max_uses > 0 and len(used_list) >= spell.max_uses:
                flash('لقد استنفدت طاقة هذه التعويذة من قبل رحالة آخرين سبقوك!', 'error')
                return redirect(url_for('altar'))

            stype = spell.spell_type
            val = spell.effect_value
            is_perc = spell.is_percentage

            if stype == 'hp_loss':
                loss = int(user.health * (val / 100.0)) if is_perc else val
                user.health -= loss
                if user.health <= 0:
                    user.health = 0
                    user.status = 'eliminated'
                    user.freeze_reason = 'أحرقته تعويذة'
                flash(f'لقد دفعت ضريبة الدم: {loss} نقطة صحة!', 'error')
            elif stype == 'hp_gain':
                gain = int(user.health * (val / 100.0)) if is_perc else val
                user.health = min(100, user.health + gain)
                flash(f'تم شفاء {gain} نقطة صحة!', 'success')
            elif stype == 'points_loss':
                loss = int(user.points * (val / 100.0)) if is_perc else val
                user.points = max(0, user.points - loss)
                flash(f'فقدت {loss} دينار!', 'error')
            elif stype == 'points_gain':
                user.points += val
                flash(f'مُنحت {val} دنانير من طاقة المذبح!', 'success')
            elif stype == 'item_reward':
                item_name = spell.item_name
                if item_name:
                    user.inventory.append(item_name)
                    flash(f'ظهرت أداة ({item_name}) بين يديك!', 'success')
            elif stype == 'unlock_lore':
                user.unlocked_lore_room = True
                flash('ظهرت نقوش بونغليف سيفار لك الآن.', 'success')
            elif stype == 'unlock_top':
                user.unlocked_top_room = True
                flash('قاعة الأساطير ترحب بك.', 'success')
            elif stype == 'kill_emperor':
                if settings.final_battle_mode:
                    emperor = User.objects(hunter_id=1000).first()
                    if emperor:
                        emperor.health = 0
                        emperor.status = 'eliminated'
                        emperor.save()
                        GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=False, set__war_mode=False)
                        _settings_cache['timestamp'] = 0
                        flash('سقط الإمبراطور! أنت الحاكم الجديد!', 'success')
                else:
                    flash('التعويذة صحيحة، لكن الإمبراطور محصن حالياً.', 'error')
                    return redirect(url_for('altar'))
            else:
                flash('التعويذة غير معروفة للمذبح.', 'error')
                return redirect(url_for('altar'))

            spell.used_by.append(str(user.id))
            spell.save()
            user.save()
            return redirect(url_for('altar'))
        return render_template('altar.html')
    except Exception as e:
        app.logger.error(f"Altar error: {traceback.format_exc()}")
        flash('حدث خطأ في المذبح', 'error')
        return redirect(url_for('home'))

@app.route('/poneglyph')
@login_required
def poneglyph():
    try:
        user = g.user
        if user.status != 'active' or not user.unlocked_lore_room:
            return redirect(url_for('home'))
        settings = get_cached_settings()
        poneglyph_text = settings.poneglyph_text or 'نقوش بونغليف سيفار ممسوحة حالياً...'
        return render_template('poneglyph.html', poneglyph_text=poneglyph_text)
    except Exception as e:
        app.logger.error(f"Poneglyph error: {e}")
        return redirect(url_for('home'))

@app.route('/top_room')
@login_required
def top_room():
    try:
        user = g.user
        if user.status != 'active' or not user.unlocked_top_room:
            return redirect(url_for('home'))
        top_iq = User.objects(hunter_id__ne=1000, status='active').order_by('-intelligence_points')[:10]
        top_loyal = User.objects(hunter_id__ne=1000, status='active').order_by('-loyalty_points')[:10]
        top_hp = User.objects(hunter_id__ne=1000, status='active').order_by('-health')[:10]
        return render_template('top_room.html', top_iq=top_iq, top_loyal=top_loyal, top_hp=top_hp)
    except Exception as e:
        app.logger.error(f"Top room error: {e}")
        return redirect(url_for('home'))

# ==================== الأصدقاء ====================
@app.route('/friends', methods=['GET'])
@login_required
def friends():
    try:
        user = g.user
        search_query = request.args.get('search')
        search_result = None
        if search_query:
            if search_query.isdigit():
                search_result = User.objects(hunter_id=int(search_query)).first()
            else:
                search_result = User.objects(username__icontains=search_query).first()
        friend_requests = User.objects(hunter_id__in=user.friend_requests)
        friends_list = User.objects(hunter_id__in=user.friends)
        return render_template('friends.html', user=user, search_result=search_result, friend_requests=friend_requests, friends=friends_list)
    except Exception as e:
        app.logger.error(f"Friends error: {e}")
        return redirect(url_for('home'))

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    try:
        user = g.user
        if user.status != 'active':
            return redirect(request.referrer or url_for('home'))
        target = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
        if not target or target.status != 'active':
            return redirect(request.referrer or url_for('home'))

        if target.role in ['ghost', 'cursed_ghost']:
            trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target.hunter_id)).first()
            if target.role == 'cursed_ghost' and trap:
                if user.inventory and random.choice([True, False]):
                    stolen_item = random.choice(user.inventory)
                    user.inventory.remove(stolen_item)
                    flash(f'أيقظت شبحاً ملعوناً وسرق منك [{stolen_item}]!', 'error')
                else:
                    loss = trap.trap_penalty_points or 10
                    user.points = max(0, user.points - loss)
                    flash(f'أيقظت شبحاً ملعوناً ونهب منك {loss} دنانير!', 'error')
                user.intelligence_points = max(0, user.intelligence_points - 5)
                user.save()
            elif trap and str(user.id) not in trap.winners_list and trap.current_winners < trap.max_winners:
                user.points += trap.reward_points
                user.stats_ghosts_caught += 1
                trap.current_winners += 1
                trap.winners_list.append(str(user.id))
                user.intelligence_points += 10
                user.save()
                trap.save()
                check_achievements(user)
                flash(f'اصطدت شبحاً وحصلت على {trap.reward_points} دينار!', 'success')
            return redirect(request.referrer or url_for('home'))

        if target.hunter_id not in user.friends and user.hunter_id not in target.friend_requests:
            target.friend_requests.append(user.hunter_id)
            target.save()
            flash('أُرسل طلب التحالف بنجاح', 'success')
    except Exception as e:
        app.logger.error(f"Add friend error: {e}")
        flash('حدث خطأ أثناء إرسال الطلب', 'error')
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    try:
        user = g.user
        target = User.objects(hunter_id=target_id).first()
        if target:
            if user.hunter_id in target.friend_requests:
                target.friend_requests.remove(user.hunter_id)
            elif target.hunter_id in user.friends:
                user.friends.remove(target.hunter_id)
                target.friends.remove(user.hunter_id)
                user.loyalty_points -= 20
            user.save()
            target.save()
            flash('تم الإلغاء', 'success')
    except Exception as e:
        app.logger.error(f"Cancel friend error: {e}")
        flash('حدث خطأ', 'error')
    return redirect(request.referrer or url_for('home'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    try:
        user = g.user
        friend = User.objects(hunter_id=friend_id).first()
        if friend and friend.status == 'active' and friend_id in user.friend_requests:
            user.friend_requests.remove(friend_id)
            user.friends.append(friend_id)
            friend.friends.append(user.hunter_id)
            friend.save()
            user.save()
            check_achievements(user)
            flash('تم قبول التحالف!', 'success')
    except Exception as e:
        app.logger.error(f"Accept friend error: {e}")
        flash('حدث خطأ', 'error')
    return redirect(request.referrer or url_for('home'))

# ==================== الأخبار والألغاز ====================
@app.route('/news')
@login_required
def news():
    try:
        user = g.user
        user.update(set__last_seen_news=datetime.utcnow())
        all_news = News.objects(category='news', status='approved').order_by('-created_at')
        return render_template('news.html', news_list=all_news)
    except Exception as e:
        app.logger.error(f"News error: {e}")
        return redirect(url_for('home'))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    try:
        user = g.user
        if request.method == 'POST':
            if user.status != 'active':
                flash('حسابك يحتاج تفعيل.', 'error')
                return redirect(url_for('puzzles'))

            puzzle_id = request.form.get('puzzle_id')
            puzzle = News.objects(id=puzzle_id).first()
            if not puzzle:
                flash('اللغز غير موجود.', 'error')
                return redirect(url_for('puzzles'))

            if puzzle.puzzle_type in ['text', 'click_count', 'word_order']:
                guess = request.form.get('guess', '').strip()
                if puzzle.puzzle_type == 'click_count':
                    if str(guess) == str(puzzle.puzzle_answer):
                        pass
                    else:
                        flash('عدد الضغطات غير صحيح.', 'error')
                        return redirect(url_for('puzzles'))
                elif puzzle.puzzle_type == 'word_order':
                    if str(guess) == str(puzzle.puzzle_answer):
                        pass
                    else:
                        flash('ترتيب الكلمات غير صحيح.', 'error')
                        return redirect(url_for('puzzles'))
                else:
                    if str(guess) != str(puzzle.puzzle_answer):
                        flash('إجابة خاطئة.', 'error')
                        return redirect(url_for('puzzles'))

                if str(user.id) in puzzle.winners_list:
                    flash('لقد قمت بحل هذا اللغز مسبقاً!', 'error')
                elif puzzle.current_winners >= puzzle.max_winners:
                    flash('نفدت الجوائز!', 'error')
                else:
                    user.points += puzzle.reward_points
                    user.stats_puzzles_solved += 1
                    puzzle.winners_list.append(str(user.id))
                    puzzle.current_winners += 1
                    user.intelligence_points += 10
                    user.save()
                    puzzle.save()
                    check_achievements(user)
                    flash(f'إجابة صحيحة! حصلت على {puzzle.reward_points} دينار!', 'success')
            else:
                flash('نوع اللغز غير مدعوم.', 'error')
            return redirect(url_for('puzzles'))

        user.update(set__last_seen_puzzles=datetime.utcnow())
        all_puzzles = News.objects(category='puzzle', status='approved').order_by('-created_at')
        return render_template('puzzles.html', puzzles_list=all_puzzles)
    except Exception as e:
        app.logger.error(f"Puzzles error: {e}")
        return redirect(url_for('home'))

@app.route('/delete_puzzle/<puzzle_id>', methods=['POST'])
@admin_required
def delete_puzzle(puzzle_id):
    try:
        News.objects(id=puzzle_id).delete()
        flash('تم الحذف!', 'success')
    except Exception as e:
        app.logger.error(f"Delete puzzle error: {e}")
        flash('خطأ في الحذف', 'error')
    return redirect(request.referrer or url_for('puzzles'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    try:
        user = g.user
        if user.status != 'active':
            return redirect(url_for('home'))
        puzzle = News.objects(id=puzzle_id).first()
        if not puzzle:
            return redirect(url_for('home'))

        if puzzle.puzzle_type == 'quicksand_trap':
            user.quicksand_lock_until = datetime.utcnow() + timedelta(minutes=puzzle.trap_duration_minutes or 5)
            user.intelligence_points = max(0, user.intelligence_points - 5)
            user.save()
            flash(f'وقعت في فخ الرمال! لن تستطيع التحرك لمدة {puzzle.trap_duration_minutes} دقائق.', 'error')
        elif puzzle.puzzle_type == 'points_gift':
            if str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
                user.points += puzzle.reward_points
                puzzle.current_winners += 1
                puzzle.winners_list.append(str(user.id))
                user.save()
                puzzle.save()
                flash(f'جائزة! حصلت على {puzzle.reward_points} دينار!', 'success')
            else:
                flash('انتهت الجائزة.', 'error')
        elif puzzle.puzzle_type == 'points_penalty':
            if str(user.id) not in puzzle.winners_list:
                user.points = max(0, user.points - puzzle.trap_penalty_points)
                puzzle.winners_list.append(str(user.id))
                user.save()
                puzzle.save()
                flash(f'لقد سُرقت منك {puzzle.trap_penalty_points} دينار!', 'error')
            else:
                flash('لقد وقعت في هذا الفخ سابقاً.', 'error')
        elif puzzle.puzzle_type == 'freeze_trap':
            user.quicksand_lock_until = datetime.utcnow() + timedelta(minutes=puzzle.trap_duration_minutes or 10)
            user.save()
            flash(f'تم تجميدك! لن تستطيع التحرك لمدة {puzzle.trap_duration_minutes} دقائق.', 'error')
        elif puzzle.puzzle_type == 'item_reward':
            item_name = puzzle.puzzle_answer
            if str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
                user.inventory.append(item_name)
                puzzle.current_winners += 1
                puzzle.winners_list.append(str(user.id))
                user.save()
                puzzle.save()
                flash(f'حصلت على {item_name}!', 'success')
            else:
                flash('انتهت الجائزة.', 'error')
        elif puzzle.puzzle_type == 'seal_reward':
            if str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
                user.inventory.append('ختم سحري')
                puzzle.current_winners += 1
                puzzle.winners_list.append(str(user.id))
                user.save()
                puzzle.save()
                flash('حصلت على ختم سحري!', 'success')
            else:
                flash('انتهت الجائزة.', 'error')
        else:
            if str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
                user.points += puzzle.reward_points
                puzzle.current_winners += 1
                puzzle.winners_list.append(str(user.id))
                user.intelligence_points += 15
                user.save()
                puzzle.save()
                flash(f'جائزة سرية! حصلت على {puzzle.reward_points} دينار!', 'success')
            else:
                flash('انتهت الجائزة.', 'error')
    except Exception as e:
        app.logger.error(f"Secret link error: {e}")
        flash('حدث خطأ', 'error')
    return redirect(request.referrer or url_for('home'))

# ==================== التصريحات ====================
@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    try:
        user = g.user
        if request.method == 'POST':
            if user.status != 'active':
                flash('حسابك قيد المراجعة.', 'error')
                return redirect(url_for('declarations'))
            img = ''
            file = request.files.get('image_file')
            if file:
                img = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            News(
                title=f"تصريح من {user.username}",
                content=request.form.get('content', '').strip(),
                image_data=img,
                category='declaration',
                author=user.username,
                status='approved' if user.role == 'admin' else 'pending'
            ).save()
            flash('تم الإرسال', 'success')
            return redirect(url_for('declarations'))
        user.update(set__last_seen_decs=datetime.utcnow())

        approved_decs = list(News.objects(category='declaration', status='approved').order_by('-created_at'))
        for dec in approved_decs:
            dec.like_list = dec._data.get('likes', []) if isinstance(dec._data, dict) else []
            dec.laugh_list = dec._data.get('laughs', []) if isinstance(dec._data, dict) else []

        pending_decs = News.objects(category='declaration', status='pending') if user.role == 'admin' else []
        my_pending_decs = News.objects(category='declaration', status='pending', author=user.username).order_by('-created_at')
        authors = set([d.author for d in approved_decs] + [d.author for d in pending_decs] + [d.author for d in my_pending_decs])
        users_query = User.objects(username__in=authors).only('username', 'hunter_id')
        avatars = {u.username: u.hunter_id for u in users_query}
        return render_template('declarations.html', approved_decs=approved_decs, pending_decs=pending_decs, my_pending_decs=my_pending_decs, current_user=user, avatars=avatars)
    except Exception as e:
        app.logger.error(f"Declarations error: {e}")
        return redirect(url_for('home'))

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
                if uid in likes:
                    likes.remove(uid)
                else:
                    likes.append(uid)
                    if uid in laughs:
                        laughs.remove(uid)
            elif react_type == 'laugh':
                if uid in laughs:
                    laughs.remove(uid)
                else:
                    laughs.append(uid)
                    if uid in likes:
                        likes.remove(uid)
            coll.update_one({'_id': ObjectId(dec_id)}, {'$set': {'likes': likes, 'laughs': laughs}})
    except Exception as e:
        app.logger.error(f"Reaction error: {e}")
    return redirect(url_for('declarations'))

@app.route('/delete_declaration/<dec_id>', methods=['POST'])
@login_required
def delete_declaration(dec_id):
    try:
        user = g.user
        dec = News.objects(id=dec_id).first()
        if dec and (dec.author == user.username or user.role == 'admin'):
            dec.delete()
            flash('تم الحذف!', 'success')
    except Exception as e:
        app.logger.error(f"Delete declaration error: {e}")
        flash('خطأ في الحذف', 'error')
    return redirect(url_for('declarations'))

# ==================== المتجر ====================
@app.route('/store')
@login_required
def store():
    try:
        user = g.user
        user.update(set__last_seen_store=datetime.utcnow())
        return render_template('store.html', items=StoreItem.objects())
    except Exception as e:
        app.logger.error(f"Store error: {e}")
        return redirect(url_for('home'))

@app.route('/delete_store_item/<item_id>', methods=['POST'])
@admin_required
def delete_store_item(item_id):
    try:
        StoreItem.objects(id=item_id).delete()
        flash('تم حذف المنتج من السوق!', 'success')
    except Exception as e:
        app.logger.error(f"Delete store item error: {e}")
        flash('خطأ في الحذف', 'error')
    return redirect(url_for('store'))

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    try:
        user = g.user
        if user.status != 'active':
            return redirect(url_for('store'))
        item = StoreItem.objects(id=item_id).first()
        if not item:
            return redirect(url_for('store'))
        if user.points >= item.price:
            if item.is_mirage:
                user.points -= item.price
                user.intelligence_points = max(0, user.intelligence_points - 10)
                flash(item.mirage_message or 'لقد اشتريت شيئًا غامضًا... لكنه تبين أنه فخ! فقدت دنانيرك و 10 نقاط ذكاء.', 'error')
            else:
                user.points -= item.price
                if item.is_luck:
                    outcome = random.randint(item.luck_min, item.luck_max)
                    user.points += outcome
                    if outcome >= 0:
                        flash(f'النتيجة من الصندوق: {outcome} دينار!', 'success')
                    else:
                        flash(f'النتيجة من الصندوق: {outcome} دينار (خسارة)!', 'error')
                else:
                    user.inventory.append(item.name)
                    user.stats_items_bought += 1
                    flash(f'تم شراء {item.name} بنجاح!', 'success')
            user.save()
        else:
            flash('دنانيرك لا تكفي!', 'error')
    except Exception as e:
        app.logger.error(f"Buy item error: {e}")
        flash('حدث خطأ أثناء الشراء', 'error')
    return redirect(url_for('store'))

# ==================== المقبرة ====================
@app.route('/graveyard')
def graveyard():
    try:
        users = User.objects(status='eliminated').order_by('-id').only('username', 'hunter_id', 'freeze_reason', 'created_at')
        return render_template('graveyard.html', users=users)
    except Exception as e:
        app.logger.error(f"Graveyard error: {e}")
        return redirect(url_for('home'))

# ==================== البوابات ====================
@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    try:
        user = g.user
        settings = get_cached_settings()
        if user.status != 'active':
            return redirect(url_for('home'))
        if settings.gates_mode_active and not settings.gates_selection_locked and user.chosen_gate == 0:
            gate_num = int(request.form.get('gate_num') or 0)
            user.chosen_gate = gate_num
            user.gate_status = 'waiting'
            user.save()
            flash('تم التسجيل بنجاح في البوابة!', 'success')
    except Exception as e:
        app.logger.error(f"Choose gate error: {e}")
        flash('حدث خطأ', 'error')
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    try:
        user = g.user
        if user.gate_status == 'testing':
            user.gate_test_answer = request.form.get('test_answer', '')
            user.save()
            flash('تم إرسال الإجابة للإمبراطور.', 'success')
    except Exception as e:
        app.logger.error(f"Submit gate test error: {e}")
        flash('حدث خطأ', 'error')
    return redirect(url_for('home'))

@app.route('/submit_floor3_votes', methods=['POST'])
@login_required
def submit_floor3_votes():
    try:
        user = g.user
        if user.hunter_id == 1000 or user.has_voted or user.status != 'active':
            return redirect(url_for('home'))
        tids = [int(request.form.get(f'target_{i}')) for i in range(1, 6)]
        amts = [int(request.form.get(f'amount_{i}')) for i in range(1, 6)]
        if len(set(tids)) == 5 and sum(amts) == 100 and 1000 not in tids and user.hunter_id not in tids:
            for i, tid in enumerate(tids):
                target_user = User.objects(hunter_id=tid).first()
                if target_user:
                    target_user.survival_votes += amts[i]
                    target_user.save()
            user.has_voted = True
            user.save()
            flash('تم تثبيت أصواتك للمحكمة!', 'success')
        else:
            flash('خطأ في التوزيع! اختر 5 أشخاص مختلفين ومجموعهم 100.', 'error')
    except Exception as e:
        app.logger.error(f"Floor3 votes error: {e}")
        flash('حدث خطأ', 'error')
    return redirect(url_for('home'))

# ==================== لوحة المشرف ====================
@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    try:
        settings = get_cached_settings()
        search_query = request.args.get('search_user', '').strip()

        if request.method == 'POST':
            act = request.form.get('action')
            try:
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
                    flash('تم نشر الخبر/اللغز.', 'success')
                elif act == 'add_standalone_puzzle':
                    puzzle_type = request.form.get('puzzle_type')
                    puzzle_answer = request.form.get('puzzle_answer', '')
                    if puzzle_type in ['points_gift', 'points_penalty', 'freeze_trap', 'item_reward', 'seal_reward']:
                        News(
                            title="رابط مخفي",
                            content="خفي",
                            category='hidden',
                            puzzle_type=puzzle_type,
                            puzzle_answer=puzzle_answer,
                            reward_points=int(request.form.get('reward_points') or 0),
                            max_winners=int(request.form.get('max_winners') or 1),
                            trap_duration_minutes=int(request.form.get('trap_duration') or 0),
                            trap_penalty_points=int(request.form.get('trap_penalty') or 0)
                        ).save()
                    elif puzzle_type in ['fake_account', 'cursed_ghost']:
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
                        User(
                            hunter_id=int(puzzle_answer),
                            username=f"شبح_{puzzle_answer}",
                            password_hash="dummy",
                            role='ghost' if puzzle_type == 'fake_account' else 'cursed_ghost',
                            status='active'
                        ).save()
                    else:
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
                    flash('تم إضافة الفخ/الشبح/الرابط.', 'success')
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
                    flash('تم إضافة المنتج للسوق.', 'success')
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
                    flash('تم زرع التعويذة في المذبح بنجاح!', 'success')
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
                    flash('تم تنفيذ الإجراء الجماعي.', 'success')
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
                    flash('تم إصدار أحكام البوابات.', 'success')
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
                    flash('تم الحكم على المتقدم.', 'success')
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
                    flash(f'{"تم فتح التصويت في الطابق الثالث." if new_state else "تم إغلاق التصويت."}', 'success')
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
                    flash('تم نقش البونغليف بنجاح!', 'success')
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
        spells = SpellConfig.objects().order_by('-created_at')

        return render_template('admin.html',
                               users=users,
                               settings=settings,
                               test_users=test_users,
                               gate_stats=gate_stats,
                               floor3_leaders=floor3_leaders,
                               search_query=search_query,
                               store_items=store_items,
                               spells=spells)
    except Exception as e:
        app.logger.error(f"Admin panel error: {traceback.format_exc()}")
        return "حدث خطأ في لوحة التحكم", 500

# ==================== معالج الأخطاء العام ====================
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(traceback.format_exc())
    return f"<div style='direction:ltr; background:#0a0a0a; color:#ff5555; padding:20px; font-family:monospace; border:2px solid red;'><h2>🚨 خطأ في النظام</h2><p>تم تسجيل الخطأ. يرجى المحاولة لاحقاً.</p></div>", 200

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))