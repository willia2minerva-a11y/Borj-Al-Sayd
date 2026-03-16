from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, BattleLog, LoreLog, SpellConfig
from functools import wraps
from datetime import datetime, timedelta
import os, base64, random, math, json, traceback

app = Flask(__name__)

# 🚨 إعدادات قاعدة البيانات - تم ضبطها لتحمل الضغط العالي بدون اختناق
app.config['MONGODB_SETTINGS'] = {
    'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db'),
    'connectTimeoutMS': 30000,
    'socketTimeoutMS': 30000,
    'serverSelectionTimeoutMS': 30000,
    'connect': False  
}

app.config['SECRET_KEY'] = 'sephar-maze-emperor-v12-final'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

db.init_app(app)

@app.errorhandler(Exception)
def handle_exception(e):
    err = traceback.format_exc()
    return f"<div style='direction:ltr; background:#0a0a0a; color:#ff5555; padding:20px; font-family:monospace; border:2px solid red;'><h2>🚨 System Crash Report</h2><pre>{err}</pre></div>", 500

class ActionLog(db.Document):
    meta = {'strict': False}
    action_text = db.StringField()
    category = db.StringField() 
    created_at = db.DateTimeField(default=datetime.utcnow)
    log_date = db.StringField(default=lambda: datetime.utcnow().strftime('%Y-%m-%d'))

# 🚨 تم تقليل الكتابة العشوائية في السجلات لتسريع الموقع
def log_action(text, cat, is_epic=False):
    if is_epic or cat in ['combat', 'system', 'puzzle']: # لا نسجل الحركات التافهة
        try: 
            ActionLog(action_text=text, category=cat).save()
            if is_epic: LoreLog(content=text, is_epic=True).save()
        except: pass

# 🚀 مسار سحري جديد: يحول كود Base64 إلى صورة حقيقية ويحفظها في متصفح اللاعب (Cache) لسرعة البرق!
@app.route('/avatar/<int:hunter_id>')
def get_avatar(hunter_id):
    user = User.objects(hunter_id=hunter_id).only('avatar').first()
    if user and getattr(user, 'avatar', '') and user.avatar.startswith('data:image'):
        header, encoded = user.avatar.split(",", 1)
        mime = header.split(":")[1].split(";")[0]
        data = base64.b64decode(encoded)
        response = Response(data, mimetype=mime)
        # أمر المتصفح بحفظ الصورة لديه وعدم طلبها من السيرفر مجدداً!
        response.headers['Cache-Control'] = 'public, max-age=31536000'
        return response
    # إذا لم يكن لديه صورة، نعيد صورة شفافة صغيرة جداً
    empty_img = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    resp = Response(empty_img, mimetype="image/png")
    resp.headers['Cache-Control'] = 'public, max-age=31536000'
    return resp

def check_achievements(user):
    try:
        new_ach = []
        user_achs = getattr(user, 'achievements', []) or []
        
        if getattr(user, 'stats_ghosts_caught', 0) >= 5 and 'صائد الأشباح 👻' not in user_achs:
            user.achievements.append('صائد الأشباح 👻'); new_ach.append('صائد الأشباح 👻')
            user.intelligence_points = getattr(user, 'intelligence_points', 0) + 10
            
        if getattr(user, 'stats_puzzles_solved', 0) >= 5 and 'حكيم سيفار 📜' not in user_achs:
            user.achievements.append('حكيم سيفار 📜'); new_ach.append('حكيم سيفار 📜')
            user.intelligence_points = getattr(user, 'intelligence_points', 0) + 20
            
        if len(getattr(user, 'friends', []) or []) >= 5 and 'حليف القوم 🤝' not in user_achs:
            user.achievements.append('حليف القوم 🤝'); new_ach.append('حليف القوم 🤝')
            user.loyalty_points = getattr(user, 'loyalty_points', 0) + 15
            
        if new_ach: 
            flash(f'🏆 إنجاز جديد: {", ".join(new_ach)}', 'success')
            user.save()
    except: pass

# 🚀 تطبيق فكرة "العمل الكسول": نحسب الوقت بدون حفظه في القاعدة إلا إذا تغيرت حالة اللاعب!
def check_lazy_death_and_bleed(user, settings):
    try:
        if not user or getattr(user, 'role', '') == 'admin' or getattr(user, 'status', '') != 'active': return
            
        now = datetime.utcnow()
        last_act = getattr(user, 'last_active', None) or getattr(user, 'created_at', None) or now
        needs_save = False
        
        if (now - last_act).total_seconds() / 3600.0 > 72:
            user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'ابتلعته الرمال'
            log_action(f"💀 هلك {user.username} بسبب الغياب", "system")
            user.save(); return

        is_war_active = getattr(settings, 'war_mode', False) or getattr(settings, 'final_battle_mode', False)
        if settings and is_war_active:
            last_action = getattr(user, 'last_action_time', None) or now
            safe_until = last_action + timedelta(minutes=getattr(settings, 'safe_time_minutes', 120))
            
            if now > safe_until:
                start_bleed_time = max(getattr(user, 'last_health_check', None) or safe_until, safe_until)
                minutes_passed = (now - start_bleed_time).total_seconds() / 60.0
                bleed_rate = getattr(settings, 'bleed_rate_minutes', 60)
                
                if bleed_rate > 0 and minutes_passed >= bleed_rate:
                    cycles = math.floor(minutes_passed / bleed_rate)
                    user.health -= cycles * getattr(settings, 'bleed_amount', 1)
                    user.last_health_check = now
                    needs_save = True
                    
                    if user.health <= 0:
                        user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'نزف حتى الموت'
                        settings.dead_count = getattr(settings, 'dead_count', 0) + 1
                        log_action(f"🩸 نزف {user.username} حتى الموت.", "combat")
                        if getattr(settings, 'war_mode', False) and settings.dead_count >= getattr(settings, 'war_kill_target', 15):
                            settings.war_mode = False
                            log_action(f"🛑 اكتفت المتاهة. الناجون يصعدون للطابق 2!", "system", is_epic=True)
                            User.objects(status='active', role='hunter', hunter_id__ne=1000).update(set__zone='الطابق 2')
                        settings.save()
        if needs_save:
            user.save()
    except: pass

@app.before_request
def check_locks_and_status():
    if request.endpoint in ['static', 'login', 'logout', 'register', 'get_avatar']: return
    try: settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    except: settings = None
    
    user = None
    if 'user_id' in session:
        try:
            # 🚀 استدعاء بيانات اللاعب بدون الصورة العملاقة (توفير 90% من الذاكرة)
            user = User.objects(id=session.get('user_id')).exclude('avatar').first()
            if not user: session.clear(); return redirect(url_for('login'))
        except: session.clear(); return redirect(url_for('login'))
    
    if getattr(settings, 'maintenance_mode', False):
        m_until = getattr(settings, 'maintenance_until', None)
        if m_until and datetime.utcnow() > m_until:
            settings.maintenance_mode = False; settings.maintenance_pages = []; settings.save()
        elif not user or getattr(user, 'role', '') != 'admin':
            m_pages = getattr(settings, 'maintenance_pages', []) or []
            if 'all' in m_pages or request.endpoint in m_pages: return render_template('locked.html', message='جاري ترميم ونقش هذه الصفحة ⏳')

    if user:
        try: 
            now = datetime.utcnow()
            last_act = getattr(user, 'last_active', None)
            # 🚀 العمل الكسول العظيم: لا نحفظ وقته في قاعدة البيانات إلا مرة كل ساعة!
            if not last_act or (now - last_act).total_seconds() > 3600:
                User.objects(id=user.id).update_one(set__last_active=now)
            check_lazy_death_and_bleed(user, settings)
        except: pass
        
        quicksand = getattr(user, 'quicksand_lock_until', None)
        if quicksand and datetime.utcnow() < quicksand:
            tl = quicksand - datetime.utcnow()
            return render_template('locked.html', message=f'مقيّد في الرمال لـ {tl.seconds // 60}د و {tl.seconds % 60}ث')
            
        if getattr(user, 'gate_status', '') == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']:
            return render_template('gate_test.html', message=getattr(settings, 'gates_test_message', 'الاختبار'), user=user)

@app.context_processor
def inject_notifications():
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'current_user': None, 'war_settings': None, 'battle_logs': []}
    try:
        settings = GlobalSettings.objects(setting_name='main_config').first()
        notifs['war_settings'] = settings
        if settings and (getattr(settings, 'war_mode', False) or getattr(settings, 'final_battle_mode', False)):
            notifs['battle_logs'] = BattleLog.objects().order_by('-created_at')[:3]
    except: pass
    if 'user_id' in session:
        try:
            # 🚀 لا نسحب الصورة الطويلة لنبقي الصفحات خفيفة
            user = User.objects(id=session['user_id']).exclude('avatar').first()
            if user:
                notifs['current_user'] = user
                now = datetime.utcnow()
                notifs['un_news'] = News.objects(category='news', status='approved', created_at__gt=(getattr(user, 'last_seen_news', None) or now)).count()
                notifs['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=(getattr(user, 'last_seen_puzzles', None) or now)).count()
                notifs['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=(getattr(user, 'last_seen_decs', None) or now)).count()
                notifs['un_store'] = StoreItem.objects(created_at__gt=(getattr(user, 'last_seen_store', None) or now)).count()
        except: pass
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
        if 'user_id' not in session: return redirect(url_for('login'))
        user = User.objects(id=session['user_id']).first()
        if not user or getattr(user, 'role', '') != 'admin': return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

def get_allowed_news(user):
    try:
        all_news = News.objects(category='news', status='approved').order_by('-created_at')
        allowed = []
        for n in all_news:
            tg = getattr(n, 'target_group', 'all') or 'all'
            if tg == 'all' or \
               (user and getattr(user, 'gate_status', '') == 'testing' and tg == 'testing') or \
               (user and getattr(user, 'status', '') == 'eliminated' and tg == 'ghosts') or \
               (user and getattr(user, 'role', '') == 'hunter' and tg == 'hunters'):
                allowed.append(n)
        return allowed
    except: return []

@app.route('/')
def home():
    try: settings = GlobalSettings.objects(setting_name='main_config').first()
    except: settings = None
    
    user = User.objects(id=session.get('user_id')).first() if 'user_id' in session else None
    
    test_winner = None
    if user and getattr(user, 'role', '') == 'admin' and request.args.get('test_victory'):
        tid = request.args.get('test_victory')
        if tid.isdigit():
            test_winner = User.objects(hunter_id=int(tid)).first()

    allowed_news = get_allowed_news(user)
    latest_news = allowed_news[0] if allowed_news else None
    latest_dec = News.objects(category='declaration', status='approved').order_by('-created_at').first()
    
    alive_count = User.objects(status='active', hunter_id__ne=1000).count()
    dead_count = User.objects(status='eliminated', hunter_id__ne=1000).count()
    emperor = User.objects(hunter_id=1000).first()
    
    hunters_list = []
    if settings and getattr(settings, 'floor3_mode_active', False):
        hunters = User.objects(status='active', role='hunter', hunter_id__ne=1000)
        hunters_list = [{'id': h.hunter_id, 'name': h.username} for h in hunters]

    return render_template('index.html', settings=settings, news=latest_news, dec=latest_dec, 
                           alive_count=alive_count, dead_count=dead_count, emperor=emperor, 
                           active_hunters_json=json.dumps(hunters_list), test_winner=test_winner)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.objects(username=request.form['username']).first(): 
            flash('الاسم مستخدم مسبقاً.', 'error')
            return redirect(url_for('register'))
            
        existing_ids = [u.hunter_id for u in User.objects().only('hunter_id').order_by('hunter_id')]
        new_id = 1000
        for eid in existing_ids:
            if eid == new_id: new_id += 1
            elif eid > new_id: break
            
        initial_status = 'active' if new_id == 1000 else 'inactive'
        
        User(
            hunter_id=new_id, 
            username=request.form['username'], 
            password_hash=generate_password_hash(request.form['password']), 
            role='admin' if new_id == 1000 else 'hunter', 
            status=initial_status,
            facebook_link=request.form.get('facebook_link', ''),
            zone='البوابات', 
            special_rank='مستكشف'
        ).save()
        
        log_action(f"✨ رحالة جديد انضم للمتاهة: {request.form['username']}", "system")
        flash('تم تسجيلك بنجاح! أنت الآن عند البوابات في انتظار موافقة الإدارة.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(getattr(user, 'password_hash', ''), request.form['password']):
            session.permanent = True
            session['user_id'] = str(user.id)
            session['role'] = getattr(user, 'role', 'hunter')
            # 🚀 العمل الكسول: يتم التسجيل فقط عند الدخول للمرة الأولى
            User.objects(id=user.id).update_one(set__last_active=datetime.utcnow())
            return redirect(url_for('home'))
        flash('بياناتك خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout(): 
    session.clear()
    return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).first()
    settings = GlobalSettings.objects(setting_name='main_config').first()
    my_items = StoreItem.objects(name__in=getattr(user, 'inventory', []) or [])
    return render_template('profile.html', user=user, banner_url=getattr(settings, 'banner_url', ''), 
                           my_items=my_items, my_seals=[i for i in my_items if getattr(i, 'item_type', '') == 'seal'])

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    action = request.form.get('action')
    now = datetime.utcnow()
    
    if action == 'change_avatar':
        file = request.files.get('avatar_file')
        if file and file.filename != '': 
            user.avatar = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            flash('تم تحديث النقش بنجاح!', 'success')
            
    elif action == 'change_name':
        new_name = request.form.get('new_name')
        last_change = getattr(user, 'last_name_change', None)
        if last_change and (now - last_change).days < 15: flash('يسمح بتغيير الاسم كل 15 يوماً فقط!', 'error')
        elif User.objects(username=new_name).first(): flash('الاسم مستخدم مسبقاً!', 'error')
        else: 
            user.username = new_name; user.last_name_change = now
            flash('تم تغيير الهوية بنجاح!', 'success')
            
    elif action == 'change_password':
        old_pw = request.form.get('old_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')
        last_pw_change = getattr(user, 'last_password_change', None)
        if last_pw_change and (now - last_pw_change).days < 1: flash('يُسمح بتغيير كلمة السر مرة واحدة كل 24 ساعة!', 'error')
        elif not check_password_hash(getattr(user, 'password_hash', ''), old_pw): flash('كلمة السر القديمة غير صحيحة!', 'error')
        elif new_pw != confirm_pw: flash('كلمتا السر غير متطابقتين!', 'error')
        else: 
            user.password_hash = generate_password_hash(new_pw); user.last_password_change = now
            flash('تم تغيير كلمة السر بنجاح!', 'success')
    try: user.save()
    except: pass
    return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']: return redirect(url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    check_lazy_death_and_bleed(target_user, settings)
    current_user = User.objects(id=session['user_id']).first()
    my_items = StoreItem.objects(name__in=getattr(current_user, 'inventory', []) or [])
    return render_template('hunter_profile.html', target_user=target_user, banner_url=getattr(settings, 'banner_url', ''), 
                           my_weapons=[i for i in my_items if getattr(i, 'item_type', '')=='weapon'], 
                           my_heals=[i for i in my_items if getattr(i, 'item_type', '')=='heal'], 
                           my_spies=[i for i in my_items if getattr(i, 'item_type', '')=='spy'], 
                           my_steals=[i for i in my_items if getattr(i, 'item_type', '')=='steal'])

@app.route('/admin_update_profile/<int:target_id>', methods=['POST'])
@admin_required
def admin_update_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if target_user:
        action = request.form.get('action')
        try:
            if action == 'edit_name': target_user.username = request.form.get('new_name')
            elif action == 'edit_points': target_user.points = int(request.form.get('new_points') or 0)
            elif action == 'edit_hp':
                target_user.health = int(request.form.get('new_hp') or 0)
                if target_user.health <= 0: target_user.health = 0; target_user.status = 'eliminated'
                elif target_user.status == 'eliminated': target_user.status = 'active'
            elif action == 'edit_details':
                target_user.facebook_link = request.form.get('facebook_link', '')
                target_user.zone = request.form.get('zone', '')
                target_user.special_rank = request.form.get('special_rank', '')
                best_ach = request.form.get('best_achievements', '')
                target_user.best_achievements = [x.strip() for x in best_ach.split(',')] if best_ach else []
                worst_ach = request.form.get('worst_achievements', '')
                target_user.worst_achievements = [x.strip() for x in worst_ach.split(',')] if worst_ach else []
            target_user.save(); flash('تم التعديل الإمبراطوري!', 'success')
        except: pass
    return redirect(url_for('hunter_profile', target_id=target_id))
@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    sender = User.objects(id=session['user_id']).first()
    receiver = User.objects(hunter_id=target_id).first()
    
    if getattr(sender, 'status', '') != 'active' or not receiver or getattr(receiver, 'status', '') != 'active' or receiver.hunter_id not in getattr(sender, 'friends', []): 
        return redirect(request.referrer or url_for('home'))
        
    transfer_type = request.form.get('transfer_type')
    
    if transfer_type == 'points':
        try:
            amt = int(request.form.get('amount') or 0)
            if 0 < amt <= sender.points: 
                sender.points -= amt
                receiver.points += amt
                sender.loyalty_points = getattr(sender, 'loyalty_points', 0) + 2
                sender.save()
                receiver.save()
                log_action(f"📦 {sender.username} هرّب {amt} نقطة إلى {receiver.username}", "social")
                flash('تم التحويل!', 'success')
        except: pass
            
    elif transfer_type == 'item':
        itm = request.form.get('item_name')
        if itm in getattr(sender, 'inventory', []): 
            sender.inventory.remove(itm)
            receiver.inventory.append(itm)
            sender.loyalty_points = getattr(sender, 'loyalty_points', 0) + 5
            sender.save()
            receiver.save()
            log_action(f"📦 {sender.username} أرسل أداة ({itm}) إلى {receiver.username}", "social")
            flash('تم الإرسال!', 'success')
            
    return redirect(request.referrer or url_for('home'))

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    attacker = User.objects(id=session['user_id']).first()
    
    if getattr(attacker, 'status', '') != 'active': 
        return redirect(request.referrer or url_for('home'))
        
    target = User.objects(hunter_id=target_id).first()
    settings = GlobalSettings.objects(setting_name='main_config').first()
    item_name = request.form.get('item_name')
    item = StoreItem.objects(name=item_name).first()
    
    if not item or item_name not in getattr(attacker, 'inventory', []) or getattr(target, 'status', '') != 'active': 
        return redirect(request.referrer or url_for('home'))
        
    now = datetime.utcnow()
    item_type = getattr(item, 'item_type', '')
    
    if item_type == 'seal':
        if target.id == attacker.id:
            attacker.destroyed_seals = getattr(attacker, 'destroyed_seals', 0) + 1
            attacker.inventory.remove(item_name)
            
            if attacker.destroyed_seals >= 4:
                if settings: 
                    settings.war_mode = False
                    settings.final_battle_mode = False
                    settings.save()
                User.objects(status='active').update(health=100)
                flash('دُمرت اللعنة النهائية!', 'success')
                log_action(f"🛡️ {attacker.username} دمر الختم الرابع وأنهى الحرب!", "system", is_epic=True)
            else: 
                flash('تم تدمير الختم!', 'success')
            attacker.save()
        return redirect(request.referrer or url_for('home'))

    is_combat_active = getattr(settings, 'war_mode', False) or getattr(settings, 'final_battle_mode', False)
    
    if item_type == 'weapon' and is_combat_active and target.hunter_id not in getattr(attacker, 'friends', []):
        if getattr(target, 'role', '') == 'admin' and not getattr(settings, 'final_battle_mode', False):
            flash('🛡️ الإمبراطور محصن في الحرب الشاملة!', 'error')
            return redirect(request.referrer or url_for('home'))
            
        has_shield = False
        for inv_item in getattr(target, 'inventory', []):
            if 'درع' in inv_item or 'shield' in inv_item.lower():
                target.inventory.remove(inv_item)
                has_shield = True
                break
                
        if has_shield:
            log_action(f"🛡️ هجمة {attacker.username} انكسرت على درع {target.username}", "combat")
            flash('الهدف يمتلك درعاً! لقد ضاعت ضربتك وتم تدمير درعه.', 'error')
        else:
            target.health -= getattr(item, 'effect_amount', 0)
            log_action(f"⚔️ {attacker.username} طعن {target.username} بـ {item.name}", "combat")
            
            if target.health <= 0: 
                has_totem = False
                if not getattr(settings, 'final_battle_mode', False) and not getattr(settings, 'floor3_mode_active', False):
                    for inv_item in getattr(target, 'inventory', []):
                        if 'طوطم' in inv_item or 'totem' in inv_item.lower():
                            target.inventory.remove(inv_item)
                            has_totem = True
                            break
                
                if has_totem:
                    target.health = 50 
                    log_action(f"🌟 طوطم الخلود أعاد {target.username} للحياة!", "system", is_epic=True)
                    flash('استيقظ الهدف من الموت باستخدام طوطم الخلود!', 'error')
                else:
                    target.health = 0
                    target.status = 'eliminated'
                    settings.dead_count = getattr(settings, 'dead_count', 0) + 1
                    log_action(f"💀 {target.username} هلك على يد {attacker.username}", "combat")
                    
                    if getattr(target, 'role', '') == 'admin':
                        log_action(f"👑 سقط الإمبراطور! {attacker.username} هو الحاكم الجديد!", "system", is_epic=True)
                        settings.final_battle_mode = False
                        settings.war_mode = False
                        
                    # 🚨 نظام الترقية الآلي عند انتهاء الحرب
                    if getattr(settings, 'war_mode', False) and settings.dead_count >= getattr(settings, 'war_kill_target', 15):
                        settings.war_mode = False
                        log_action(f"🛑 اكتفت المتاهة من الدماء. الناجون يصعدون للطابق 2!", "system", is_epic=True)
                        User.objects(status='active', role='hunter', hunter_id__ne=1000).update(set__zone='الطابق 2')
                        
                    settings.save()
                    
            BattleLog(victim_name=target.username, weapon_name=item.name, remaining_hp=target.health).save()
            flash('تمت الضربة!', 'success')
            
        attacker.inventory.remove(item_name)
        attacker.last_action_time = now
        attacker.save()
        target.save()
            
    elif item_type == 'heal':
        if target.id == attacker.id or target.hunter_id in getattr(attacker, 'friends', []):
            heal_amount = getattr(item, 'effect_amount', 0)
            if getattr(target, 'role', '') == 'admin':
                target.health += heal_amount
            else:
                target.health = min(100, target.health + heal_amount)
                
            log_action(f"🧪 {attacker.username} عالج {target.username}", "combat")
            
            if target.id != attacker.id: 
                attacker.loyalty_points = getattr(attacker, 'loyalty_points', 0) + 5
                
            target.save()
            attacker.inventory.remove(item_name)
            attacker.last_action_time = now
            attacker.save()
            flash('عُولج!', 'success')

    elif item_type == 'spy':
        if any('حجاب' in i or 'درع' in i for i in getattr(target, 'inventory', [])): 
            attacker.inventory.remove(item_name)
            attacker.save()
            flash('الهدف محصن!', 'error')
        else:
            attacker.tajis_eye_until = now + timedelta(hours=1)
            attacker.inventory.remove(item_name)
            attacker.save()
            log_action(f"👁️ {attacker.username} فتح عين التجسس على {target.username}", "social")
            flash('تجسست بنجاح!', 'success')

    elif item_type == 'steal':
        stolen_item = request.form.get('target_item')
        if stolen_item in getattr(target, 'inventory', []):
            if any('حجاب' in i or 'درع' in i or 'عباءة' in i for i in getattr(target, 'inventory', [])): 
                attacker.inventory.remove(item_name)
                attacker.save()
                flash('الهدف محمي!', 'error')
            else:
                target.inventory.remove(stolen_item)
                attacker.inventory.append(stolen_item)
                attacker.inventory.remove(item_name)
                attacker.intelligence_points = getattr(attacker, 'intelligence_points', 0) + 5
                attacker.save()
                target.save()
                log_action(f"🖐️ {attacker.username} سرق أداة من {target.username}", "social")
                flash('تمت السرقة!', 'success')
                
    return redirect(request.referrer or url_for('home'))

@app.route('/altar', methods=['GET', 'POST'])
@login_required
def altar():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': 
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        spell_word = request.form.get('spell_word', '').strip()
        spell = SpellConfig.objects(spell_word=spell_word).first()
        settings = GlobalSettings.objects(setting_name='main_config').first()
        
        if not spell:
            flash('كلمة لا معنى لها... المذبح صامت.', 'error')
            return redirect(url_for('altar'))
            
        stype = getattr(spell, 'spell_type', '')
        val = getattr(spell, 'effect_value', 0)
        is_perc = getattr(spell, 'is_percentage', False)
        lore_msg = getattr(spell, 'lore_message', f"الرحالة [user] تلا تعويذة منسية!")
        
        if stype == 'hp_loss':
            loss = int(user.health * (val / 100.0)) if is_perc else val
            user.health -= loss
            if user.health <= 0:
                user.health = 0
                user.status = 'eliminated'
                user.freeze_reason = 'أحرقته تعويذة'
            flash('لقد دفعت ضريبة الدم!', 'error')
            
        elif stype == 'hp_gain':
            gain = int(user.health * (val / 100.0)) if is_perc else val
            user.health = min(100, user.health + gain)
            flash('تسري طاقة غريبة في جسدك!', 'success')
            
        elif stype == 'points_loss':
            loss = int(user.points * (val / 100.0)) if is_perc else val
            user.points = max(0, user.points - loss)
            flash('تبخرت أموالك أمام عينيك!', 'error')
            
        elif stype == 'item_reward':
            item_name = getattr(spell, 'item_name', '')
            if item_name:
                user.inventory.append(item_name)
                flash(f'ظهرت أداة ({item_name}) بين يديك!', 'success')
                
        elif stype == 'unlock_lore':
            user.unlocked_lore_room = True
            flash('انشق الجدار... غرفة السجلات مفتوحة لك الآن.', 'success')
            
        elif stype == 'unlock_top':
            user.unlocked_top_room = True
            flash('قاعة الأساطير ترحب بك.', 'success')
            
        elif stype == 'kill_emperor':
            if getattr(settings, 'final_battle_mode', False):
                emperor = User.objects(hunter_id=1000).first()
                if emperor:
                    emperor.health = 0
                    emperor.status = 'eliminated'
                    emperor.save()
                    settings.final_battle_mode = False
                    settings.war_mode = False
                    settings.save()
                    log_action(f"👑 {user.username} تلا تعويذة الموت وأسقط الإمبراطور!", "system", is_epic=True)
                    flash('سقط الإمبراطور! أنت الحاكم الجديد!', 'success')
            else:
                flash('التعويذة صحيحة، لكن الإمبراطور محصن حالياً.', 'error')
                
        log_action(lore_msg.replace('[user]', user.username), "puzzle", is_epic=True)
        user.save()
        return redirect(url_for('altar'))
        
    return render_template('altar.html')

@app.route('/lore_room')
@login_required
def lore_room():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active' or not getattr(user, 'unlocked_lore_room', False): 
        return redirect(url_for('home'))
    return render_template('lore_room.html', logs=LoreLog.objects().order_by('-created_at'))

@app.route('/top_room')
@login_required
def top_room():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active' or not getattr(user, 'unlocked_top_room', False): 
        return redirect(url_for('home'))
        
    top_iq = User.objects(hunter_id__ne=1000, status='active').order_by('-intelligence_points')[:10]
    top_loyal = User.objects(hunter_id__ne=1000, status='active').order_by('-loyalty_points')[:10]
    top_hp = User.objects(hunter_id__ne=1000, status='active').order_by('-health')[:10]
    
    return render_template('top_room.html', top_iq=top_iq, top_loyal=top_loyal, top_hp=top_hp)

@app.route('/friends', methods=['GET'])
@login_required
def friends():
    user = User.objects(id=session['user_id']).first()
    search_query = request.args.get('search')
    search_result = None
    
    if search_query: 
        if search_query.isdigit():
            search_result = User.objects(hunter_id=int(search_query)).first()
        else:
            search_result = User.objects(username__icontains=search_query).first()
            
    friend_requests = User.objects(hunter_id__in=getattr(user, 'friend_requests', []))
    friends_list = User.objects(hunter_id__in=getattr(user, 'friends', []))
    
    return render_template('friends.html', user=user, search_result=search_result, 
                           friend_requests=friend_requests, friends=friends_list)

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': 
        return redirect(request.referrer or url_for('home'))
        
    target = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
    if not target or getattr(target, 'status', '') != 'active': 
        return redirect(request.referrer or url_for('home'))
        
    if getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target.hunter_id)).first()
        
        if getattr(target, 'role', '') == 'cursed_ghost' and trap: 
            user.points -= getattr(trap, 'trap_penalty_points', 0)
            user.intelligence_points -= 5
            user.save()
            log_action(f"💀 {user.username} وقع في فخ شبح ملعون", "puzzle")
            flash('أيقظت شبحاً ملعوناً!', 'error')
            
        elif trap and str(user.id) not in getattr(trap, 'winners_list', []) and getattr(trap, 'current_winners', 0) < getattr(trap, 'max_winners', 1):
            user.points += getattr(trap, 'reward_points', 0)
            user.stats_ghosts_caught = getattr(user, 'stats_ghosts_caught', 0) + 1
            trap.current_winners = getattr(trap, 'current_winners', 0) + 1
            trap.winners_list.append(str(user.id))
            user.intelligence_points += 10
            user.save()
            trap.save()
            log_action(f"👻 {user.username} اصطاد شبح مرشد", "puzzle")
            check_achievements(user)
            flash('اصطدت شبحاً!', 'success')
            
        return redirect(request.referrer or url_for('home'))
        
    if target.hunter_id not in getattr(user, 'friends', []) and user.hunter_id not in getattr(target, 'friend_requests', []):
        target.friend_requests.append(user.hunter_id)
        target.save()
        log_action(f"🤝 {user.username} طلب تحالف مع {target.username}", "social")
        flash('أُرسل الطلب', 'success')
        
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': 
        return redirect(request.referrer or url_for('home'))
        
    target = User.objects(hunter_id=target_id).first()
    if target:
        if user.hunter_id in getattr(target, 'friend_requests', []): 
            target.friend_requests.remove(user.hunter_id)
        elif target.hunter_id in getattr(user, 'friends', []): 
            user.friends.remove(target.hunter_id)
            target.friends.remove(user.hunter_id)
            user.loyalty_points -= 20 
            log_action(f"💔 انهار التحالف بين {user.username} و {target.username}", "social")
            
        user.save()
        target.save()
        flash('تم الإلغاء', 'success')
        
    return redirect(request.referrer or url_for('home'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': 
        return redirect(request.referrer or url_for('home'))
        
    friend = User.objects(hunter_id=friend_id).first()
    if friend and friend.status == 'active' and friend_id in getattr(user, 'friend_requests', []):
        user.friend_requests.remove(friend_id)
        user.friends.append(friend_id)
        friend.friends.append(user.hunter_id)
        friend.save()
        user.save()
        log_action(f"🤝 نشأ تحالف بين {user.username} و {friend.username}", "social")
        check_achievements(user)
        flash('قُبل!', 'success')
        
    return redirect(request.referrer or url_for('home'))

@app.route('/news')
@login_required
def news():
    try: 
        user = User.objects(id=session['user_id']).first()
        user.last_seen_news = datetime.utcnow()
        user.save()
    except: 
        user = None
    return render_template('news.html', news_list=get_allowed_news(user))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    user = User.objects(id=session['user_id']).first()
    
    if request.method == 'POST':
        if getattr(user, 'status', '') != 'active': 
            flash('حسابك يحتاج تفعيل للمشاركة.', 'error')
            return redirect(url_for('puzzles'))
            
        guess = request.form.get('guess')
        puzzle = News.objects(id=request.form.get('puzzle_id')).first()
        
        # التحقق من الإجابة
        if puzzle and str(guess) == str(getattr(puzzle, 'puzzle_answer', '')) and str(user.id) not in getattr(puzzle, 'winners_list', []):
            if getattr(puzzle, 'current_winners', 0) < getattr(puzzle, 'max_winners', 1):
                user.points += getattr(puzzle, 'reward_points', 0)
                user.stats_puzzles_solved = getattr(user, 'stats_puzzles_solved', 0) + 1
                puzzle.winners_list.append(str(user.id))
                puzzle.current_winners = getattr(puzzle, 'current_winners', 0) + 1
                user.intelligence_points += 10
                user.save()
                puzzle.save()
                log_action(f"🧩 {user.username} حل لغز ({puzzle.title})", "puzzle")
                flash('إجابة صحيحة!', 'success')
            else: 
                flash('نفدت الجوائز!', 'error')
        else: 
            flash('إجابة خاطئة أو تم الحل مسبقاً.', 'error')
        return redirect(url_for('puzzles'))
        
    try: 
        user.last_seen_puzzles = datetime.utcnow()
        user.save()
    except: pass
    
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/delete_puzzle/<puzzle_id>', methods=['POST'])
@admin_required
def delete_puzzle(puzzle_id):
    try: 
        News.objects(id=puzzle_id).delete()
        flash('تم طمس اللغز!', 'success')
    except: pass
    return redirect(url_for('puzzles'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': 
        return redirect(url_for('home'))
        
    try: puzzle = News.objects(id=puzzle_id).first()
    except: return redirect(url_for('home'))
    
    if puzzle and getattr(puzzle, 'puzzle_type', '') == 'quicksand_trap':
        user.quicksand_lock_until = datetime.utcnow() + timedelta(minutes=getattr(puzzle, 'trap_duration_minutes', 5))
        user.intelligence_points -= 5
        user.save()
        log_action(f"🕸️ {user.username} وقع في فخ رمال", "puzzle")
        flash('وقعت في فخ الرمال!', 'error')
        
    elif puzzle and str(user.id) not in getattr(puzzle, 'winners_list', []) and getattr(puzzle, 'current_winners', 0) < getattr(puzzle, 'max_winners', 1):
        user.points += getattr(puzzle, 'reward_points', 0)
        puzzle.current_winners = getattr(puzzle, 'current_winners', 0) + 1
        puzzle.winners_list.append(str(user.id))
        user.intelligence_points += 15
        user.save()
        puzzle.save()
        log_action(f"🎁 {user.username} عثر على رابط سري", "puzzle")
        flash('جائزة سرية!', 'success')
        
    return redirect(request.referrer or url_for('home'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).first()
    
    if request.method == 'POST':
        if getattr(user, 'status', '') != 'active': 
            flash('حسابك قيد المراجعة ولا يسمح لك بالنشر.', 'error')
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
            status='approved' if getattr(user, 'role', '') == 'admin' else 'pending'
        ).save()
        
        log_action(f"📢 {user.username} أرسل تصريحاً", "social")
        flash('تم الإرسال بنجاح', 'success')
        return redirect(url_for('declarations'))
        
    try: 
        user.last_seen_decs = datetime.utcnow()
        user.save()
    except: pass
    
    approved_decs = News.objects(category='declaration', status='approved').order_by('-created_at')
    pending_decs = News.objects(category='declaration', status='pending') if getattr(user, 'role', '') == 'admin' else []
    my_pending_decs = News.objects(category='declaration', status='pending', author=user.username).order_by('-created_at')
    
    authors = set([d.author for d in approved_decs] + [d.author for d in pending_decs] + [d.author for d in my_pending_decs])
    # 🚀 لا نحمل الصور العملاقة هنا لضمان السرعة
    users_query = User.objects(username__in=authors).only('username')
    avatars = {u.username: u.username for u in users_query}
    
    return render_template('declarations.html', approved_decs=approved_decs, pending_decs=pending_decs, 
                           my_pending_decs=my_pending_decs, current_user=user, avatars=avatars)

@app.route('/delete_declaration/<dec_id>', methods=['POST'])
@login_required
def delete_declaration(dec_id):
    user = User.objects(id=session['user_id']).first()
    dec = News.objects(id=dec_id).first()
    if dec and (dec.author == user.username or getattr(user, 'role', '') == 'admin'): 
        dec.delete()
        flash('تم الحذف!', 'success')
    return redirect(url_for('declarations'))

@app.route('/store')
@login_required
def store():
    try: 
        user = User.objects(id=session['user_id']).first()
        user.last_seen_store = datetime.utcnow()
        user.save()
    except: pass
    return render_template('store.html', items=StoreItem.objects())

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': 
        return redirect(url_for('store'))
        
    try: item = StoreItem.objects(id=item_id).first()
    except: return redirect(url_for('store'))
    
    if user and item and user.points >= item.price:
        user.points -= item.price
        
        if getattr(item, 'is_luck', False):
            outcome = random.randint(getattr(item, 'luck_min', 0), getattr(item, 'luck_max', 0))
            user.points += outcome
            log_action(f"🎲 لعب {user.username} بصندوق حظ ونتيجته: {outcome}", "puzzle")
            flash(f'النتيجة: {outcome}', 'success' if outcome >= 0 else 'error')
            
        elif getattr(item, 'is_mirage', False): 
            user.intelligence_points -= 10
            log_action(f"🕸️ وقع {user.username} في فخ المتجر", "puzzle")
            flash(getattr(item, 'mirage_message', 'فخ!'), 'error')
            
        else: 
            user.inventory.append(item.name)
            user.stats_items_bought = getattr(user, 'stats_items_bought', 0) + 1
            log_action(f"🐪 اشترى {user.username} {item.name}", "social")
            flash('تم الشراء!', 'success')
            
        user.save()
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): 
    return render_template('graveyard.html', users=User.objects(status='eliminated').only('username', 'freeze_reason', 'hunter_id').order_by('-id'))

@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    user = User.objects(id=session['user_id']).first()
    settings = GlobalSettings.objects(setting_name='main_config').first()
    
    if getattr(user, 'status', '') != 'active': 
        return redirect(url_for('home'))
        
    if getattr(settings, 'gates_mode_active', False) and not getattr(settings, 'gates_selection_locked', False) and getattr(user, 'chosen_gate', 0) == 0:
        gate_num = int(request.form.get('gate_num') or 0)
        user.chosen_gate = gate_num
        user.gate_status = 'waiting'
        user.save()
        log_action(f"🚪 اختار {user.username} البوابة {gate_num}", "system")
        flash('تم التسجيل!', 'success')
        
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'gate_status', '') == 'testing': 
        user.gate_test_answer = request.form.get('test_answer', '')
        user.save()
        log_action(f"📝 {user.username} سلم إجابة الاختبار", "system")
    return redirect(url_for('home'))

@app.route('/submit_floor3_votes', methods=['POST'])
@login_required
def submit_floor3_votes():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'hunter_id', 0) == 1000 or getattr(user, 'has_voted', False) or getattr(user, 'status', '') != 'active': 
        return redirect(url_for('home'))
        
    try:
        tids = [int(request.form.get(f'target_{i}')) for i in range(1, 6)]
        amts = [int(request.form.get(f'amount_{i}')) for i in range(1, 6)]
        
        if len(set(tids)) == 5 and sum(amts) == 100 and 1000 not in tids and user.hunter_id not in tids:
            for i, tid in enumerate(tids):
                target_user = User.objects(hunter_id=tid).first()
                if target_user: 
                    target_user.survival_votes = getattr(target_user, 'survival_votes', 0) + amts[i]
                    target_user.save()
            user.has_voted = True
            user.save()
            log_action(f"🗳️ {user.username} ثبت أصواته للمحكمة", "puzzle")
            flash('تم التثبيت!', 'success')
        else: 
            flash('خطأ في التوزيع أو محاولة استهداف الإمبراطور!', 'error')
    except: pass
    return redirect(url_for('home'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    try: settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    except: settings = None
        
    sel_date = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    logs = ActionLog.objects(log_date=sel_date).order_by('-created_at')
    
    if request.method == 'POST':
        act = request.form.get('action')
        try:
            if act == 'moderate_dec':
                d = News.objects(id=request.form.get('dec_id')).first()
                if d: 
                    if request.form.get('decision') == 'approve':
                        d.status = 'approved'
                        d.save()
                    else: d.delete()
                        
            elif act == 'add_targeted_news':
                News(title=request.form.get('title'), content=request.form.get('content'), category='news', target_group=request.form.get('target_group')).save()
                
            elif act == 'setup_maintenance':
                dur = int(request.form.get('m_duration') or 0)
                pages = request.form.getlist('m_pages')
                if dur > 0: 
                    settings.maintenance_mode = True
                    settings.maintenance_until = datetime.utcnow() + timedelta(minutes=dur)
                    settings.maintenance_pages = pages
                else: 
                    settings.maintenance_mode = False; settings.maintenance_pages = []
                    
            elif act == 'toggle_war':
                settings.war_mode = not getattr(settings, 'war_mode', False)
                if not settings.war_mode: 
                    User.objects(status='active').update(health=100)
                    BattleLog.objects.delete()
                    
            elif act == 'toggle_final_battle': 
                settings.final_battle_mode = not getattr(settings, 'final_battle_mode', False)
                
            elif act == 'set_admin_hp':
                User.objects(hunter_id=1000).update(health=int(request.form.get('admin_hp') or 100))
                
            elif act == 'add_news':
                puzzle_type = request.form.get('puzzle_type')
                News(
                    title=request.form.get('title'), 
                    content=request.form.get('content'), 
                    category='puzzle' if puzzle_type != 'none' else 'news', 
                    puzzle_type=puzzle_type, 
                    puzzle_answer=request.form.get('puzzle_answer'), 
                    reward_points=int(request.form.get('reward_points') or 0), 
                    max_winners=int(request.form.get('max_winners') or 1)
                ).save()
                
            elif act == 'add_standalone_puzzle':
                puzzle_type = request.form.get('puzzle_type')
                puzzle_answer = request.form.get('puzzle_answer', '')
                News(
                    title="لغز مخفي", content="خفي", category='hidden', puzzle_type=puzzle_type, puzzle_answer=puzzle_answer, 
                    reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1), 
                    trap_duration_minutes=int(request.form.get('trap_duration') or 0), trap_penalty_points=int(request.form.get('trap_penalty') or 0)
                ).save()
                
                if puzzle_type in ['fake_account', 'cursed_ghost']:
                    User(
                        hunter_id=int(puzzle_answer), username=f"شبح_{puzzle_answer}", password_hash="dummy", 
                        role='ghost' if puzzle_type == 'fake_account' else 'cursed_ghost', status='active', avatar='👻'
                    ).save()
                    
            elif act == 'add_store_item':
                im = ''
                file = request.files.get('item_image')
                if file: im = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
                StoreItem(
                    name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price') or 0), 
                    item_type=request.form.get('item_type'), effect_amount=int(request.form.get('effect_amount') or 0), 
                    is_mirage=bool(request.form.get('is_mirage')), mirage_message=request.form.get('mirage_message', ''), 
                    is_luck=bool(request.form.get('is_luck')), luck_min=int(request.form.get('luck_min') or 0), 
                    luck_max=int(request.form.get('luck_max') or 0), image=im
                ).save()
                
            elif act == 'add_spell':
                SpellConfig(
                    spell_word=request.form.get('spell_word'), spell_type=request.form.get('spell_type'), effect_value=int(request.form.get('effect_value') or 0), 
                    is_percentage=bool(request.form.get('is_percentage')), item_name=request.form.get('item_name', ''), 
                    lore_message=request.form.get('lore_message', '[user] ألقى تعويذة غامضة')
                ).save()
                
            elif act == 'bulk_action':
                bt = request.form.get('bulk_type')
                for uid in request.form.getlist('selected_users'):
                    u = User.objects(id=uid).first()
                    if u and getattr(u, 'hunter_id', 0) != 1000:
                        if bt == 'hard_delete': u.delete()
                        elif bt == 'activate': 
                            u.status = 'active'; u.health = 100; u.save()
                        elif bt == 'eliminate': 
                            u.status = 'eliminated'; u.freeze_reason = request.form.get('bulk_reason', 'بأمر الإدارة'); u.save()
                        elif bt == 'move_zone': 
                            u.zone = request.form.get('bulk_zone', 'الطابق 1'); u.save()
                            
            elif act == 'setup_gates':
                settings.gates_mode_active = True
                settings.gates_selection_locked = bool(request.form.get('locked'))
                settings.gates_description = request.form.get('desc', '')
                settings.gate_1_name = request.form.get('g1', '')
                settings.gate_2_name = request.form.get('g2', '')
                settings.gate_3_name = request.form.get('g3', '')
                settings.gates_test_message = request.form.get('test_msg', '')
                
            elif act == 'close_gates_mode': 
                settings.gates_mode_active = False
                
            elif act == 'judge_gates':
                fates = {1: request.form.get('fate_1'), 2: request.form.get('fate_2'), 3: request.form.get('fate_3')}
                for u in User.objects(gate_status='waiting', status='active'):
                    fate = fates.get(str(getattr(u, 'chosen_gate', 0))) 
                    if fate == 'pass': 
                        u.gate_status = 'passed'; u.zone = 'الطابق 1'
                    elif fate == 'kill': 
                        u.status = 'eliminated'; u.freeze_reason = 'البوابة التهمته'
                    elif fate == 'test': 
                        u.gate_status = 'testing'
                    u.save()
                    
            elif act == 'judge_test_user':
                u = User.objects(id=request.form.get('user_id')).first()
                if u: 
                    if request.form.get('decision') == 'pass': 
                        u.gate_status = 'passed'; u.zone = 'الطابق 1'
                    else: 
                        u.status = 'eliminated'; u.freeze_reason = 'فشل في الاختبار'
                    u.save()
                    
            elif act == 'toggle_floor3': 
                settings.floor3_mode_active = not getattr(settings, 'floor3_mode_active', False)
                
            elif act == 'punish_floor3_slackers':
                slackers = User.objects(has_voted=False, status='active', role='hunter')
                active_voters = User.objects(has_voted=True, status='active', role='hunter')
                if slackers.count() > 0 and active_voters.count() > 0:
                    bonus = (slackers.count() * 100) // active_voters.count()
                    for v in active_voters: 
                        v.survival_votes = getattr(v, 'survival_votes', 0) + bonus; v.save()
                for s_user in slackers: 
                    s_user.status = 'eliminated'; s_user.freeze_reason = 'لم يصوت'; s_user.save()
                    
            elif act == 'advance_voters':
                top_n = int(request.form.get('top_n', 5))
                leaders = User.objects(status='active', role='hunter').order_by('-survival_votes')[:top_n]
                for l in leaders:
                    l.zone = 'المعركة الأخيرة'; l.save()
                settings.floor3_mode_active = False
                log_action(f"أُغلقت محكمة الأصوات، وصعد أعلى {top_n} لاعبين للمعركة الأخيرة!", "system", True)
                
            elif act == 'update_war_settings':
                settings.bleed_rate_minutes = int(request.form.get('bleed_rate_minutes') or 60)
                settings.bleed_amount = int(request.form.get('bleed_amount') or 1)
                settings.safe_time_minutes = int(request.form.get('safe_time_minutes') or 120)
                settings.war_kill_target = int(request.form.get('war_kill_target') or 15)
                
            elif act == 'update_nav_names':
                settings.nav_home = request.form.get('nav_home', getattr(settings, 'nav_home', ''))
                settings.nav_profile = request.form.get('nav_profile', getattr(settings, 'nav_profile', ''))
                settings.nav_friends = request.form.get('nav_friends', getattr(settings, 'nav_friends', ''))
                settings.nav_news = request.form.get('nav_news', getattr(settings, 'nav_news', ''))
                settings.nav_puzzles = request.form.get('nav_puzzles', getattr(settings, 'nav_puzzles', ''))
                settings.nav_decs = request.form.get('nav_decs', getattr(settings, 'nav_decs', ''))
                settings.nav_store = request.form.get('nav_store', getattr(settings, 'nav_store', ''))
                settings.nav_grave = request.form.get('nav_grave', getattr(settings, 'nav_grave', ''))
                settings.maze_name = request.form.get('maze_name', getattr(settings, 'maze_name', ''))
                
            elif act == 'update_home_settings':
                settings.home_title = request.form.get('home_title', 'البوابة')
                settings.home_color = request.form.get('home_color', 'var(--zone-0-black)')
                file = request.files.get('banner_file')
                if file and file.filename != '': 
                    settings.banner_url = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
                    
            elif act == 'toggle_global_news':
                settings.global_news_active = not getattr(settings, 'global_news_active', False)
                settings.global_news_text = request.form.get('global_news_text', '')
                
            if settings: settings.save()
        except: pass
        return redirect(url_for('admin_panel', date=sel_date))
    
    # 🚀 نجلب قائمة اللاعبين بدون الصور لتسريع فتح صفحة الإدارة
    users = User.objects(hunter_id__ne=1000).exclude('avatar').order_by('hunter_id')
    
    gate_stats = {
        1: User.objects(chosen_gate=1, status='active').count(), 
        2: User.objects(chosen_gate=2, status='active').count(), 
        3: User.objects(chosen_gate=3, status='active').count()
    }
    
    floor3_leaders = []
    if getattr(settings, 'floor3_mode_active', False):
        floor3_leaders = User.objects(status='active', role='hunter').order_by('-survival_votes')[:5]
        
    return render_template(
        'admin.html', 
        users=users, 
        settings=settings, 
        logs=logs, 
        current_date=sel_date, 
        test_users=User.objects(gate_status='testing', status='active'),
        gate_stats=gate_stats,
        floor3_leaders=floor3_leaders
    )

@app.route('/download_logs/<log_date>')
@admin_required
def download_logs(log_date):
    logs = ActionLog.objects(log_date=log_date).order_by('created_at')
    out = f"--- سجلات المتاهة ليوم {log_date} ---\n\n"
    for l in logs: 
        out += f"[{l.created_at.strftime('%H:%M:%S')}] ({l.category}): {l.action_text}\n"
    return Response(out, mimetype="text/plain", headers={"Content-disposition": f"attachment; filename=logs_{log_date}.txt"})

if __name__ == '__main__': 
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
