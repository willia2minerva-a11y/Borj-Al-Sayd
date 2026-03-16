from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, SpellConfig
from functools import wraps
from datetime import datetime, timedelta
import os, base64, random, math, json, traceback

app = Flask(__name__)

# 🚨 إعدادات قاعدة البيانات - السرعة القصوى (بدون ضغط)
app.config['MONGODB_SETTINGS'] = {
    'host': os.getenv('MONGO_URI'),
    'connect': False  
}
app.config['SECRET_KEY'] = 'sephar-maze-emperor-v12-final'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

db.init_app(app)

@app.errorhandler(Exception)
def handle_exception(e):
    return f"<div style='direction:ltr; background:#0a0a0a; color:#ff5555; padding:20px; font-family:monospace; border:2px solid red;'><h2>🚨 System Crash Report</h2><pre>{traceback.format_exc()}</pre></div>", 200

# 🚀 مسار البانر والصور الخفيفة (كاش المتصفح لسرعة البرق)
@app.route('/banner.png')
def get_banner():
    settings = GlobalSettings.objects(setting_name='main_config').only('banner_url').first()
    if settings and getattr(settings, 'banner_url', '') and settings.banner_url.startswith('data:image'):
        header, encoded = settings.banner_url.split(",", 1)
        mime = header.split(":")[1].split(";")[0]
        data = base64.b64decode(encoded)
        resp = Response(data, mimetype=mime)
        resp.headers['Cache-Control'] = 'public, max-age=31536000'
        return resp
    return Response(b'', mimetype="image/png")

@app.route('/avatar/<int:hunter_id>')
def get_avatar(hunter_id):
    user = User.objects(hunter_id=hunter_id).only('avatar').first()
    if user and getattr(user, 'avatar', '') and user.avatar.startswith('data:image'):
        header, encoded = user.avatar.split(",", 1)
        mime = header.split(":")[1].split(";")[0]
        data = base64.b64decode(encoded)
        resp = Response(data, mimetype=mime)
        resp.headers['Cache-Control'] = 'public, max-age=31536000'
        return resp
    empty_img = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    resp = Response(empty_img, mimetype="image/png")
    resp.headers['Cache-Control'] = 'public, max-age=31536000'
    return resp

def check_achievements(user):
    try:
        new_ach = []
        user_achs = getattr(user, 'achievements', []) or []
        if getattr(user, 'stats_ghosts_caught', 0) >= 5 and 'صائد الأشباح 👻' not in user_achs:
            user.achievements.append('صائد الأشباح 👻'); new_ach.append('صائد الأشباح 👻'); user.intelligence_points = getattr(user, 'intelligence_points', 0) + 10
        if getattr(user, 'stats_puzzles_solved', 0) >= 5 and 'حكيم سيفار 📜' not in user_achs:
            user.achievements.append('حكيم سيفار 📜'); new_ach.append('حكيم سيفار 📜'); user.intelligence_points = getattr(user, 'intelligence_points', 0) + 20
        if len(getattr(user, 'friends', []) or []) >= 5 and 'حليف القوم 🤝' not in user_achs:
            user.achievements.append('حليف القوم 🤝'); new_ach.append('حليف القوم 🤝'); user.loyalty_points = getattr(user, 'loyalty_points', 0) + 15
        if new_ach: 
            flash(f'🏆 إنجاز جديد: {", ".join(new_ach)}', 'success')
            user.save()
    except: pass

def check_lazy_death_and_bleed(user, settings):
    try:
        if not user or getattr(user, 'role', '') == 'admin' or getattr(user, 'status', '') != 'active': return
        now = datetime.utcnow()
        last_act = getattr(user, 'last_active', None) or getattr(user, 'created_at', None) or now
        needs_save = False
        
        if (now - last_act).total_seconds() / 3600.0 > 72:
            user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'ابتلعته الرمال'
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
                        GlobalSettings.objects(setting_name='main_config').update_inc(dead_count=1)
                        dead_total = getattr(settings, 'dead_count', 0) + 1
                        if getattr(settings, 'war_mode', False) and dead_total >= getattr(settings, 'war_kill_target', 15):
                            GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False)
                            User.objects(status='active', role='hunter', hunter_id__ne=1000).update(set__zone='الطابق 2')
        if needs_save: user.save()
    except: pass

@app.before_request
def check_locks_and_status():
    if request.endpoint in ['static', 'login', 'logout', 'register', 'get_avatar', 'get_banner']: return
    try: settings = GlobalSettings.objects(setting_name='main_config').exclude('banner_url').first() or GlobalSettings(setting_name='main_config').save()
    except: settings = None
    
    # ⏳ المؤقتات الآلية الخفيفة
    if settings:
        now = datetime.utcnow()
        if getattr(settings, 'war_mode', False) and getattr(settings, 'war_end_time', None) and now >= settings.war_end_time:
            GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False)
            User.objects(status='active').update(health=100)
            
        if getattr(settings, 'floor3_mode_active', False) and getattr(settings, 'vote_end_time', None) and now >= settings.vote_end_time:
            top_n = getattr(settings, 'vote_top_n', 5)
            for l in User.objects(status='active', role='hunter').order_by('-survival_votes')[:top_n]:
                l.zone = 'المعركة الأخيرة'; l.save()
            GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=False)

    user = None
    if 'user_id' in session:
        try:
            user = User.objects(id=session.get('user_id')).exclude('avatar').first()
            if not user: session.clear(); return redirect(url_for('login'))
        except: session.clear(); return redirect(url_for('login'))
    
    if getattr(settings, 'maintenance_mode', False):
        m_until = getattr(settings, 'maintenance_until', None)
        if m_until and datetime.utcnow() > m_until:
            GlobalSettings.objects(setting_name='main_config').update_one(set__maintenance_mode=False, set__maintenance_pages=[])
        elif not user or getattr(user, 'role', '') != 'admin':
            m_pages = getattr(settings, 'maintenance_pages', []) or []
            if 'all' in m_pages or request.endpoint in m_pages: return render_template('locked.html', message='المتاهة قيد الترميم ⏳')

    if user:
        try: 
            now = datetime.utcnow()
            last_act = getattr(user, 'last_active', None)
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
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'current_user': None, 'war_settings': None}
    try:
        settings = GlobalSettings.objects(setting_name='main_config').exclude('banner_url').first()
        if settings:
            settings.banner_url = '/banner.png' 
            notifs['war_settings'] = settings
    except: pass
    if 'user_id' in session:
        try:
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
        user = User.objects(id=session['user_id']).exclude('avatar').first()
        if not user or getattr(user, 'role', '') != 'admin': return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

def get_allowed_news(user):
    try:
        all_news = News.objects(category='news', status='approved').exclude('image_data').order_by('-created_at')
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
    try: 
        settings = GlobalSettings.objects(setting_name='main_config').exclude('banner_url').first()
        if settings: settings.banner_url = '/banner.png'
    except: settings = None
    
    user = User.objects(id=session.get('user_id')).exclude('avatar').first() if 'user_id' in session else None
    test_winner = User.objects(hunter_id=int(request.args.get('test_victory'))).exclude('avatar').first() if user and getattr(user, 'role', '') == 'admin' and request.args.get('test_victory') and request.args.get('test_victory').isdigit() else None

    allowed_news = get_allowed_news(user)
    latest_news = allowed_news[0] if allowed_news else None
    latest_dec = News.objects(category='declaration', status='approved').exclude('image_data').order_by('-created_at').first()
    
    alive_count = User.objects(status='active', hunter_id__ne=1000).count()
    dead_count = User.objects(status='eliminated', hunter_id__ne=1000).count()
    emperor = User.objects(hunter_id=1000).exclude('avatar').first()
    
    hunters_list = [{'id': h.hunter_id, 'name': h.username} for h in User.objects(status='active', role='hunter', hunter_id__ne=1000).exclude('avatar')] if settings and getattr(settings, 'floor3_mode_active', False) else []
    return render_template('index.html', settings=settings, news=latest_news, dec=latest_dec, alive_count=alive_count, dead_count=dead_count, emperor=emperor, active_hunters_json=json.dumps(hunters_list), test_winner=test_winner)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.objects(username=request.form['username']).first(): 
            flash('الاسم مستخدم مسبقاً.', 'error'); return redirect(url_for('register'))
        existing_ids = [u.hunter_id for u in User.objects().only('hunter_id').order_by('hunter_id')]
        new_id = 1000
        for eid in existing_ids:
            if eid == new_id: new_id += 1
            elif eid > new_id: break
        User(hunter_id=new_id, username=request.form['username'], password_hash=generate_password_hash(request.form['password']), role='admin' if new_id == 1000 else 'hunter', status='active' if new_id == 1000 else 'inactive', facebook_link=request.form.get('facebook_link', ''), zone='البوابات', special_rank='مستكشف').save()
        flash('تم تسجيلك بنجاح! في انتظار التفعيل.', 'success'); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(getattr(user, 'password_hash', ''), request.form['password']):
            session.permanent = True; session['user_id'] = str(user.id); session['role'] = getattr(user, 'role', 'hunter')
            User.objects(id=user.id).update_one(set__last_active=datetime.utcnow())
            return redirect(url_for('home'))
        flash('بياناتك خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).exclude('avatar').first()
    settings = GlobalSettings.objects(setting_name='main_config').exclude('banner_url').first()
    if settings: settings.banner_url = '/banner.png'
    my_items = StoreItem.objects(name__in=getattr(user, 'inventory', []) or []).exclude('image')
    return render_template('profile.html', user=user, banner_url=getattr(settings, 'banner_url', ''), my_items=my_items, my_seals=[i for i in my_items if getattr(i, 'item_type', '') == 'seal'])

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    action = request.form.get('action'); now = datetime.utcnow()
    if action == 'change_avatar':
        file = request.files.get('avatar_file')
        if file and file.filename != '': 
            user.avatar = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            flash('تم تحديث النقش بنجاح!', 'success')
    elif action == 'change_name':
        new_name = request.form.get('new_name')
        if getattr(user, 'last_name_change', None) and (now - user.last_name_change).days < 15: flash('كل 15 يوماً فقط!', 'error')
        elif User.objects(username=new_name).first(): flash('الاسم مستخدم مسبقاً!', 'error')
        else: user.username = new_name; user.last_name_change = now; flash('تم التغيير!', 'success')
    elif action == 'change_password':
        old_pw = request.form.get('old_password', ''); new_pw = request.form.get('new_password', ''); confirm_pw = request.form.get('confirm_password', '')
        if getattr(user, 'last_password_change', None) and (now - user.last_password_change).days < 1: flash('مرة كل 24 ساعة!', 'error')
        elif not check_password_hash(getattr(user, 'password_hash', ''), old_pw): flash('الكلمة القديمة خاطئة!', 'error')
        elif new_pw != confirm_pw: flash('غير متطابقتين!', 'error')
        else: user.password_hash = generate_password_hash(new_pw); user.last_password_change = now; flash('تم التغيير بنجاح!', 'success')
    try: user.save()
    except: pass
    return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).exclude('avatar').first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']: return redirect(url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').exclude('banner_url').first()
    if settings: settings.banner_url = '/banner.png'
    check_lazy_death_and_bleed(target_user, settings)
    current_user = User.objects(id=session['user_id']).exclude('avatar').first()
    my_items = StoreItem.objects(name__in=getattr(current_user, 'inventory', []) or []).exclude('image')
    return render_template('hunter_profile.html', target_user=target_user, banner_url=getattr(settings, 'banner_url', ''), 
                           my_weapons=[i for i in my_items if getattr(i, 'item_type', '')=='weapon'], my_heals=[i for i in my_items if getattr(i, 'item_type', '')=='heal'], 
                           my_spies=[i for i in my_items if getattr(i, 'item_type', '')=='spy'], my_steals=[i for i in my_items if getattr(i, 'item_type', '')=='steal'])

@app.route('/admin_update_profile/<int:target_id>', methods=['POST'])
@admin_required
def admin_update_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if target_user:
        try:
            action = request.form.get('action')
            if action == 'edit_name': target_user.username = request.form.get('new_name')
            elif action == 'edit_points': target_user.points = int(request.form.get('new_points') or 0)
            elif action == 'edit_hp':
                target_user.health = int(request.form.get('new_hp') or 0)
                if target_user.health <= 0: target_user.health = 0; target_user.status = 'eliminated'
                elif target_user.status == 'eliminated': target_user.status = 'active'
            elif action == 'edit_details':
                target_user.facebook_link = request.form.get('facebook_link', ''); target_user.zone = request.form.get('zone', ''); target_user.special_rank = request.form.get('special_rank', '')
            target_user.save(); flash('تم التعديل الإمبراطوري!', 'success')
        except: pass
    return redirect(url_for('hunter_profile', target_id=target_id))
@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    sender = User.objects(id=session['user_id']).first()
    receiver = User.objects(hunter_id=target_id).exclude('avatar').first()
    if getattr(sender, 'status', '') != 'active' or not receiver or getattr(receiver, 'status', '') != 'active' or receiver.hunter_id not in getattr(sender, 'friends', []): return redirect(request.referrer or url_for('home'))
    transfer_type = request.form.get('transfer_type')
    if transfer_type == 'points':
        try:
            amt = int(request.form.get('amount') or 0)
            if 0 < amt <= sender.points: 
                sender.points -= amt; receiver.points += amt; sender.loyalty_points = getattr(sender, 'loyalty_points', 0) + 2
                sender.save(); receiver.save(); flash('تم التحويل!', 'success')
        except: pass
    elif transfer_type == 'item':
        itm = request.form.get('item_name')
        if itm in getattr(sender, 'inventory', []): 
            sender.inventory.remove(itm); receiver.inventory.append(itm); sender.loyalty_points = getattr(sender, 'loyalty_points', 0) + 5
            sender.save(); receiver.save(); flash('تم الإرسال!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    attacker = User.objects(id=session['user_id']).first()
    if getattr(attacker, 'status', '') != 'active': return redirect(request.referrer or url_for('home'))
    target = User.objects(hunter_id=target_id).exclude('avatar').first()
    settings = GlobalSettings.objects(setting_name='main_config').exclude('banner_url').first()
    item_name = request.form.get('item_name')
    item = StoreItem.objects(name=item_name).exclude('image').first()
    if not item or item_name not in getattr(attacker, 'inventory', []) or getattr(target, 'status', '') != 'active': return redirect(request.referrer or url_for('home'))
        
    now = datetime.utcnow(); item_type = getattr(item, 'item_type', '')
    if item_type == 'seal':
        if target.id == attacker.id:
            attacker.destroyed_seals = getattr(attacker, 'destroyed_seals', 0) + 1; attacker.inventory.remove(item_name)
            if attacker.destroyed_seals >= 4:
                if settings: settings.war_mode = False; settings.final_battle_mode = False; settings.save()
                User.objects(status='active').update(health=100); flash('دُمرت اللعنة النهائية!', 'success')
            else: flash('تم تدمير الختم!', 'success')
            attacker.save()
        return redirect(request.referrer or url_for('home'))

    is_combat_active = getattr(settings, 'war_mode', False) or getattr(settings, 'final_battle_mode', False)
    if item_type == 'weapon' and is_combat_active and target.hunter_id not in getattr(attacker, 'friends', []):
        if getattr(target, 'role', '') == 'admin' and not getattr(settings, 'final_battle_mode', False): flash('🛡️ الإمبراطور محصن!', 'error'); return redirect(request.referrer or url_for('home'))
        has_shield = False
        for inv_item in getattr(target, 'inventory', []):
            if 'درع' in inv_item or 'shield' in inv_item.lower(): target.inventory.remove(inv_item); has_shield = True; break
        if has_shield:
            flash('الهدف يمتلك درعاً!', 'error')
        else:
            target.health -= getattr(item, 'effect_amount', 0)
            if target.health <= 0: 
                has_totem = False
                if not getattr(settings, 'final_battle_mode', False) and not getattr(settings, 'floor3_mode_active', False):
                    for inv_item in getattr(target, 'inventory', []):
                        if 'طوطم' in inv_item or 'totem' in inv_item.lower(): target.inventory.remove(inv_item); has_totem = True; break
                if has_totem: target.health = 50; flash('استيقظ الهدف من الموت باستخدام طوطم الخلود!', 'error')
                else:
                    target.health = 0; target.status = 'eliminated'; GlobalSettings.objects(setting_name='main_config').update_inc(dead_count=1)
                    if getattr(target, 'role', '') == 'admin': GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=False, set__war_mode=False)
                    dead_total = getattr(settings, 'dead_count', 0) + 1
                    if getattr(settings, 'war_mode', False) and dead_total >= getattr(settings, 'war_kill_target', 15):
                        GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=False); User.objects(status='active', role='hunter', hunter_id__ne=1000).update(set__zone='الطابق 2')
            flash('تمت الضربة!', 'success')
        attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); target.save()
    elif item_type == 'heal':
        if target.id == attacker.id or target.hunter_id in getattr(attacker, 'friends', []):
            heal_amount = getattr(item, 'effect_amount', 0)
            if getattr(target, 'role', '') == 'admin': target.health += heal_amount
            else: target.health = min(100, target.health + heal_amount)
            if target.id != attacker.id: attacker.loyalty_points = getattr(attacker, 'loyalty_points', 0) + 5
            target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); flash('عُولج!', 'success')
    elif item_type == 'spy':
        if any('حجاب' in i or 'درع' in i for i in getattr(target, 'inventory', [])): attacker.inventory.remove(item_name); attacker.save(); flash('الهدف محصن!', 'error')
        else:
            attacker.tajis_eye_until = now + timedelta(hours=1); attacker.inventory.remove(item_name); attacker.save()
            flash('تجسست بنجاح!', 'success')
    elif item_type == 'steal':
        stolen_item = request.form.get('target_item')
        if stolen_item in getattr(target, 'inventory', []):
            if any('حجاب' in i or 'درع' in i or 'عباءة' in i for i in getattr(target, 'inventory', [])): attacker.inventory.remove(item_name); attacker.save(); flash('الهدف محمي!', 'error')
            else:
                target.inventory.remove(stolen_item); attacker.inventory.append(stolen_item); attacker.inventory.remove(item_name); attacker.intelligence_points = getattr(attacker, 'intelligence_points', 0) + 5
                attacker.save(); target.save(); flash('تمت السرقة!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/altar', methods=['GET', 'POST'])
@login_required
def altar():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': return redirect(url_for('home'))
    if request.method == 'POST':
        spell_word = request.form.get('spell_word', '').strip()
        spell = SpellConfig.objects(spell_word=spell_word).first()
        settings = GlobalSettings.objects(setting_name='main_config').exclude('banner_url').first()
        if not spell: flash('كلمة لا معنى لها... المذبح صامت.', 'error'); return redirect(url_for('altar'))
        stype = getattr(spell, 'spell_type', ''); val = getattr(spell, 'effect_value', 0); is_perc = getattr(spell, 'is_percentage', False)
        if stype == 'hp_loss':
            loss = int(user.health * (val / 100.0)) if is_perc else val
            user.health -= loss
            if user.health <= 0: user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'أحرقته تعويذة'
            flash('لقد دفعت ضريبة الدم!', 'error')
        elif stype == 'hp_gain': gain = int(user.health * (val / 100.0)) if is_perc else val; user.health = min(100, user.health + gain); flash('تسري طاقة غريبة في جسدك!', 'success')
        elif stype == 'points_loss': loss = int(user.points * (val / 100.0)) if is_perc else val; user.points = max(0, user.points - loss); flash('تبخرت أموالك أمام عينيك!', 'error')
        elif stype == 'item_reward':
            item_name = getattr(spell, 'item_name', '')
            if item_name: user.inventory.append(item_name); flash(f'ظهرت أداة ({item_name}) بين يديك!', 'success')
        elif stype == 'unlock_lore': user.unlocked_lore_room = True; flash('ظهرت نقوش بونغليف سيفار لك الآن.', 'success')
        elif stype == 'unlock_top': user.unlocked_top_room = True; flash('قاعة الأساطير ترحب بك.', 'success')
        elif stype == 'kill_emperor':
            if getattr(settings, 'final_battle_mode', False):
                emperor = User.objects(hunter_id=1000).first()
                if emperor:
                    emperor.health = 0; emperor.status = 'eliminated'; emperor.save(); GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=False, set__war_mode=False)
                    flash('سقط الإمبراطور! أنت الحاكم الجديد!', 'success')
            else: flash('التعويذة صحيحة، لكن الإمبراطور محصن حالياً.', 'error')
        user.save()
        return redirect(url_for('altar'))
    return render_template('altar.html')

# 🚀 تحويل غرفة السجلات إلى بونغليف سيفار
@app.route('/poneglyph')
@login_required
def poneglyph():
    user = User.objects(id=session['user_id']).exclude('avatar').first()
    if getattr(user, 'status', '') != 'active' or not getattr(user, 'unlocked_lore_room', False): return redirect(url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    poneglyph_text = getattr(settings, 'poneglyph_text', 'نقوش بونغليف سيفار ممسوحة حالياً...')
    return render_template('poneglyph.html', poneglyph_text=poneglyph_text)

@app.route('/top_room')
@login_required
def top_room():
    user = User.objects(id=session['user_id']).exclude('avatar').first()
    if getattr(user, 'status', '') != 'active' or not getattr(user, 'unlocked_top_room', False): return redirect(url_for('home'))
    top_iq = User.objects(hunter_id__ne=1000, status='active').exclude('avatar').order_by('-intelligence_points')[:10]
    top_loyal = User.objects(hunter_id__ne=1000, status='active').exclude('avatar').order_by('-loyalty_points')[:10]
    top_hp = User.objects(hunter_id__ne=1000, status='active').exclude('avatar').order_by('-health')[:10]
    return render_template('top_room.html', top_iq=top_iq, top_loyal=top_loyal, top_hp=top_hp)

@app.route('/friends', methods=['GET'])
@login_required
def friends():
    user = User.objects(id=session['user_id']).exclude('avatar').first()
    search_query = request.args.get('search')
    search_result = None
    if search_query: 
        if search_query.isdigit(): search_result = User.objects(hunter_id=int(search_query)).exclude('avatar').first()
        else: search_result = User.objects(username__icontains=search_query).exclude('avatar').first()
    friend_requests = User.objects(hunter_id__in=getattr(user, 'friend_requests', [])).exclude('avatar')
    friends_list = User.objects(hunter_id__in=getattr(user, 'friends', [])).exclude('avatar')
    return render_template('friends.html', user=user, search_result=search_result, friend_requests=friend_requests, friends=friends_list)

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': return redirect(request.referrer or url_for('home'))
    target = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
    if not target or getattr(target, 'status', '') != 'active': return redirect(request.referrer or url_for('home'))
    if getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target.hunter_id)).first()
        if getattr(target, 'role', '') == 'cursed_ghost' and trap: 
            user.points -= getattr(trap, 'trap_penalty_points', 0); user.intelligence_points -= 5; user.save()
            flash('أيقظت شبحاً ملعوناً!', 'error')
        elif trap and str(user.id) not in getattr(trap, 'winners_list', []) and getattr(trap, 'current_winners', 0) < getattr(trap, 'max_winners', 1):
            user.points += getattr(trap, 'reward_points', 0); user.stats_ghosts_caught = getattr(user, 'stats_ghosts_caught', 0) + 1; trap.current_winners = getattr(trap, 'current_winners', 0) + 1; trap.winners_list.append(str(user.id))
            user.intelligence_points += 10; user.save(); trap.save(); check_achievements(user); flash('اصطدت شبحاً!', 'success')
        return redirect(request.referrer or url_for('home'))
    if target.hunter_id not in getattr(user, 'friends', []) and user.hunter_id not in getattr(target, 'friend_requests', []):
        target.friend_requests.append(user.hunter_id); target.save(); flash('أُرسل الطلب', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': return redirect(request.referrer or url_for('home'))
    target = User.objects(hunter_id=target_id).first()
    if target:
        if user.hunter_id in getattr(target, 'friend_requests', []): target.friend_requests.remove(user.hunter_id)
        elif target.hunter_id in getattr(user, 'friends', []): 
            user.friends.remove(target.hunter_id); target.friends.remove(user.hunter_id); user.loyalty_points -= 20
        user.save(); target.save(); flash('تم الإلغاء', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': return redirect(request.referrer or url_for('home'))
    friend = User.objects(hunter_id=friend_id).first()
    if friend and friend.status == 'active' and friend_id in getattr(user, 'friend_requests', []):
        user.friend_requests.remove(friend_id); user.friends.append(friend_id); friend.friends.append(user.hunter_id)
        friend.save(); user.save(); check_achievements(user); flash('قُبل!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/news')
@login_required
def news():
    try: user = User.objects(id=session['user_id']).exclude('avatar').first(); User.objects(id=user.id).update_one(set__last_seen_news=datetime.utcnow())
    except: user = None
    return render_template('news.html', news_list=get_allowed_news(user))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if getattr(user, 'status', '') != 'active': flash('حسابك يحتاج تفعيل.', 'error'); return redirect(url_for('puzzles'))
        guess = request.form.get('guess'); puzzle = News.objects(id=request.form.get('puzzle_id')).exclude('image_data').first()
        if puzzle and str(guess) == str(getattr(puzzle, 'puzzle_answer', '')) and str(user.id) not in getattr(puzzle, 'winners_list', []):
            if getattr(puzzle, 'current_winners', 0) < getattr(puzzle, 'max_winners', 1):
                user.points += getattr(puzzle, 'reward_points', 0); user.stats_puzzles_solved = getattr(user, 'stats_puzzles_solved', 0) + 1; puzzle.winners_list.append(str(user.id)); puzzle.current_winners = getattr(puzzle, 'current_winners', 0) + 1
                user.intelligence_points += 10; user.save(); puzzle.save(); flash('إجابة صحيحة!', 'success')
            else: flash('نفدت الجوائز!', 'error')
        else: flash('إجابة خاطئة أو تم الحل مسبقاً.', 'error')
        return redirect(url_for('puzzles'))
    try: User.objects(id=user.id).update_one(set__last_seen_puzzles=datetime.utcnow())
    except: pass
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').exclude('image_data').order_by('-created_at'))

@app.route('/delete_puzzle/<puzzle_id>', methods=['POST'])
@admin_required
def delete_puzzle(puzzle_id):
    try: News.objects(id=puzzle_id).delete(); flash('تم الحذف!', 'success')
    except: pass
    return redirect(request.referrer or url_for('puzzles'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': return redirect(url_for('home'))
    try: puzzle = News.objects(id=puzzle_id).first()
    except: return redirect(url_for('home'))
    if puzzle and getattr(puzzle, 'puzzle_type', '') == 'quicksand_trap':
        user.quicksand_lock_until = datetime.utcnow() + timedelta(minutes=getattr(puzzle, 'trap_duration_minutes', 5)); user.intelligence_points -= 5; user.save()
        flash('وقعت في فخ الرمال!', 'error')
    elif puzzle and str(user.id) not in getattr(puzzle, 'winners_list', []) and getattr(puzzle, 'current_winners', 0) < getattr(puzzle, 'max_winners', 1):
        user.points += getattr(puzzle, 'reward_points', 0); puzzle.current_winners = getattr(puzzle, 'current_winners', 0) + 1; puzzle.winners_list.append(str(user.id))
        user.intelligence_points += 15; user.save(); puzzle.save(); flash('جائزة سرية!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).exclude('avatar').first()
    if request.method == 'POST':
        if getattr(user, 'status', '') != 'active': flash('حسابك قيد المراجعة.', 'error'); return redirect(url_for('declarations'))
        img = ''
        file = request.files.get('image_file')
        if file: img = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
        News(title=f"تصريح من {user.username}", content=request.form.get('content', '').strip(), image_data=img, category='declaration', author=user.username, status='approved' if getattr(user, 'role', '') == 'admin' else 'pending').save()
        flash('تم الإرسال', 'success'); return redirect(url_for('declarations'))
    try: User.objects(id=user.id).update_one(set__last_seen_decs=datetime.utcnow())
    except: pass
    approved_decs = News.objects(category='declaration', status='approved').order_by('-created_at')
    pending_decs = News.objects(category='declaration', status='pending') if getattr(user, 'role', '') == 'admin' else []
    my_pending_decs = News.objects(category='declaration', status='pending', author=user.username).order_by('-created_at')
    authors = set([d.author for d in approved_decs] + [d.author for d in pending_decs] + [d.author for d in my_pending_decs])
    users_query = User.objects(username__in=authors).only('username', 'hunter_id')
    avatars = {u.username: u.hunter_id for u in users_query}
    return render_template('declarations.html', approved_decs=approved_decs, pending_decs=pending_decs, my_pending_decs=my_pending_decs, current_user=user, avatars=avatars)

@app.route('/delete_declaration/<dec_id>', methods=['POST'])
@login_required
def delete_declaration(dec_id):
    user = User.objects(id=session['user_id']).first()
    dec = News.objects(id=dec_id).first()
    if dec and (dec.author == user.username or getattr(user, 'role', '') == 'admin'): dec.delete(); flash('تم الحذف!', 'success')
    return redirect(url_for('declarations'))

@app.route('/store')
@login_required
def store():
    try: user = User.objects(id=session['user_id']).exclude('avatar').first(); User.objects(id=user.id).update_one(set__last_seen_store=datetime.utcnow())
    except: pass
    return render_template('store.html', items=StoreItem.objects().exclude('image'))

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'status', '') != 'active': return redirect(url_for('store'))
    try: item = StoreItem.objects(id=item_id).first()
    except: return redirect(url_for('store'))
    if user and item and user.points >= item.price:
        user.points -= item.price
        if getattr(item, 'is_luck', False):
            outcome = random.randint(getattr(item, 'luck_min', 0), getattr(item, 'luck_max', 0)); user.points += outcome
            flash(f'النتيجة: {outcome}', 'success' if outcome >= 0 else 'error')
        elif getattr(item, 'is_mirage', False): 
            user.intelligence_points -= 10; flash(getattr(item, 'mirage_message', 'فخ!'), 'error')
        else: 
            user.inventory.append(item.name); user.stats_items_bought = getattr(user, 'stats_items_bought', 0) + 1; flash('تم الشراء!', 'success')
        user.save()
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated').exclude('avatar').order_by('-id'))

@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    user = User.objects(id=session['user_id']).first()
    settings = GlobalSettings.objects(setting_name='main_config').exclude('banner_url').first()
    if getattr(user, 'status', '') != 'active': return redirect(url_for('home'))
    if getattr(settings, 'gates_mode_active', False) and not getattr(settings, 'gates_selection_locked', False) and getattr(user, 'chosen_gate', 0) == 0:
        gate_num = int(request.form.get('gate_num') or 0); user.chosen_gate = gate_num; user.gate_status = 'waiting'; user.save()
        flash('تم التسجيل!', 'success')
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'gate_status', '') == 'testing': user.gate_test_answer = request.form.get('test_answer', ''); user.save(); flash('تم الإرسال', 'success')
    return redirect(url_for('home'))

@app.route('/submit_floor3_votes', methods=['POST'])
@login_required
def submit_floor3_votes():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'hunter_id', 0) == 1000 or getattr(user, 'has_voted', False) or getattr(user, 'status', '') != 'active': return redirect(url_for('home'))
    try:
        tids = [int(request.form.get(f'target_{i}')) for i in range(1, 6)]
        amts = [int(request.form.get(f'amount_{i}')) for i in range(1, 6)]
        if len(set(tids)) == 5 and sum(amts) == 100 and 1000 not in tids and user.hunter_id not in tids:
            for i, tid in enumerate(tids):
                target_user = User.objects(hunter_id=tid).first()
                if target_user: target_user.survival_votes = getattr(target_user, 'survival_votes', 0) + amts[i]; target_user.save()
            user.has_voted = True; user.save(); flash('تم التثبيت!', 'success')
        else: flash('خطأ في التوزيع!', 'error')
    except: pass
    return redirect(url_for('home'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    try: settings = GlobalSettings.objects(setting_name='main_config').exclude('banner_url').first() or GlobalSettings(setting_name='main_config').save()
    except: settings = None
        
    search_query = request.args.get('search_user', '').strip() 
    
    if request.method == 'POST':
        act = request.form.get('action')
        try:
            if act == 'moderate_dec':
                d = News.objects(id=request.form.get('dec_id')).first()
                if d: 
                    if request.form.get('decision') == 'approve': d.status = 'approved'; d.save()
                    else: d.delete()
            elif act == 'add_targeted_news': News(title=request.form.get('title'), content=request.form.get('content'), category='news', target_group=request.form.get('target_group')).save()
            elif act == 'setup_maintenance':
                dur = int(request.form.get('m_duration') or 0)
                if dur > 0: GlobalSettings.objects(setting_name='main_config').update_one(set__maintenance_mode=True, set__maintenance_until=datetime.utcnow() + timedelta(minutes=dur), set__maintenance_pages=request.form.getlist('m_pages'))
                else: GlobalSettings.objects(setting_name='main_config').update_one(set__maintenance_mode=False, set__maintenance_pages=[])
            elif act == 'toggle_war':
                new_state = not getattr(settings, 'war_mode', False)
                war_hours = int(request.form.get('war_hours') or 0)
                end_time = datetime.utcnow() + timedelta(hours=war_hours) if war_hours > 0 and new_state else None
                GlobalSettings.objects(setting_name='main_config').update_one(set__war_mode=new_state, set__war_end_time=end_time)
                if not new_state: User.objects(status='active').update(health=100)
            elif act == 'toggle_final_battle': GlobalSettings.objects(setting_name='main_config').update_one(set__final_battle_mode=not getattr(settings, 'final_battle_mode', False))
            elif act == 'set_admin_hp': User.objects(hunter_id=1000).update(health=int(request.form.get('admin_hp') or 100))
            elif act == 'add_news':
                News(title=request.form.get('title'), content=request.form.get('content'), category='puzzle' if request.form.get('puzzle_type') != 'none' else 'news', puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1)).save()
            elif act == 'add_standalone_puzzle':
                puzzle_type = request.form.get('puzzle_type'); puzzle_answer = request.form.get('puzzle_answer', '')
                News(title="لغز مخفي", content="خفي", category='hidden', puzzle_type=puzzle_type, puzzle_answer=puzzle_answer, reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1), trap_duration_minutes=int(request.form.get('trap_duration') or 0), trap_penalty_points=int(request.form.get('trap_penalty') or 0)).save()
                if puzzle_type in ['fake_account', 'cursed_ghost']: User(hunter_id=int(puzzle_answer), username=f"شبح_{puzzle_answer}", password_hash="dummy", role='ghost' if puzzle_type == 'fake_account' else 'cursed_ghost', status='active', avatar='👻').save()
            elif act == 'add_store_item':
                im = ''
                file = request.files.get('item_image')
                if file: im = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
                StoreItem(name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price') or 0), item_type=request.form.get('item_type'), effect_amount=int(request.form.get('effect_amount') or 0), is_mirage=bool(request.form.get('is_mirage')), mirage_message=request.form.get('mirage_message', ''), is_luck=bool(request.form.get('is_luck')), luck_min=int(request.form.get('luck_min') or 0), luck_max=int(request.form.get('luck_max') or 0), image=im).save()
            elif act == 'add_spell': SpellConfig(spell_word=request.form.get('spell_word'), spell_type=request.form.get('spell_type'), effect_value=int(request.form.get('effect_value') or 0), is_percentage=bool(request.form.get('is_percentage')), item_name=request.form.get('item_name', '')).save()
            elif act == 'bulk_action':
                bt = request.form.get('bulk_type')
                for uid in request.form.getlist('selected_users'):
                    u = User.objects(id=uid).first()
                    if u and getattr(u, 'hunter_id', 0) != 1000:
                        if bt == 'hard_delete': u.delete()
                        elif bt == 'activate': u.status = 'active'; u.health = 100; u.save()
                        elif bt == 'eliminate': u.status = 'eliminated'; u.freeze_reason = request.form.get('bulk_reason', 'بأمر الإدارة'); u.save()
                        elif bt == 'move_zone': u.zone = request.form.get('bulk_zone', 'الطابق 1'); u.save()
            elif act == 'setup_gates': GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=True, set__gates_selection_locked=bool(request.form.get('locked')), set__gates_description=request.form.get('desc', ''), set__gate_1_name=request.form.get('g1', ''), set__gate_2_name=request.form.get('g2', ''), set__gate_3_name=request.form.get('g3', ''), set__gates_test_message=request.form.get('test_msg', ''))
            elif act == 'close_gates_mode': GlobalSettings.objects(setting_name='main_config').update_one(set__gates_mode_active=False)
            elif act == 'judge_gates':
                # 🚀 دعم الخيار الثالث للغرفة
                fates = {1: request.form.get('fate_1'), 2: request.form.get('fate_2'), 3: request.form.get('fate_3')}
                for u in User.objects(gate_status='waiting', status='active'):
                    fate = fates.get(str(getattr(u, 'chosen_gate', 0))) 
                    if fate == 'pass': u.gate_status = 'passed'; u.zone = 'الطابق 1'
                    elif fate == 'kill': u.status = 'eliminated'; u.freeze_reason = 'البوابة التهمته'
                    elif fate == 'test': u.gate_status = 'testing'
                    u.save()
            elif act == 'judge_test_user':
                u = User.objects(id=request.form.get('user_id')).first()
                if u: 
                    if request.form.get('decision') == 'pass': u.gate_status = 'passed'; u.zone = 'الطابق 1'
                    else: u.status = 'eliminated'; u.freeze_reason = 'فشل في الاختبار'
                    u.save()
            elif act == 'toggle_floor3': 
                new_state = not getattr(settings, 'floor3_mode_active', False)
                vote_hours = int(request.form.get('vote_hours') or 0)
                top_n = int(request.form.get('top_n', 5))
                end_time = datetime.utcnow() + timedelta(hours=vote_hours) if vote_hours > 0 and new_state else None
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=new_state, set__vote_end_time=end_time, set__vote_top_n=top_n)
            elif act == 'punish_floor3_slackers':
                slackers = User.objects(has_voted=False, status='active', role='hunter')
                active_voters = User.objects(has_voted=True, status='active', role='hunter')
                if slackers.count() > 0 and active_voters.count() > 0:
                    bonus = (slackers.count() * 100) // active_voters.count()
                    for v in active_voters: v.survival_votes = getattr(v, 'survival_votes', 0) + bonus; v.save()
                for s_user in slackers: s_user.status = 'eliminated'; s_user.freeze_reason = 'لم يصوت'; s_user.save()
            elif act == 'advance_voters':
                top_n = int(request.form.get('top_n', 5))
                for l in User.objects(status='active', role='hunter').order_by('-survival_votes')[:top_n]: l.zone = 'المعركة الأخيرة'; l.save()
                GlobalSettings.objects(setting_name='main_config').update_one(set__floor3_mode_active=False)
            elif act == 'update_war_settings':
                GlobalSettings.objects(setting_name='main_config').update_one(set__bleed_rate_minutes=int(request.form.get('bleed_rate_minutes') or 60), set__bleed_amount=int(request.form.get('bleed_amount') or 1), set__safe_time_minutes=int(request.form.get('safe_time_minutes') or 120), set__war_kill_target=int(request.form.get('war_kill_target') or 15))
            elif act == 'update_home_settings':
                file = request.files.get('banner_file')
                if file and file.filename != '': 
                    b_url = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
                    GlobalSettings.objects(setting_name='main_config').update_one(set__home_title=request.form.get('home_title', 'البوابة'), set__banner_url=b_url)
                else: GlobalSettings.objects(setting_name='main_config').update_one(set__home_title=request.form.get('home_title', 'البوابة'))
            elif act == 'toggle_global_news': GlobalSettings.objects(setting_name='main_config').update_one(set__global_news_active=not getattr(settings, 'global_news_active', False), set__global_news_text=request.form.get('global_news_text', ''))
            
            # 🚀 كتابة بونغليف سيفار
            elif act == 'update_poneglyph':
                GlobalSettings.objects(setting_name='main_config').update_one(set__poneglyph_text=request.form.get('poneglyph_text', ''))
                flash('تم نقش البونغليف بنجاح!', 'success')
                
        except: pass
        return redirect(url_for('admin_panel', search_user=search_query))
    
    users_query = User.objects(hunter_id__ne=1000).exclude('avatar')
    if search_query:
        if search_query.isdigit(): users_query = users_query.filter(hunter_id=int(search_query))
        else: users_query = users_query.filter(username__icontains=search_query)
    
    users = users_query.order_by('-last_active')[:100]
    gate_stats = {1: User.objects(chosen_gate=1, status='active').count(), 2: User.objects(chosen_gate=2, status='active').count(), 3: User.objects(chosen_gate=3, status='active').count()}
    floor3_leaders = User.objects(status='active', role='hunter').exclude('avatar').order_by('-survival_votes')[:getattr(settings, 'vote_top_n', 5)] if getattr(settings, 'floor3_mode_active', False) else []
        
    return render_template('admin.html', users=users, settings=settings, test_users=User.objects(gate_status='testing', status='active').exclude('avatar'), gate_stats=gate_stats, floor3_leaders=floor3_leaders, search_query=search_query)

if __name__ == '__main__': 
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
