from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, SpellConfig, Notification, GroupMessage
from functools import wraps
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import os
import base64
import random
import math
import time
import traceback

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
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

db.init_app(app)

_settings_cache = {'data': None, 'timestamp': 0}
_SETTINGS_CACHE_TTL = 10  

# ==========================================
# 🛡️ الصلاحيات والمتغيرات العامة
# ==========================================
@app.context_processor
def inject_global_vars():
    """حقن المتغيرات الأساسية في جميع القوالب"""
    return dict(
        current_user=getattr(g, 'user', None), 
        settings=getattr(g, 'settings', None)
    )

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        u = User.objects(id=ObjectId(session['user_id'])).first()
        if not u or u.role != 'admin':
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 🗺️ خرائط ومهام الطابق الأول
# ==========================================
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

TASKS_BY_ROOM = {
    'قاعة العروش': [
        {"name": "إصلاح العرش", "description": "أصلح العرش الملكي"}, 
        {"name": "تنظيف القاعة", "description": "أزل الغبار"}
    ],
    'مكتبة الأسرار': [
        {"name": "فك التشفير", "description": "فك رموز المخطوطة"}, 
        {"name": "ترتيب الرفوف", "description": "رتب الكتب"}
    ],
    'معبد الطلاسم': [
        {"name": "رسم الدائرة", "description": "ارسم دائرة الحماية"}, 
        {"name": "ترتيب التماثيل", "description": "أعد ترتيب التماثيل"}
    ],
    'مخزن الآثار': [
        {"name": "جرد الآثار", "description": "إحصاء القطع"}, 
        {"name": "تنظيف الصناديق", "description": "نظف الصناديق"}
    ],
    'دهليز الأجداد': [
        {"name": "إضاءة المشاعل", "description": "أشعل المشاعل"}, 
        {"name": "إصلاح الجدار", "description": "صلح الشقوق"}
    ],
    'مرصد الأبراج': [
        {"name": "توجيه العدسات", "description": "اضبط العدسات"}, 
        {"name": "تسجيل الأبراج", "description": "دوّن المواقع"}
    ],
    'غرفة البصيرة': [
        {"name": "تأمل البلورة", "description": "تأمل البلورة"}, 
        {"name": "قراءة الطالع", "description": "اقرأ المستقبل"}
    ]
}

def compress_image(image_data, quality=70, max_size=(500, 500)):
    """ضغط الصور قبل رفعها لقاعدة البيانات لتخفيف الضغط"""
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
    except Exception as e:
        print(f"Error compressing image: {e}")
        return image_data

def assign_tasks_to_player(user):
    """توزيع المهام بشكل عشوائي للرحالة في الطابق الأول"""
    all_tasks = [
        {"room": r, "name": t["name"], "description": t["description"], "completed": False} 
        for r, ts in TASKS_BY_ROOM.items() for t in ts
    ]
    user.update(set__f1_tasks=random.sample(all_tasks, min(3, len(all_tasks))))

def execute_trap_effect(user, trap):
    """تنفيذ تأثيرات الفخاخ المخفية في المتاهة"""
    if '_' not in trap.puzzle_type:
        return
        
    eff = trap.puzzle_type.split('_', 1)[1]
    
    if eff == 'give_points':
        user.update(inc__points=trap.reward_points, inc__intelligence_points=10)
        flash(f'نجاح! حصلت على {trap.reward_points} دنانير!', 'success')
        
    elif eff == 'steal_points':
        user.update(set__points=max(0, user.points - trap.trap_penalty_points), dec__intelligence_points=5)
        flash(f'فخ مرعب! سُرق منك {trap.trap_penalty_points} دنانير!', 'error')
        
    elif eff == 'give_item' and trap.reward_item:
        user.update(push__inventory=trap.reward_item)
        flash(f'نجاح! حصلت على الأداة: {trap.reward_item}', 'success')
        
    elif eff == 'steal_item':
        if user.inventory:
            stolen = random.choice(user.inventory)
            user.update(pull__inventory=stolen)
            flash(f'فخ مرعب! سُرقت منك الأداة: {stolen}', 'error')
            
    elif eff == 'give_seal' and trap.reward_item not in user.collected_seals:
        user.update(push__inventory=trap.reward_item)
        flash(f'نجاح أسطوري! حصلت على ختم: {trap.reward_item}', 'success')
        
    elif eff == 'quicksand':
        dur = trap.trap_duration_minutes or 5
        user.update(set__quicksand_lock_until=datetime.utcnow() + timedelta(minutes=dur))
        flash(f'وقعت في فخ الرمال! أنت مجمد لمدة {dur} دقائق.', 'error')

@app.before_request
def fast_health_check():
    """تجاوز الفحص السريع للسيرفر لتجنب الأخطاء"""
    if request.method == 'HEAD' or request.path == '/health':
        return "OK", 200

# ==========================================
# 🩸 المحرك الكوني الشامل (النزيف وتحديثات الأنظمة)
# ==========================================
def check_lazy_death(user, settings):
    """فحص الخمول: من لم يدخل لمدة 3 أيام يموت"""
    try:
        if not user or getattr(user, 'role', '') == 'admin' or getattr(user, 'status', '') not in ['active', 'dead_body']:
            return
            
        if user.hunter_id in [1000, 1001]:
            return
            
        now = datetime.utcnow()
        last_act = getattr(user, 'last_active', None) or getattr(user, 'created_at', None) or now
        
        # الموت بسبب الخمول التام (مثال 72 ساعة)
        if (now - last_act).total_seconds() / 3600.0 > 72: 
            user.update(set__health=0, set__status='eliminated', set__freeze_reason='ابتلعته الرمال بسبب الخمول')
            return
    except Exception as e:
        print(f"Error in lazy check: {e}")

@app.before_request
def pre_process():
    """يتم تنفيذه قبل أي عملية في الموقع لتحديث النزيف والمؤقتات"""
    if request.endpoint in ['static', 'get_avatar', 'fast_health_check', 'login', 'register', 'logout']:
        return
        
    try:
        g.settings = GlobalSettings.objects(setting_name='main_config').first()
    except Exception as e:
        return f"<div style='direction:rtl; background:#0a0a0a; color:#e74c3c; padding:30px; text-align:center;'><h1>🚨 مشكلة اتصال بقاعدة البيانات</h1><p>{str(e)}</p></div>", 503

    settings = g.settings
    now = datetime.utcnow()
    
    if settings:
        # ----------------------------------------------------
        # 1. النزيف التلقائي الشامل لجميع اللاعبين (بأثر رجعي)
        # ----------------------------------------------------
        if settings.war_mode:
            bleed_rate = getattr(settings, 'bleed_rate_minutes', 60)
            bleed_amt = getattr(settings, 'bleed_amount', 1)
            last_global_bleed = getattr(settings, 'last_global_bleed', now)
            
            minutes_passed = (now - last_global_bleed).total_seconds() / 60.0
            if minutes_passed >= bleed_rate and bleed_rate > 0:
                cycles = math.floor(minutes_passed / bleed_rate)
                total_damage = cycles * bleed_amt
                
                # تحديث صحة الجميع في قاعدة البيانات بضربة واحدة
                active_users = User.objects(status='active', hunter_id__nin=[1000, 1001])
                for u in active_users:
                    new_hp = max(0, u.health - total_damage)
                    if new_hp <= 0:
                        u.update(set__health=0, set__status='eliminated', set__freeze_reason='نزف حتى الموت (حرب شاملة)')
                        GlobalSettings.objects(setting_name='main_config').update_one(inc__dead_count=1)
                    else:
                        u.update(set__health=new_hp)
                
                # الاحتفاظ بكسور الوقت لتكون العملية دقيقة تماماً
                time_remainder = minutes_passed % bleed_rate
                GlobalSettings.objects(setting_name='main_config').update_one(set__last_global_bleed=now - timedelta(minutes=time_remainder))

            # إنهاء الحرب تلقائياً
            if settings.war_end_time and now >= settings.war_end_time:
                GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False)

        # ----------------------------------------------------
        # 2. إعدام المتخاذلين في البوابات
        # ----------------------------------------------------
        if settings.gates_mode_active and settings.gates_end_time and now >= settings.gates_end_time:
            lazy_users = User.objects(status='active', chosen_gate=0, hunter_id__nin=[1000, 1001])
            lazy_users.update(set__status='eliminated', set__freeze_reason='تخاذل في اختيار البوابة')
            GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=False)

        # ----------------------------------------------------
        # 3. محرك الطابق الأول (الاجتماعات والمحاكمات)
        # ----------------------------------------------------
        if getattr(settings, 'floor1_mode_active', False):
            meetings = getattr(settings, 'f1_active_meetings', {}).copy()
            meetings_changed = False
            
            for gid_str, minfo in list(meetings.items()):
                group_id = int(gid_str)
                m_end_time = datetime.fromisoformat(minfo['end_time'])
                
                living_members = User.objects(group_id=group_id, status='active')
                total_living = living_members.count()
                voted_count = living_members.filter(f1_has_voted=True).count()
                
                # إنهاء الاجتماع فور تصويت الجميع أو انتهاء الوقت
                if now >= m_end_time or voted_count >= total_living:
                    highest_votes = 0
                    kicked_user = None
                    
                    for m in User.objects(group_id=group_id, status__in=['active', 'dead_body']):
                        if m.f1_votes_received > highest_votes:
                            highest_votes = m.f1_votes_received
                            kicked_user = m
                    
                    if kicked_user and highest_votes > 0:
                        # التحقق من التعادل
                        tie_check = User.objects(group_id=group_id, f1_votes_received=highest_votes).count()
                        if tie_check == 1:
                            kicked_user.update(set__status='eliminated', set__freeze_reason='طُرد بتصويت المجموعة')
                            GroupMessage(group_id=group_id, sender_name="النظام", message=f"⚖️ تم طرد [{kicked_user.username}] بالأغلبية!", is_system_msg=True).save()
                            
                            # نشر وصية المقتول
                            if getattr(kicked_user, 'f1_will', ''):
                                GroupMessage(group_id=group_id, sender_name="النظام", message=f"📜 وصية {kicked_user.username}: {kicked_user.f1_will}", is_system_msg=True).save()
                            
                            # هل طردوا الملعون الحقيقي؟
                            if getattr(kicked_user, 'is_cursed', False):
                                GroupMessage(group_id=group_id, sender_name="النظام", message=f"✨ لقد طردتم الملعون بنجاح! فُتحت البوابة للطابق 2!", is_system_msg=True).save()
                                User.objects(group_id=group_id, status='active').update(set__zone='الطابق 2')
                        else:
                            GroupMessage(group_id=group_id, sender_name="النظام", message="⚖️ تفرقت الآراء (حدث تعادل)... لا إعدام في هذا الاجتماع.", is_system_msg=True).save()
                    
                    del meetings[gid_str]
                    meetings_changed = True
                    User.objects(group_id=group_id).update(set__f1_has_voted=False, set__f1_votes_received=0)
            
            if meetings_changed:
                GlobalSettings.objects(setting_name='main_config').update_one(set__f1_active_meetings=meetings)

            # التحقق من شروط فوز الملعون
            win_percent = getattr(settings, 'f1_cursed_win_percent', 50)
            for gid in User.objects(status='active', group_id__gt=0).distinct('group_id'):
                living = User.objects(group_id=gid, status='active')
                total = living.count()
                if total > 0:
                    cursed = living.filter(is_cursed=True).count()
                    if cursed > 0:
                        percent = (cursed / total) * 100
                        if percent >= win_percent:
                            # قتل البقية وفوز الملعون
                            living.filter(is_cursed=False).update(set__status='eliminated', set__freeze_reason='ذبحهم الملعون')
                            GroupMessage(group_id=gid, sender_name="النظام", message="🔪 لقد انتصر الملعون وسحق الأبرياء! فُتحت له بوابة الدم للطابق الثاني.", is_system_msg=True).save()
                            living.filter(is_cursed=True).update(set__zone='الطابق 2')

        # ----------------------------------------------------
        # 4. محرك الطابق الثالث والتجميد (الصيانة)
        # ----------------------------------------------------
        if settings.floor3_mode_active and not getattr(settings, 'floor3_paused', False) and settings.vote_end_time and now >= settings.vote_end_time:
            slackers = User.objects(has_voted=False, status='active', role='hunter', hunter_id__nin=[1000, 1001])
            slackers.update(set__status='eliminated', set__freeze_reason='تخاذل في المحكمة (ط3)')
            for u in User.objects(status='active', role='hunter', hunter_id__nin=[1000, 1001]).order_by('-survival_votes')[:settings.vote_top_n]: 
                u.update(set__zone='المعركة الأخيرة')
            GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=False, set__floor3_results_active=True)

        if settings.maintenance_mode and settings.maintenance_until and now > settings.maintenance_until:
            GlobalSettings.objects(setting_name='main_config').update_one(set__maintenance_mode=False, set__maintenance_pages=[])
            
        if settings.maintenance_mode:
            if 'user_id' not in session or not User.objects(id=ObjectId(session['user_id'])).first() or User.objects(id=ObjectId(session['user_id'])).first().role != 'admin':
                m_pages = settings.maintenance_pages or []
                if 'all' in m_pages or request.endpoint in m_pages: 
                    return render_template('locked.html', message='المتاهة قيد الصيانة ⏳')

    # ----------------------------------------------------
    # التحقق من جلسة المستخدم الحالي
    # ----------------------------------------------------
    user = None
    if 'user_id' in session:
        try:
            user = User.objects(id=ObjectId(session['user_id'])).first()
        except Exception as e:
            user = None
            
        if not user: 
            session.clear()
            return redirect(url_for('login'))
            
        if not user.last_active or (now - user.last_active).total_seconds() > 1800:
            user.update(set__last_active=now)
            
        check_lazy_death(user, settings)

        # القيود المؤقتة للفخاخ
        if user.status == 'active' and user.quicksand_lock_until and now < user.quicksand_lock_until:
            minutes_left = (user.quicksand_lock_until - now).seconds // 60
            return render_template('locked.html', message=f'مقيّد في الرمال لمدة {minutes_left} دقائق')
            
        if user.gate_status == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']: 
            return render_template('gate_test.html', message=getattr(settings, 'gates_test_message', 'الاختبار'), user=user)

    g.user = user

# ==========================================
# 🏰 الساحة الرئيسية
# ==========================================
@app.route('/')
def home():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    user = getattr(g, 'user', None)
    
    winner_user = None
    if settings and getattr(settings, 'maze_winner_id', 0) > 0:
        winner_user = User.objects(hunter_id=settings.maze_winner_id).first()

    test_winner = None
    if user and user.role == 'admin' and request.args.get('test_victory') and request.args.get('test_victory').isdigit():
        test_winner = User.objects(hunter_id=int(request.args.get('test_victory'))).first()
        
    emperor = User.objects(hunter_id=1000).first()
    
    active_hunters = []
    if settings and settings.floor3_mode_active:
        active_hunters = User.objects(status='active', role='hunter', hunter_id__nin=[1000, 1001], id__ne=user.id if user else None)
        
    room_players = []
    dead_bodies_in_room = []
    adjacent_rooms = []
    is_dark = False
    has_meeting = False
    meeting_info = None
    group_chats = []
    
    if settings and getattr(settings, 'floor1_mode_active', False) and user and user.status == 'active' and user.group_id > 0:
        gid_str = str(user.group_id)
        if gid_str in getattr(settings, 'f1_active_meetings', {}):
            has_meeting = True
            meeting_info = settings.f1_active_meetings[gid_str]
            
        if getattr(settings, 'floor1_darkness_until', None) and datetime.utcnow() < settings.floor1_darkness_until:
            is_dark = True
            
        group_chats = GroupMessage.objects(group_id=user.group_id).order_by('created_at')
        
        if not is_dark:
            room_players = User.objects(group_id=user.group_id, current_room=user.current_room, status='active', id__ne=user.id, hunter_id__nin=[1000, 1001])
            
        dead_bodies_in_room = User.objects(group_id=user.group_id, current_room=user.current_room, status='dead_body')
        adjacent_rooms = F1_MAP.get(getattr(user, 'current_room', 'قاعة العروش'), [])

    f3_users = User.objects(status='active', role='hunter', survival_votes__gt=0, hunter_id__nin=[1000, 1001]).order_by('-survival_votes')
    player_tasks = getattr(user, 'f1_tasks', []) if user else []
    current_room_tasks = [t for t in player_tasks if t.get('room') == user.current_room and not t.get('completed', False)] if user and user.current_room else []
    
    return render_template('index.html', 
        winner_user=winner_user, 
        emperor=emperor, 
        test_winner=test_winner, 
        active_hunters=active_hunters, 
        room_players=room_players, 
        dead_bodies_in_room=dead_bodies_in_room, 
        is_dark=is_dark, 
        adjacent_rooms=adjacent_rooms, 
        has_meeting=has_meeting, 
        meeting_info=meeting_info, 
        group_chats=group_chats,
        f3_users=f3_users, 
        f1_map=F1_MAP, 
        player_tasks=player_tasks, 
        current_room_tasks=current_room_tasks, 
        settings=settings
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
            if user.status == 'inactive':
                flash('حسابك قيد المراجعة. التصفح متاح.', 'info')
            if user.status in ['eliminated', 'frozen', 'dead_body']:
                flash('حسابك موقوف عن اللعب.', 'error')
            return redirect(url_for('home'))
        flash('البيانات خاطئة.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fb_link = request.form.get('facebook_link', '').strip()
        if not fb_link:
            flash('رابط الفيسبوك إلزامي!', 'error')
            return redirect(url_for('register'))
            
        if User.objects(username=request.form['username']).first():
            flash('الاسم مستخدم مسبقاً.', 'error')
            return redirect(url_for('register'))
            
        existing_ids = [u.hunter_id for u in User.objects(hunter_id__lt=1000).only('hunter_id').order_by('hunter_id')]
        new_id = 1
        for eid in existing_ids:
            if eid == new_id:
                new_id += 1
            elif eid > new_id:
                break
                
        User(
            hunter_id=new_id, 
            username=request.form['username'], 
            password_hash=generate_password_hash(request.form['password']), 
            role='hunter', 
            status='inactive', 
            zone='البوابات', 
            special_rank='مستكشف', 
            facebook_link=fb_link
        ).save()
        
        flash('تم التسجيل! حسابك قيد المراجعة.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ==========================================
# 👤 الملف الشخصي واللاعبين الآخرين
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
        flash('حدث خطأ!', 'error')
        print(e)
        
    return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    # حماية بروفايل الإمبراطور ومساعده من الوصول المباشر
    if target_id in [1000, 1001] and g.user.hunter_id not in [1000, 1001]:
        return f"<div style='background:#030202; color:#e74c3c; height:100vh; display:flex; align-items:center; justify-content:center; flex-direction:column; font-family:Courier New; text-align:center; padding:20px; box-shadow: inset 0 0 100px #000;'><h1 style='font-size:50px; margin:0; text-shadow: 0 0 20px #ff0000;'>👁️</h1><h2 style='text-shadow: 0 0 10px #e74c3c;'>هذا الحساب محجوب في طيات الظلام...</h2><p style='color:#aaa; font-size:18px;'>لا تقترب من العرش الإمبراطوري!</p><a href='/' style='color:#b59b4c; margin-top:30px; border:1px solid #b59b4c; padding:10px 30px; text-decoration:none; border-radius:5px;'>العودة للساحة</a></div>", 403
        
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']: 
        return redirect(url_for('home'))
        
    my_items = StoreItem.objects(name__in=getattr(g.user, 'inventory', []) or [])
    fresh_settings = GlobalSettings.objects(setting_name='main_config').first()
    
    my_weapons = [i for i in my_items if getattr(i, 'item_type', '') == 'weapon']
    my_heals = [i for i in my_items if getattr(i, 'item_type', '') == 'heal']
    my_spies = [i for i in my_items if getattr(i, 'item_type', '') == 'spy']
    my_steals = [i for i in my_items if getattr(i, 'item_type', '') == 'steal']
    
    return render_template(
        'hunter_profile.html', 
        target_user=target_user, 
        my_weapons=my_weapons, 
        my_heals=my_heals, 
        my_spies=my_spies, 
        my_steals=my_steals,
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
        # إذا بحث عن الإمبراطور أو مساعده (بالرقم أو الاسم)
        if search_query in ['1000', '1001', 'الإمبراطور', 'مساعد الإمبراطور']:
            flash('👁️ الفضول قد يقتل صاحبه... لا تبحث عن الظلال.', 'error')
            search_result = None
        # إذا بحث برقم ID صالح
        elif search_query.isdigit(): 
            search_result = User.objects(hunter_id=int(search_query)).first()
        # إذا بحث باسم رحالة عادي
        else: 
            search_result = User.objects(username__icontains=search_query, hunter_id__nin=[1000, 1001]).first()
    
    exclude_roles = ['ghost', 'cursed_ghost', 'admin']
    exclude_ids = [g.user.hunter_id, 1000, 1001] + getattr(g.user, 'friends', []) + getattr(g.user, 'friend_requests', [])
    suggested_hunters = User.objects(status='active', role__nin=exclude_roles, hunter_id__nin=exclude_ids).order_by('-last_active')[:30]
    
    friend_requests = User.objects(hunter_id__in=getattr(g.user, 'friend_requests', []))
    friends_list = User.objects(hunter_id__in=getattr(g.user, 'friends', []))
    
    return render_template(
        'friends.html', 
        user=g.user, 
        search_result=search_result, 
        friend_requests=friend_requests, 
        friends=friends_list, 
        suggested_hunters=suggested_hunters
    )

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = g.user
    target_id = int(request.form.get('target_id') or 0)
    target = User.objects(hunter_id=target_id).first()
    
    if user.status != 'active': 
        flash('حسابك موقوف عن اللعب.', 'error')
        return redirect(request.referrer or url_for('home'))
        
    if not target or target.status not in ['active', 'inactive']: 
        return redirect(request.referrer or url_for('home'))
        
    if target.id == user.id or target.hunter_id in [1000, 1001]: 
        flash('لا يمكنك التحالف مع هذا الكيان!', 'error')
        return redirect(request.referrer or url_for('home'))
    
    # حالة خاصة: إذا كان الهدف شبحاً
    if getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_answer=str(target.hunter_id), category='hidden').first()
        if trap and str(user.id) not in getattr(trap, 'winners_list', []) and getattr(trap, 'current_winners', 0) < getattr(trap, 'max_winners', 1):
            if trap.puzzle_type.startswith('ghost_'): 
                execute_trap_effect(user, trap)
                trap.update(inc__current_winners=1, push__winners_list=str(user.id))
        else: 
            flash('اختفى الشبح أو نفدت المكافآت.', 'info')
            
    # الحالة العادية: إرسال طلب
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
    target_id = int(request.form.get('target_id') or 0)
    target = User.objects(hunter_id=target_id).first()
    
    if target and user.hunter_id in getattr(target, 'friend_requests', []): 
        target.update(pull__friend_requests=user.hunter_id)
        user.update(pull__sent_requests=target.hunter_id)
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
        friend.update(push__friends=user.hunter_id, pull__sent_requests=user.hunter_id)
        
    return redirect(request.referrer or url_for('home'))

# ==========================================
# 🎁 الإمدادات واستخدام الأسلحة
# ==========================================
@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    sender = g.user
    receiver = User.objects(hunter_id=target_id).first()
    
    if sender.status != 'active': 
        flash('لا يمكنك التنفيذ.', 'error')
        return redirect(request.referrer or url_for('home'))
        
    if not receiver or receiver.status != 'active':
        flash('الهدف غير متاح.', 'error')
        return redirect(request.referrer or url_for('home'))
        
    # حماية التحالف (لا يمكن الإرسال إلا للحلفاء)
    if receiver.hunter_id not in getattr(sender, 'friends', []): 
        flash('لا يمكنك إرسال إمدادات إلا لمن أقسمت معهم يمين التحالف!', 'error')
        return redirect(request.referrer or url_for('home'))
        
    transfer_type = request.form.get('transfer_type')
    
    if transfer_type == 'points':
        try:
            amt = int(request.form.get('amount') or 0)
            if 0 < amt <= sender.points: 
                sender.update(dec__points=amt, inc__loyalty_points=2)
                receiver.update(inc__points=amt)
                flash(f'تم إرسال {amt} دنانير!', 'success')
            else:
                flash('عدد دنانير غير صالح.', 'error')
        except ValueError:
            pass
            
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
    
    if attacker.status != 'active': 
        flash('حسابك معطل عن اللعب.', 'error')
        return redirect(request.referrer or url_for('home'))
        
    item_name = request.form.get('item_name')
    item = StoreItem.objects(name=item_name).first()
    
    if not item or item_name not in getattr(attacker, 'inventory', []) or not target or target.status != 'active': 
        return redirect(request.referrer or url_for('home'))
        
    now = datetime.utcnow()
    item_type = getattr(item, 'item_type', '')
    
    # التحقق من مؤقت التبريد للهجوم
    if item_type in ['weapon', 'steal', 'spy']:
        cooldown_mins = getattr(settings, 'attack_cooldown_minutes', 0)
        if cooldown_mins > 0 and attacker.last_action_time and (now - attacker.last_action_time).total_seconds() < (cooldown_mins * 60):
            remaining = int((cooldown_mins * 60) - (now - attacker.last_action_time).total_seconds())
            flash(f'الرجاء الانتظار {remaining} ثانية قبل الهجوم مجدداً.', 'error')
            return redirect(request.referrer or url_for('home'))

    # قواعد المعركة الأخيرة
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
                
                # فحص الفوز في المعركة الأخيرة
                if getattr(target, 'role', '') == 'admin': 
                    GlobalSettings.objects(setting_name='main_config').update_one(
                        set__final_battle_mode=False, 
                        set__war_mode=False, 
                        set__maze_winner_id=attacker.hunter_id
                    )
            else: 
                target.update(set__health=new_hp)
            flash('تمت الضربة بنجاح!', 'success')
            
        attacker.update(pull__inventory=item_name, set__last_action_time=now)
        
    elif item_type == 'heal':
        # يمكن علاج نفسه أو حلفائه
        if target.id == attacker.id or target.hunter_id in getattr(attacker, 'friends', []):
            heal_amt = getattr(item, 'effect_amount', 0)
            
            # الإمبراطور يمكنه العلاج بلا سقف 100%
            if getattr(target, 'role', '') == 'admin':
                new_hp = target.health + heal_amt
            else:
                new_hp = min(100, target.health + heal_amt)
                
            target.update(set__health=new_hp)
            
            if target.id != attacker.id: 
                attacker.update(inc__loyalty_points=5)
                
            attacker.update(pull__inventory=item_name, set__last_action_time=now)
            flash('تم العلاج بنجاح!', 'success')
        else:
            flash('لا يمكنك علاج هذا الشخص، فهو ليس حليفاً لك!', 'error')
            
    elif item_type == 'spy':
        if getattr(target, 'has_shield', False): 
            attacker.update(pull__inventory=item_name, set__last_action_time=now)
            flash('الهدف محصن ضد التجسس!', 'error')
        else: 
            attacker.update(set__tajis_eye_until=now + timedelta(hours=1), pull__inventory=item_name, set__last_action_time=now)
            flash('تجسست بنجاح! يمكنك الآن رؤية أسراره.', 'success')
            
    elif item_type == 'steal':
        stolen_item = request.form.get('target_item')
        if stolen_item in getattr(target, 'inventory', []):
            if getattr(target, 'has_shield', False): 
                attacker.update(pull__inventory=item_name, set__last_action_time=now)
                flash('الهدف محمي! انكسر الدرع وضاعت محاولتك.', 'error')
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
                
                # فحص فوز جمع الأختام الأربعة
                if len(attacker.collected_seals) >= 4:
                    if settings: 
                        GlobalSettings.objects(setting_name='main_config').update_one(
                            set__war_mode=False, 
                            set__final_battle_mode=False, 
                            set__maze_winner_id=attacker.hunter_id
                        )
                    # إحياء البقية للفوز بسلام
                    User.objects(status='active', hunter_id__nin=[1000, 1001]).update(set__health=100)
                    flash('🔥 جمعت الأختام الأربعة الفريدة! لقد فزت بالمتاهة!', 'success')
                else: 
                    flash('تم تفعيل الختم ووضعه في سجلك!', 'success')
            else: 
                attacker.update(pull__inventory=item_name)
                flash('لقد فعلت هذا الختم مسبقاً! تبخر بلا فائدة.', 'error')
                
    return redirect(request.referrer or url_for('home'))

# ==========================================
# 📜 المراسيم، النقوش، والتصريحات
# ==========================================
@app.route('/news')
@login_required
def news(): 
    g.user.update(set__last_seen_news=datetime.utcnow())
    news_list = News.objects(category='news', status='approved').order_by('-created_at')
    return render_template('news.html', news_list=news_list)

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
        puzzle_id = request.form.get('puzzle_id')
        puzzle = News.objects(id=puzzle_id).first()
        
        if puzzle and str(guess) == str(getattr(puzzle, 'puzzle_answer', '')) and str(user.id) not in getattr(puzzle, 'winners_list', []):
            if getattr(puzzle, 'current_winners', 0) < getattr(puzzle, 'max_winners', 1):
                user.update(inc__points=getattr(puzzle, 'reward_points', 0), inc__stats_puzzles_solved=1, inc__intelligence_points=10)
                puzzle.update(push__winners_list=str(user.id), inc__current_winners=1)
                flash('إجابة صحيحة!', 'success')
                
                # مكافأة الطابق الأول (حجر كريم)
                if settings and getattr(settings, 'floor1_mode_active', False):
                    user.update(inc__gems_collected=1)
                    Notification(target_hunter_id=user.hunter_id, message='💎 حصلت على حجر كريم من حل اللغز!', notif_type='success').save()
                    
                    total_gems = sum([u.gems_collected for u in User.objects(group_id=user.group_id)])
                    if total_gems >= getattr(settings, 'floor1_gems_target', 10):
                        User.objects(group_id=user.group_id, is_cursed=True).update(set__status='eliminated', set__freeze_reason='احترقت اللعنة بنور الأحجار')
                        GroupMessage(group_id=user.group_id, sender_name="النظام", message="✨ اكتمل النور وفُتحت البوابة للطابق الثاني!", is_system_msg=True).save()
                        User.objects(group_id=user.group_id, status='active').update(set__zone='الطابق 2')
        else: 
            flash('إجابة خاطئة أو أنك حللته مسبقاً!', 'error')
        return redirect(url_for('puzzles'))
        
    puzzles_list = News.objects(category='puzzle', status='approved').order_by('-created_at')
    return render_template('puzzles.html', puzzles_list=puzzles_list)

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = g.user
    if user.status != 'active': 
        return redirect(url_for('home'))
        
    try: 
        puzzle = News.objects(id=puzzle_id).first()
    except: 
        return redirect(url_for('home'))
    
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
        if file and file.filename != '': 
            img_bytes = compress_image(file.read())
            img = f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
            
        News(
            title=f"تصريح من {user.username}", 
            content=request.form.get('content', '').strip(), 
            image_data=img, 
            category='declaration', 
            author=user.username, 
            status='approved' if user.role == 'admin' else 'pending'
        ).save()
        flash('تم النشر! وهو بصدد موافقة عليه. ', 'success')
        return redirect(url_for('declarations'))
        
    user.update(set__last_seen_decs=datetime.utcnow())
    
    approved = News.objects(category='declaration', status='approved').order_by('-created_at')
    pending = News.objects(category='declaration', status='pending') if user.role == 'admin' else []
    my_pending = News.objects(category='declaration', status='pending', author=user.username).order_by('-created_at')
    
    avatars = {u.username: u.hunter_id for u in User.objects(username__in=set([d.author for d in News.objects(category='declaration')]))}
    
    return render_template(
        'declarations.html', 
        approved_decs=approved, 
        pending_decs=pending, 
        my_pending_decs=my_pending, 
        current_user=user, 
        avatars=avatars
    )

@app.route('/react_declaration/<dec_id>/<react_type>', methods=['POST'])
@login_required
def react_declaration(dec_id, react_type):
    try:
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
                    if uid in laughs: laughs.remove(uid)
            elif react_type == 'laugh':
                if uid in laughs: 
                    laughs.remove(uid)
                else: 
                    laughs.append(uid)
                    if uid in likes: likes.remove(uid)
                    
            coll.update_one({'_id': ObjectId(dec_id)}, {'$set': {'likes': likes, 'laughs': laughs}})
    except: 
        pass
    return redirect(url_for('declarations'))

@app.route('/delete_declaration/<dec_id>', methods=['POST'])
@login_required
def delete_declaration(dec_id):
    user = g.user
    try:
        dec = News.objects(id=ObjectId(dec_id)).first()
        # يمكن للأدمن أو لصاحب التصريح حذفه
        if dec and (dec.author == user.username or user.role == 'admin'): 
            dec.delete()
            flash('تم حذف التصريح بنجاح.', 'success')
    except: 
        pass
    return redirect(request.referrer or url_for('declarations'))

# ==========================================
# 🛒 السوق والمقبرة
# ==========================================
@app.route('/store')
@login_required
def store(): 
    g.user.update(set__last_seen_store=datetime.utcnow())
    items = StoreItem.objects()
    return render_template('store.html', items=items)

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    user = g.user
    if user.status != 'active': 
        flash('حسابك موقوف عن الشراء.', 'error')
        return redirect(url_for('store'))
        
    try: 
        item = StoreItem.objects(id=ObjectId(item_id)).first()
    except: 
        return redirect(url_for('store'))
    
    if user and item and user.points >= item.price:
        if getattr(item, 'is_mirage', False): 
            user.update(dec__points=item.price, dec__intelligence_points=10)
            flash(getattr(item, 'mirage_message', 'فخ سراب! خسرت الدنانير و 10 نقاط ذكاء.'), 'error')
        else:
            user.update(dec__points=item.price)
            if getattr(item, 'is_luck', False): 
                outcome = random.randint(getattr(item, 'luck_min', 0), getattr(item, 'luck_max', 0))
                user.update(inc__points=outcome)
                if outcome >= 0:
                    flash(f'صندوق حظ: النتيجة ربح {outcome} دنانير!', 'success')
                else:
                    flash(f'صندوق حظ: النتيجة خسارة {abs(outcome)} دنانير!', 'error')
            else: 
                user.update(push__inventory=item.name, inc__stats_items_bought=1)
                flash(f'تم شراء [{item.name}] بنجاح!', 'success')
    else: 
        flash('دنانيرك لا تكفي!', 'error')
        
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): 
    dead_users = User.objects(status='eliminated', hunter_id__nin=[1000, 1001]).order_by('-id')
    return render_template('graveyard.html', users=dead_users)

@app.route('/delete_store_item/<item_id>', methods=['POST'])
@admin_required
def delete_store_item(item_id):
    try: 
        StoreItem.objects(id=ObjectId(item_id)).delete()
        flash('تم الحذف من السوق!', 'success')
    except: 
        pass
    return redirect(url_for('store'))

@app.route('/delete_puzzle/<puzzle_id>', methods=['POST'])
@admin_required
def delete_puzzle(puzzle_id):
    try: 
        News.objects(id=ObjectId(puzzle_id)).delete()
        flash('تم الحذف!', 'success')
    except: 
        pass
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
                    GlobalSettings.objects(setting_name='main_config').update_one(
                        set__final_battle_mode=False, 
                        set__war_mode=False, 
                        set__maze_winner_id=user.hunter_id
                    )
                    User.objects(status='active', hunter_id__nin=[1000, 1001, user.hunter_id]).update(
                        set__status='eliminated', 
                        set__freeze_reason='سقطوا لانتهاء المتاهة'
                    )
                    flash('نجاح! التعويذة المحرمة.. سقط الإمبراطور.', 'success')
                else: 
                    flash('خطأ! الإمبراطور محصن حالياً في الظلال.', 'error')
                    return redirect(url_for('altar'))
                    
            spell.update(push__used_by=str(user.id))
        except Exception as e: 
            print(f"Altar Error: {e}")
            flash("خطأ في طاقة المذبح.", "error")
            
        return redirect(url_for('altar'))
        
    return render_template('altar.html')

@app.route('/poneglyph')
@login_required
def poneglyph():
    if getattr(g.user, 'role', '') != 'admin' and not getattr(g.user, 'unlocked_lore_room', False): 
        return redirect(url_for('home'))
    
    fresh_settings = GlobalSettings.objects(setting_name='main_config').first()
    return render_template('poneglyph.html', poneglyph_text=getattr(fresh_settings, 'poneglyph_text', ''))

@app.route('/top_room')
@login_required
def top_room():
    if getattr(g.user, 'role', '') != 'admin' and not getattr(g.user, 'unlocked_top_room', False): 
        return redirect(url_for('home'))
        
    top_iq = User.objects(hunter_id__nin=[1000, 1001], status__in=['active', 'inactive']).order_by('-intelligence_points')[:10]
    top_loyal = User.objects(hunter_id__nin=[1000, 1001], status__in=['active', 'inactive']).order_by('-loyalty_points')[:10]
    top_hp = User.objects(hunter_id__nin=[1000, 1001], status__in=['active', 'inactive']).order_by('-health')[:10]
    
    return render_template('top_room.html', top_iq=top_iq, top_loyal=top_loyal, top_hp=top_hp)

# ==========================================
# 🚪 البوابات ومصائرها
# ==========================================
@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    user = g.user
    settings = g.settings
    if user.status != 'active': 
        return redirect(url_for('home'))
    
    if getattr(settings, 'gates_mode_active', False) and getattr(user, 'chosen_gate', 0) == 0: 
        gate_num = int(request.form.get('gate_num') or 0)
        if gate_num in [1, 2, 3]:
            user.update(set__chosen_gate=gate_num, set__gate_status='waiting')
            flash('تم تسجيل اختيارك! انتظر حتى يحدد الإمبراطور مصير هذه البوابة.', 'info')
                
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    if g.user.gate_status == 'testing': 
        g.user.update(set__gate_test_answer=request.form.get('test_answer', ''))
        flash('تم تسليم إجابتك للحارس السري.', 'success')
    return redirect(url_for('home'))

# ==========================================
# 👑 لوحة الإدارة (Admin Panel)
# ==========================================
@app.route('/admin_hard_delete/<int:target_id>', methods=['POST'])
@admin_required
def admin_hard_delete(target_id):
    if target_id in [1000, 1001]:
        flash('مستحيل! لا يمكن مسح الإمبراطور أو مساعده من الوجود!', 'error')
        return redirect(request.referrer)
        
    user = User.objects(hunter_id=target_id).first()
    if user:
        user.delete()
        flash('تم طمس الأثر بنجاح! الـ ID متاح الآن للتسجيل.', 'success')
        return redirect(url_for('admin_panel'))
        
    return redirect(request.referrer)

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    
    if request.method == 'POST':
        act = request.form.get('action')
        
        if act == 'toggle_gates':
            if getattr(settings, 'gates_mode_active', False):
                GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=False)
                User.objects(status='active', hunter_id__nin=[1000, 1001]).update(set__chosen_gate=0, set__gate_status='')
                flash('تم إغلاق البوابات وتصفير اختيارات الرحالة السابقة.', 'success')
            else:
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
                flash('تم فتح البوابات للرحالة ليختاروا!', 'success')
                
        elif act == 'execute_gates_fate':
            gate_num = int(request.form.get('target_gate') or 0)
            fate = request.form.get('fate_decision')
            users_in_gate = User.objects(status='active', chosen_gate=gate_num)
            
            if fate == 'success':
                users_in_gate.update(set__zone='الطابق 1', set__gate_status='passed')
                flash(f'تم إدخال الرحالة في البوابة {gate_num} إلى الطابق الأول بنجاح!', 'success')
            elif fate == 'death':
                users_in_gate.update(set__status='eliminated', set__freeze_reason=f'فخ البوابة {gate_num}')
                flash(f'تم إعدام الرحالة في البوابة {gate_num} (فخ مميت)!', 'success')
            elif fate == 'test':
                users_in_gate.update(set__gate_status='testing')
                flash(f'تم تحويل الرحالة في البوابة {gate_num} إلى غرفة الاختبار!', 'success')
        
        elif act == 'toggle_floor1':
            if getattr(settings, 'floor1_mode_active', False):
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor1_mode_active=False, set__f1_active_meetings={})
                User.objects.update(set__f1_tasks=[], set__current_room='الساحة', set__group_id=0, set__is_cursed=False, set__gems_collected=0, set__used_vent=False, set__emergency_used=False)
                flash('تم إيقاف الطابق الأول وتصفير المجموعات بدقة.', 'success')
            else:
                active_users = list(User.objects(status='active', hunter_id__nin=[1000, 1001]))
                random.shuffle(active_users)
                group_size = int(request.form.get('group_size', 5))
                group_id = 1
                for i in range(0, len(active_users), group_size):
                    members = active_users[i:i + group_size]
                    if members:
                        cursed_idx = random.randint(0, len(members) - 1)
                        for j, m in enumerate(members): 
                            assign_tasks_to_player(m)
                            m.update(
                                set__group_id=group_id, 
                                set__is_cursed=(j == cursed_idx), 
                                set__current_room='قاعة العروش', 
                                set__f1_has_voted=False, 
                                set__f1_votes_received=0,
                                set__gems_collected=0, 
                                set__used_vent=False, 
                                set__emergency_used=False,
                                set__f1_last_move=None
                            )
                        group_id += 1
                        
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__floor1_mode_active=True, 
                    set__floor1_move_cooldown=int(request.form.get('move_cooldown', 30)), 
                    set__floor1_kill_cooldown=int(request.form.get('kill_cooldown', 60)), 
                    set__floor1_gems_target=int(request.form.get('gems_target', 10)),
                    set__f1_cursed_win_percent=int(request.form.get('f1_cursed_win_percent', 50)),
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
            
            GlobalSettings.objects(setting_name='main_config').update_one(
                set__war_mode=new_state, 
                set__war_end_time=end_time,
                set__war_kill_target=int(request.form.get('war_kill_target') or 15) if new_state else settings.war_kill_target,
                set__bleed_rate_minutes=int(request.form.get('bleed_rate_minutes') or 60) if new_state else settings.bleed_rate_minutes,
                set__bleed_amount=int(request.form.get('bleed_amount') or 1) if new_state else settings.bleed_amount,
                set__attack_cooldown_minutes=int(request.form.get('attack_cooldown_minutes') or 5) if new_state else settings.attack_cooldown_minutes
            )
            
            # إذا بدأت الحرب للتو، سجّل الوقت الحالي كبداية للنزيف
            if new_state:
                GlobalSettings.objects(setting_name='main_config').update_one(set__last_global_bleed=datetime.utcnow())
            else: 
                # إذا توقفت، اعد الصحة كاملة للناجين
                User.objects(status='active', hunter_id__nin=[1000, 1001]).update(set__health=100)
                
            flash('تغيرت إعدادات الحرب الشاملة!', 'success')
            
        elif act == 'toggle_floor3':
            if getattr(settings, 'floor3_mode_active', False):
                time_left = (settings.vote_end_time - datetime.utcnow()).total_seconds() if settings.vote_end_time else 0
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__floor3_mode_active=False, 
                    set__floor3_paused=True, 
                    set__floor3_time_left=max(0, int(time_left))
                )
                flash('تم إيقاف/تجميد المحكمة وحفظ الوقت!', 'success')
            elif getattr(settings, 'floor3_paused', False):
                new_end = datetime.utcnow() + timedelta(seconds=settings.floor3_time_left)
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__floor3_mode_active=True, 
                    set__floor3_paused=False, 
                    set__vote_end_time=new_end
                )
                flash('تم استئناف المحكمة الكبرى!', 'success')
            else:
                vote_hours = int(request.form.get('vote_hours') or 0)
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__floor3_mode_active=True, 
                    set__floor3_results_active=False, 
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
                GlobalSettings.objects(setting_name='main_config').update_one(set__emperor_max_hp=emp_hp)
            GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=new_state)
            flash('تغيرت حالة المعركة الأخيرة!', 'success')
            
        elif act == 'reset_maze_winner':
            GlobalSettings.objects(setting_name='main_config').update_one(set__maze_winner_id=0)
            flash('تم تصفير حالة الفوز! عصر جديد يبدأ في المتاهة.', 'success')

        elif act == 'add_standalone_puzzle':
            cat = request.form.get('trap_category')
            eff = request.form.get('trap_effect')
            ans = request.form.get('puzzle_answer')
            News(
                title="كيان مخفي", 
                content="خفي", 
                category='hidden', 
                puzzle_type=f"{cat}_{eff}", 
                puzzle_answer=ans, 
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
            selected_ids = request.form.getlist('selected_users')
            
            for uid in selected_ids:
                u = User.objects(id=ObjectId(uid)).first()
                if u and u.hunter_id not in [1000, 1001]:
                    if bt == 'hard_delete': u.delete()
                    elif bt == 'activate': u.update(set__status='active', set__health=100)
                    elif bt == 'eliminate': u.update(set__status='eliminated', set__freeze_reason='قرار إداري')
                    elif bt == 'freeze': u.update(set__status='frozen')
                    elif bt == 'move_zone': u.update(set__zone=request.form.get('bulk_zone', 'الطابق 1'))
            flash('تم تنفيذ الأمر الجماعي بنجاح!', 'success')

        elif act == 'update_home_settings':
            GlobalSettings.objects(setting_name='main_config').update_one(
                set__home_title=request.form.get('home_title', 'البوابة'), 
                set__global_news_active=bool(request.form.get('global_news_active')), 
                set__global_news_text=request.form.get('global_news_text', '')
            )
            file = request.files.get('banner_file')
            if file and file.filename != '': 
                img_bytes = compress_image(file.read())
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__banner_url=f"data:{file.content_type};base64,{base64.b64encode(img_bytes).decode('utf-8')}"
                )
            flash('تم تحديث الإعدادات العامة!', 'success')

        elif act == 'setup_maintenance':
            duration = int(request.form.get('m_duration', 0))
            pages = request.form.getlist('m_pages')
            if duration > 0:
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__maintenance_mode=True,
                    set__maintenance_until=datetime.utcnow() + timedelta(minutes=duration),
                    set__maintenance_pages=pages
                )
                flash(f'تم تفعيل الصيانة لمدة {duration} دقيقة!', 'success')
            else:
                GlobalSettings.objects(setting_name='main_config').update_one(
                    set__maintenance_mode=False,
                    unset__maintenance_until=1,
                    set__maintenance_pages=[]
                )
                flash('تم إنهاء حالة الصيانة فوراً!', 'success')

        elif act == 'update_poneglyph':
            text = request.form.get('poneglyph_text', '')
            GlobalSettings.objects(setting_name='main_config').update_one(set__poneglyph_text=text)
            flash('تم نقش السر في البونغليف!', 'success')

        elif act == 'add_news':
            ptype = request.form.get('puzzle_type', 'none')
            img_data = ''
            file = request.files.get('news_image')
            if file and file.filename != '':
                img_bytes = compress_image(file.read())
                img_data = f"data:{file.content_type};base64,{base64.b64encode(img_bytes).decode('utf-8')}"
                
            News(
                title=request.form.get('title', ''),
                content=request.form.get('content', ''),
                category='puzzle' if ptype == 'standard_puzzle' else 'news',
                puzzle_type=ptype,
                puzzle_answer=request.form.get('puzzle_answer', ''),
                reward_points=int(request.form.get('reward_points') or 0),
                max_winners=int(request.form.get('max_winners') or 1),
                author='الإمبراطور',
                image_data=img_data,
                status='approved'
            ).save()
            flash('تم إصدار المرسوم/اللغز بنجاح!', 'success')

        elif act == 'bulk_delete_news':
            selected = request.form.getlist('selected_news')
            if selected:
                News.objects(id__in=[ObjectId(s) for s in selected]).delete()
                flash('تم حذف المراسيم المحددة.', 'success')

        elif act == 'add_spell':
            SpellConfig(
                spell_word=request.form.get('spell_word', '').strip(),
                spell_type=request.form.get('spell_type', ''),
                effect_value=int(request.form.get('effect_value') or 0),
                item_name=request.form.get('item_name', ''),
                max_uses=int(request.form.get('max_uses') or 1),
                expires_at=datetime.utcnow() + timedelta(hours=int(request.form.get('spell_hours') or 24)) if request.form.get('spell_hours') else None
            ).save()
            flash('تم زرع التعويذة في المذبح!', 'success')

        elif act == 'delete_spell':
            spell_id = request.form.get('spell_id')
            if spell_id:
                try:
                    SpellConfig.objects(id=ObjectId(spell_id)).delete()
                    flash('تم إبطال التعويذة نهائياً.', 'success')
                except Exception as e:
                    flash('خطأ في إبطال التعويذة.', 'error')

        return redirect(url_for('admin_panel'))
    
    # === استعلامات الإحصائيات الدقيقة (تتجاوز 1000 و 1001) ===
    users_query = User.objects(hunter_id__nin=[1000, 1001])
    search_query = request.args.get('search_user', '').strip() 
    
    if search_query:
        if search_query.isdigit(): 
            users_query = users_query.filter(hunter_id=int(search_query))
        else: 
            users_query = users_query.filter(username__icontains=search_query)

    total_u = users_query.count()
    alive_u = users_query.filter(status='active').count()
    dead_u = users_query.filter(status__in=['eliminated', 'dead_body']).count()
    pts_u = User.objects.sum('points') or 0
    
    stats = {
        'total': total_u,
        'alive': alive_u,
        'dead': dead_u,
        'points': pts_u
    }
    
    gate_counts = {
        1: User.objects(status='active', chosen_gate=1).count(),
        2: User.objects(status='active', chosen_gate=2).count(),
        3: User.objects(status='active', chosen_gate=3).count()
    }
        
    hidden_traps = News.objects(category='hidden')
    all_news = News.objects(category__in=['news', 'puzzle', 'declaration']).order_by('-created_at')
    spells = SpellConfig.objects().order_by('-created_at')
    
    return render_template(
        'admin.html', 
        users=users_query.order_by('-last_active')[:100], 
        settings=settings, 
        search_query=search_query, 
        hidden_traps=hidden_traps, 
        all_news=all_news, 
        spells=spells, 
        stats=stats, 
        gate_counts=gate_counts
    )

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
        except Exception as e: 
            flash('حدث خطأ في الإدخال', 'error')
    return redirect(request.referrer)

# ==========================================
# 🖼️ نظام الصور والألقاب (Achievements)
# ==========================================
@app.route('/avatar/<int:hunter_id>')
def get_avatar(hunter_id):
    u = User.objects(hunter_id=hunter_id).first()
    if u and getattr(u, 'avatar', ''):
        try:
            header, encoded = u.avatar.split(",", 1)
            data = base64.b64decode(encoded)
            return Response(data, mimetype=header.split(';')[0].split(':')[1])
        except Exception as e:
            pass
    
    # أيقونة ذهبية مدمجة في الخادم
    default_svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#d4af37"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>'''
    return Response(default_svg, mimetype='image/svg+xml')

def check_titles(user):
    titles = []
    puzzles = getattr(user, 'stats_puzzles_solved', 0)
    kills = getattr(user, 'stats_ghosts_caught', 0)
    
    if puzzles >= 5: titles.append('عالم الآثار')
    if puzzles >= 15: titles.append('حكيم سيفار')
    if kills >= 1: titles.append('صائد الأرواح')
    if kills >= 5: titles.append('سفاح المتاهة')
    if len(getattr(user, 'friends', [])) >= 3: titles.append('زعيم التحالف')
    
    existing = getattr(user, 'achievements', [])
    new_titles = [t for t in titles if t not in existing]
    
    if new_titles:
        user.update(push_all__achievements=new_titles)
        for t in new_titles:
            Notification(target_hunter_id=user.hunter_id, message=f'🏆 حصدت لقباً جديداً: {t}', notif_type='success').save()

@app.route('/set_title', methods=['POST'])
@login_required
def set_title():
    title = request.form.get('title', '')
    if title in getattr(g.user, 'achievements', []) or title == '':
        g.user.update(set__special_rank=title)
        flash('تم تغيير اللقب المعروض بنجاح!', 'success')
    return redirect(url_for('profile'))

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
