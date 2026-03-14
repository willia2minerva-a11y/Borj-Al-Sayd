from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, BattleLog
from functools import wraps
from datetime import datetime, timedelta
import os, base64, random, math, json

app = Flask(__name__)
app.config['MONGODB_SETTINGS'] = {'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db')}
app.config['SECRET_KEY'] = 'sephar-maze-emperor-ultimate-v5'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
db.init_app(app)

class ActionLog(db.Document):
    meta = {'strict': False}
    action_text = db.StringField()
    category = db.StringField()
    created_at = db.DateTimeField(default=datetime.utcnow)
    log_date = db.StringField(default=lambda: datetime.utcnow().strftime('%Y-%m-%d'))

def log_action(text, cat):
    try: ActionLog(action_text=text, category=cat).save()
    except: pass

def check_achievements(user):
    try:
        new_ach = []
        if getattr(user, 'stats_ghosts_caught', 0) >= 5 and 'صائد الأشباح 👻' not in user.achievements:
            user.achievements.append('صائد الأشباح 👻'); new_ach.append('صائد الأشباح 👻')
        if getattr(user, 'stats_puzzles_solved', 0) >= 5 and 'حكيم سيفار 📜' not in user.achievements:
            user.achievements.append('حكيم سيفار 📜'); new_ach.append('حكيم سيفار 📜')
        if getattr(user, 'stats_items_bought', 0) >= 5 and 'التاجر الخبير 🐪' not in user.achievements:
            user.achievements.append('التاجر الخبير 🐪'); new_ach.append('التاجر الخبير 🐪')
        if len(user.friends) >= 5 and 'حليف القوم 🤝' not in user.achievements:
            user.achievements.append('حليف القوم 🤝'); new_ach.append('حليف القوم 🤝')
        if new_ach: flash(f'🏆 إنجاز جديد: {", ".join(new_ach)}', 'success')
        user.save()
    except: pass

def check_lazy_death_and_bleed(user, settings):
    try:
        if not user or getattr(user, 'role', '') == 'admin' or getattr(user, 'status', '') != 'active': return
        now = datetime.utcnow()
        last_act = getattr(user, 'last_active', None) or getattr(user, 'created_at', now) or now
        if (now - last_act).total_seconds() / 3600.0 > 72:
            user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'ابتلعته الرمال لغيابه 72 ساعة'
            log_action(f"💀 هلك {user.username} بسبب غياب 72 ساعة", "system"); user.save(); return
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
                    if user.health <= 0:
                        user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'نزف حتى الموت في المعركة'
                        settings.dead_count = getattr(settings, 'dead_count', 0) + 1; settings.save()
                        log_action(f"🩸 نزف {user.username} حتى الموت", "combat")
                    user.save()
    except: pass

@app.before_request
def check_locks_and_status():
    if request.endpoint in ['static', 'login', 'logout', 'register']: return
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    user = User.objects(id=session.get('user_id')).first() if 'user_id' in session else None
    if getattr(settings, 'maintenance_mode', False):
        if getattr(settings, 'maintenance_until', None) and datetime.utcnow() > settings.maintenance_until:
            settings.maintenance_mode = False; settings.maintenance_pages = []; settings.save()
        elif not user or getattr(user, 'role', '') != 'admin':
            m_pages = getattr(settings, 'maintenance_pages', [])
            if 'all' in m_pages or request.endpoint in m_pages:
                return render_template('locked.html', message='جاري ترميم ونقش هذه الصفحة. ستعود قريباً ⏳')
    if user:
        user.last_active = datetime.utcnow(); user.save()
        check_lazy_death_and_bleed(user, settings)
        quicksand = getattr(user, 'quicksand_lock_until', None)
        if quicksand and datetime.utcnow() < quicksand:
            tl = quicksand - datetime.utcnow()
            return render_template('locked.html', message=f'مقيّد في الرمال لـ {tl.seconds // 60}د و {tl.seconds % 60}ث')
        if getattr(user, 'gate_status', '') == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']:
            return render_template('gate_test.html', message=getattr(settings, 'gates_test_message', 'الاختبار'), user=user)

@app.context_processor
def inject_notifications():
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'current_user': None, 'war_settings': None, 'battle_logs': []}
    settings = GlobalSettings.objects(setting_name='main_config').first()
    notifs['war_settings'] = settings
    if settings and (getattr(settings, 'war_mode', False) or getattr(settings, 'final_battle_mode', False)):
        notifs['battle_logs'] = BattleLog.objects().order_by('-created_at')[:3]
    if 'user_id' in session:
        user = User.objects(id=session['user_id']).first()
        if user:
            notifs['current_user'] = user; now = datetime.utcnow()
            notifs['un_news'] = News.objects(category='news', status='approved', created_at__gt=getattr(user, 'last_seen_news', now)).count()
            notifs['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=getattr(user, 'last_seen_puzzles', now)).count()
            notifs['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=getattr(user, 'last_seen_decs', now)).count()
            notifs['un_store'] = StoreItem.objects(created_at__gt=getattr(user, 'last_seen_store', now)).count()
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

@app.route('/')
def home():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    user = User.objects(id=session.get('user_id')).first() if 'user_id' in session else None
    news_query = db.Q(category='news', status='approved', target_group='all')
    if user:
        if getattr(user, 'gate_status', '') == 'testing': news_query |= db.Q(target_group='testing')
        if getattr(user, 'status', '') == 'eliminated': news_query |= db.Q(target_group='ghosts')
        if getattr(user, 'role', '') == 'hunter': news_query |= db.Q(target_group='hunters')
    latest_news = News.objects(news_query).order_by('-created_at').first()
    latest_dec = News.objects(category='declaration', status='approved').order_by('-created_at').first()
    last_frozen = User.objects(status='eliminated').order_by('-id').first()
    hunters_list = []
    if settings and getattr(settings, 'floor3_mode_active', False):
        hunters = User.objects(status='active', role='hunter', hunter_id__ne=1000)
        hunters_list = [{'id': h.hunter_id, 'name': h.username} for h in hunters]
    return render_template('index.html', settings=settings, news=latest_news, dec=latest_dec, last_frozen=last_frozen, active_hunters_json=json.dumps(hunters_list))

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
        User(hunter_id=new_id, username=request.form['username'], password_hash=generate_password_hash(request.form['password']), role='admin' if new_id==1000 else 'hunter').save()
        log_action(f"✨ رحالة جديد انضم: {request.form['username']} (#{new_id})", "system")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session.permanent = True; session['user_id'] = str(user.id); session['role'] = getattr(user, 'role', 'hunter')
            log_action(f"🔑 {user.username} دخل المتاهة", "system")
            return redirect(url_for('home'))
        flash('بياناتك خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).first(); settings = GlobalSettings.objects(setting_name='main_config').first()
    my_items = StoreItem.objects(name__in=user.inventory) if getattr(user, 'inventory', None) else []
    my_seals = [i for i in my_items if getattr(i, 'item_type', '') == 'seal']
    return render_template('profile.html', user=user, banner_url=getattr(settings, 'banner_url', ''), my_items=my_items, my_seals=my_seals)

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first(); action = request.form.get('action'); now = datetime.utcnow()
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
        else: user.username = new_name; user.last_name_change = now; flash('تم تغيير الهوية بنجاح!', 'success')
    elif action == 'change_password':
        old_pw = request.form.get('old_password'); new_pw = request.form.get('new_password'); confirm_pw = request.form.get('confirm_password')
        last_pw_change = getattr(user, 'last_password_change', None)
        if last_pw_change and (now - last_pw_change).days < 1: flash('يُسمح بتغيير كلمة السر مرة واحدة كل 24 ساعة!', 'error')
        elif not check_password_hash(user.password_hash, old_pw): flash('كلمة السر القديمة غير صحيحة!', 'error')
        elif new_pw != confirm_pw: flash('كلمتا السر الجديدتان غير متطابقتين!', 'error')
        else: user.password_hash = generate_password_hash(new_pw); user.last_password_change = now; log_action(f"🔒 قام {user.username} بتغيير كلمة السر", "system"); flash('تم تغيير كلمة السر بنجاح!', 'success')
    user.save(); return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']: return redirect(url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    check_lazy_death_and_bleed(target_user, settings)
    current_user = User.objects(id=session['user_id']).first()
    my_items = StoreItem.objects(name__in=current_user.inventory) if getattr(current_user, 'inventory', None) else []
    return render_template('hunter_profile.html', target_user=target_user, banner_url=getattr(settings, 'banner_url', ''), my_weapons=[i for i in my_items if getattr(i, 'item_type', '')=='weapon'], my_heals=[i for i in my_items if getattr(i, 'item_type', '')=='heal'], my_spies=[i for i in my_items if getattr(i, 'item_type', '')=='spy'], my_steals=[i for i in my_items if getattr(i, 'item_type', '')=='steal'])

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
            target_user.save(); flash('تم التعديل الإمبراطوري!', 'success')
        except: flash('خطأ في الإدخال', 'error')
    return redirect(url_for('hunter_profile', target_id=target_id))

@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    sender = User.objects(id=session['user_id']).first(); receiver = User.objects(hunter_id=target_id).first()
    if sender.status != 'active' or not receiver or receiver.status != 'active' or receiver.hunter_id not in sender.friends: return redirect(request.referrer or url_for('home'))
    ttype = request.form.get('transfer_type')
    if ttype == 'points':
        try:
            amt = int(request.form.get('amount') or 0)
            if 0 < amt <= sender.points: 
                sender.points -= amt; receiver.points += amt; sender.save(); receiver.save()
                log_action(f"📦 {sender.username} هرّب {amt} نقطة إلى {receiver.username}", "social"); flash('تم التهريب!', 'success')
        except: pass
    elif ttype == 'item':
        itm = request.form.get('item_name')
        if itm in sender.inventory: 
            sender.inventory.remove(itm); receiver.inventory.append(itm); sender.save(); receiver.save()
            log_action(f"📦 {sender.username} أرسل أداة ({itm}) إلى {receiver.username}", "social"); flash('تم الإرسال!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    attacker = User.objects(id=session['user_id']).first()
    if attacker.status != 'active': return redirect(request.referrer or url_for('home'))
    target = User.objects(hunter_id=target_id).first(); settings = GlobalSettings.objects(setting_name='main_config').first()
    item_name = request.form.get('item_name'); item = StoreItem.objects(name=item_name).first()
    if not item or item_name not in attacker.inventory or target.status != 'active': return redirect(request.referrer or url_for('home'))
    now = datetime.utcnow()
    
    if getattr(item, 'item_type', '') == 'seal':
        if target.id == attacker.id:
            attacker.destroyed_seals = getattr(attacker, 'destroyed_seals', 0) + 1; attacker.inventory.remove(item_name)
            if attacker.destroyed_seals >= 4:
                if settings: settings.war_mode = False; settings.final_battle_mode = False; settings.save()
                User.objects(status='active').update(health=100); flash('دُمرت اللعنة النهائية!', 'success')
                log_action(f"🛡️ {attacker.username} دمر الختم الرابع وأنهى الحرب!", "system")
            else: flash('تم تدمير الختم!', 'success')
            attacker.save()
        return redirect(request.referrer or url_for('home'))

    is_combat_active = getattr(settings, 'war_mode', False) or getattr(settings, 'final_battle_mode', False)
    
    if getattr(item, 'item_type', '') == 'weapon' and is_combat_active and target.hunter_id not in attacker.friends:
        if getattr(target, 'role', '') == 'admin' and not getattr(settings, 'final_battle_mode', False):
            flash('🛡️ الإمبراطور محصن في الحرب الشاملة! فقط في المعركة الأخيرة يمكنك استهدافه.', 'error')
            return redirect(request.referrer or url_for('home'))
            
        target.health -= getattr(item, 'effect_amount', 0)
        log_action(f"⚔️ {attacker.username} طعن {target.username} بـ {item.name}", "combat")
        if target.health <= 0: 
            target.health = 0; target.status = 'eliminated'; settings.dead_count = getattr(settings, 'dead_count', 0) + 1; settings.save()
            log_action(f"💀 {target.username} هلك على يد {attacker.username}", "combat")
        BattleLog(victim_name=target.username, weapon_name=item.name, remaining_hp=target.health).save()
        target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); flash('تمت الضربة!', 'success')
            
    elif getattr(item, 'item_type', '') == 'heal':
        if target.id == attacker.id or target.hunter_id in attacker.friends:
            target.health = target.health + getattr(item, 'effect_amount', 0) if getattr(target, 'role', '') == 'admin' else min(100, target.health + getattr(item, 'effect_amount', 0))
            log_action(f"🧪 {attacker.username} عالج {target.username} بـ {item.name}", "combat")
            target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); flash('عُولج!', 'success')

    elif getattr(item, 'item_type', '') == 'spy':
        if any('حجاب' in i or 'درع' in i for i in target.inventory): 
            attacker.inventory.remove(item_name); attacker.save(); flash('الهدف محصن!', 'error')
        else:
            attacker.tajis_eye_until = now + timedelta(hours=1); attacker.inventory.remove(item_name); attacker.save()
            log_action(f"👁️ {attacker.username} فتح عين تاجيس على {target.username}", "social"); flash('فتحت عين تاجيس!', 'success')

    elif getattr(item, 'item_type', '') == 'steal':
        stolen_item = request.form.get('target_item')
        if stolen_item in target.inventory:
            if any('حجاب' in i or 'درع' in i or 'عباءة' in i for i in target.inventory): 
                attacker.inventory.remove(item_name); attacker.save(); flash('الهدف محمي! احترقت يدك.', 'error')
            else:
                target.inventory.remove(stolen_item); attacker.inventory.append(stolen_item); attacker.inventory.remove(item_name)
                attacker.save(); target.save(); log_action(f"🖐️ {attacker.username} سرق {stolen_item} من {target.username}", "social"); flash('تمت السرقة بنجاح!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/friends', methods=['GET'])
@login_required
def friends():
    user = User.objects(id=session['user_id']).first(); sq = request.args.get('search'); sr = None
    if sq: sr = User.objects(hunter_id=int(sq)).first() if sq.isdigit() else User.objects(username__icontains=sq).first()
    return render_template('friends.html', user=user, search_result=sr, friend_requests=User.objects(hunter_id__in=getattr(user, 'friend_requests', [])), friends=User.objects(hunter_id__in=getattr(user, 'friends', [])))

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = User.objects(id=session['user_id']).first(); target = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
    if not target or target.status != 'active': return redirect(request.referrer or url_for('home'))
    if getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target.hunter_id)).first()
        if getattr(target, 'role', '') == 'cursed_ghost' and trap: 
            user.points -= getattr(trap, 'trap_penalty_points', 0); user.save(); log_action(f"💀 {user.username} وقع في فخ شبح ملعون", "puzzle"); flash('أيقظت شبحاً ملعوناً!', 'error')
        elif trap and str(user.id) not in getattr(trap, 'winners_list', []) and getattr(trap, 'current_winners', 0) < getattr(trap, 'max_winners', 1):
            user.points += getattr(trap, 'reward_points', 0); user.stats_ghosts_caught = getattr(user, 'stats_ghosts_caught', 0) + 1
            trap.current_winners = getattr(trap, 'current_winners', 0) + 1; trap.winners_list.append(str(user.id)); user.save(); trap.save()
            log_action(f"👻 {user.username} اصطاد شبح مرشد", "puzzle"); check_achievements(user); flash('اصطدت شبحاً!', 'success')
        return redirect(request.referrer or url_for('home'))
    if target.hunter_id not in user.friends and user.hunter_id not in target.friend_requests:
        target.friend_requests.append(user.hunter_id); target.save(); log_action(f"🤝 {user.username} طلب تحالف مع {target.username}", "social"); flash('أُرسل الطلب', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = User.objects(id=session['user_id']).first(); target = User.objects(hunter_id=target_id).first()
    if target:
        if user.hunter_id in target.friend_requests: target.friend_requests.remove(user.hunter_id)
        elif target.hunter_id in user.friends: 
            user.friends.remove(target.hunter_id); target.friends.remove(user.hunter_id); log_action(f"💔 انهار التحالف بين {user.username} و {target.username}", "social")
        user.save(); target.save(); flash('تم الإلغاء', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = User.objects(id=session['user_id']).first(); f = User.objects(hunter_id=friend_id).first()
    if f and f.status == 'active' and friend_id in user.friend_requests:
        user.friend_requests.remove(friend_id); user.friends.append(friend_id); f.friends.append(user.hunter_id); f.save(); user.save()
        log_action(f"🤝 نشأ تحالف بين {user.username} و {f.username}", "social"); check_achievements(user); flash('قُبل!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/news')
@login_required
def news():
    user = User.objects(id=session['user_id']).first(); user.last_seen_news = datetime.utcnow(); user.save()
    news_q = db.Q(category='news', status='approved', target_group='all')
    if getattr(user, 'gate_status', '') == 'testing': news_q |= db.Q(target_group='testing')
    if getattr(user, 'status', '') == 'eliminated': news_q |= db.Q(target_group='ghosts')
    if getattr(user, 'role', '') == 'hunter': news_q |= db.Q(target_group='hunters')
    return render_template('news.html', news_list=News.objects(news_q).order_by('-created_at'))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        guess = request.form.get('guess'); puz = News.objects(id=request.form.get('puzzle_id')).first()
        if puz and guess == getattr(puz, 'puzzle_answer', '') and str(user.id) not in getattr(puz, 'winners_list', []):
            if getattr(puz, 'current_winners', 0) < getattr(puz, 'max_winners', 1):
                user.points += getattr(puz, 'reward_points', 0); user.stats_puzzles_solved = getattr(user, 'stats_puzzles_solved', 0) + 1
                puz.winners_list.append(str(user.id)); puz.current_winners = getattr(puz, 'current_winners', 0) + 1; user.save(); puz.save()
                log_action(f"🧩 {user.username} حل لغز ({puz.title})", "puzzle"); flash('إجابة صحيحة!', 'success')
            else: flash('نفدت الجوائز!', 'error')
        else: flash('إجابة خاطئة أو تم الحل مسبقاً.', 'error')
        return redirect(url_for('puzzles'))
    user.last_seen_puzzles = datetime.utcnow(); user.save()
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/delete_puzzle/<puzzle_id>', methods=['POST'])
@admin_required
def delete_puzzle(puzzle_id):
    try: News.objects(id=puzzle_id).delete(); flash('تم طمس اللغز!', 'success')
    except: pass
    return redirect(url_for('puzzles'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    try: puz = News.objects(id=puzzle_id).first()
    except: return redirect(url_for('home'))
    if puz and getattr(puz, 'puzzle_type', '') == 'quicksand_trap':
        user.quicksand_lock_until = datetime.utcnow() + timedelta(minutes=getattr(puz, 'trap_duration_minutes', 5))
        user.save(); log_action(f"🕸️ {user.username} وقع في فخ رمال", "puzzle"); flash('وقعت في فخ الرمال!', 'error')
    elif puz and str(user.id) not in getattr(puz, 'winners_list', []) and getattr(puz, 'current_winners', 0) < getattr(puz, 'max_winners', 1):
        user.points += getattr(puz, 'reward_points', 0); puz.current_winners = getattr(puz, 'current_winners', 0) + 1; puz.winners_list.append(str(user.id))
        user.save(); puz.save(); log_action(f"🎁 {user.username} عثر على رابط سري", "puzzle"); flash('جائزة سرية!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        img = ''; file = request.files.get('image_file')
        if file: img = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
        News(content=request.form.get('content', '').strip(), image_data=img, category='declaration', author=user.username, status='approved' if getattr(user, 'role', '') == 'admin' else 'pending').save()
        log_action(f"📢 {user.username} أرسل تصريحاً للمراجعة", "social"); flash('تم الإرسال', 'success'); return redirect(url_for('declarations'))
    user.last_seen_decs = datetime.utcnow(); user.save()
    appr = News.objects(category='declaration', status='approved').order_by('-created_at')
    pend = News.objects(category='declaration', status='pending') if getattr(user, 'role', '') == 'admin' else []
    my_pend = News.objects(category='declaration', status='pending', author=user.username).order_by('-created_at')
    return render_template('declarations.html', approved_decs=appr, pending_decs=pend, my_pending_decs=my_pend, current_user=user)

@app.route('/delete_declaration/<dec_id>', methods=['POST'])
@login_required
def delete_declaration(dec_id):
    user = User.objects(id=session['user_id']).first(); dec = News.objects(id=dec_id).first()
    if dec and (dec.author == user.username or getattr(user, 'role', '') == 'admin'): dec.delete(); flash('تم الحذف', 'success')
    return redirect(url_for('declarations'))

@app.route('/store')
@login_required
def store():
    user = User.objects(id=session['user_id']).first(); user.last_seen_store = datetime.utcnow(); user.save()
    return render_template('store.html', items=StoreItem.objects())

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    user = User.objects(id=session['user_id']).first(); 
    try: item = StoreItem.objects(id=item_id).first()
    except: return redirect(url_for('store'))
    if user and item and user.points >= item.price:
        user.points -= item.price
        if getattr(item, 'is_luck', False):
            outcome = random.randint(getattr(item, 'luck_min', 0), getattr(item, 'luck_max', 0)); user.points += outcome
            log_action(f"🎲 لعب {user.username} بصندوق حظ ونتيجته: {outcome}", "puzzle")
            flash(f'نتيجة الصندوق: {outcome}', 'success' if outcome >= 0 else 'error')
        elif getattr(item, 'is_mirage', False): 
            log_action(f"🕸️ {user.username} وقع في فخ سراب المتجر", "puzzle"); flash(getattr(item, 'mirage_message', 'فخ!'), 'error')
        else: 
            user.inventory.append(item.name); user.stats_items_bought = getattr(user, 'stats_items_bought', 0) + 1
            log_action(f"🐪 اشترى {user.username} {item.name}", "social"); flash('تم الشراء!', 'success')
        user.save()
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated').order_by('-id'))

@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    user = User.objects(id=session['user_id']).first(); settings = GlobalSettings.objects(setting_name='main_config').first()
    if getattr(settings, 'gates_mode_active', False) and not getattr(settings, 'gates_selection_locked', False) and getattr(user, 'chosen_gate', 0) == 0:
        gn = int(request.form.get('gate_num') or 0); user.chosen_gate = gn; user.gate_status = 'waiting'; user.save()
        log_action(f"🚪 اختار {user.username} البوابة {gn}", "system"); flash('تم التسجيل!', 'success')
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    user = User.objects(id=session['user_id']).first()
    if getattr(user, 'gate_status', '') == 'testing': 
        user.gate_test_answer = request.form.get('test_answer', ''); user.save()
        log_action(f"📝 {user.username} سلم إجابة الاختبار", "system")
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
                u = User.objects(hunter_id=tid).first()
                if u: u.survival_votes = getattr(u, 'survival_votes', 0) + amts[i]; u.save()
            user.has_voted = True; user.save(); log_action(f"🗳️ {user.username} ثبت أصواته للمحكمة", "puzzle"); flash('تم التثبيت!', 'success')
        else: flash('خطأ في التوزيع أو محاولة استهداف الإمبراطور!', 'error')
    except: pass
    return redirect(url_for('home'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    sel_date = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    logs = ActionLog.objects(log_date=sel_date).order_by('-created_at')
    
    if request.method == 'POST':
        act = request.form.get('action')
        try:
            if act == 'moderate_dec':
                d = News.objects(id=request.form.get('dec_id')).first()
                if d: (d.save(set__status='approved') if request.form.get('decision') == 'approve' else d.delete())
            elif act == 'add_targeted_news':
                News(title=request.form.get('title'), content=request.form.get('content'), category='news', target_group=request.form.get('target_group')).save()
            elif act == 'setup_maintenance':
                dur = int(request.form.get('m_duration') or 0); pages = request.form.getlist('m_pages')
                if dur > 0: settings.maintenance_mode = True; settings.maintenance_until = datetime.utcnow() + timedelta(minutes=dur); settings.maintenance_pages = pages
                else: settings.maintenance_mode = False; settings.maintenance_pages = []
            elif act == 'toggle_war':
                settings.war_mode = not getattr(settings, 'war_mode', False)
                if not settings.war_mode: User.objects(status='active').update(health=100); BattleLog.objects.delete()
            elif act == 'toggle_final_battle': settings.final_battle_mode = not getattr(settings, 'final_battle_mode', False)
            elif act == 'set_admin_hp':
                User.objects(hunter_id=1000).update(health=int(request.form.get('admin_hp') or 100))
            elif act == 'add_news':
                News(title=request.form.get('title'), content=request.form.get('content'), category='puzzle' if request.form.get('puzzle_type') != 'none' else 'news', puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1)).save()
            elif act == 'add_standalone_puzzle':
                News(title="لغز مخفي", content="خفي", category='hidden', puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer', ''), reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1), trap_duration_minutes=int(request.form.get('trap_duration') or 0), trap_penalty_points=int(request.form.get('trap_penalty') or 0)).save()
                if request.form.get('puzzle_type') in ['fake_account', 'cursed_ghost']:
                    User(hunter_id=int(request.form.get('puzzle_answer')), username=f"شبح_{request.form.get('puzzle_answer')}", password_hash="dummy", role='ghost' if request.form.get('puzzle_type') == 'fake_account' else 'cursed_ghost', status='active', avatar='👻').save()
            elif act == 'add_store_item':
                im = ''; file = request.files.get('item_image')
                if file: im = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
                StoreItem(name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price') or 0), item_type=request.form.get('item_type'), effect_amount=int(request.form.get('effect_amount') or 0), is_mirage=bool(request.form.get('is_mirage')), mirage_message=request.form.get('mirage_message', ''), is_luck=bool(request.form.get('is_luck')), luck_min=int(request.form.get('luck_min') or 0), luck_max=int(request.form.get('luck_max') or 0), image=im).save()
            elif act == 'bulk_action':
                bt = request.form.get('bulk_type')
                for uid in request.form.getlist('selected_users'):
                    u = User.objects(id=uid).first()
                    if u and getattr(u, 'hunter_id', 0) != 1000:
                        if bt == 'hard_delete': u.delete()
                        elif bt == 'activate': u.status = 'active'; u.health = 100; u.save()
                        elif bt == 'eliminate': u.status = 'eliminated'; u.freeze_reason = request.form.get('bulk_reason', 'بأمر الإدارة'); u.save()
            elif act == 'setup_gates':
                settings.gates_mode_active = True; settings.gates_selection_locked = bool(request.form.get('locked')); settings.gates_description = request.form.get('desc', ''); settings.gate_1_name = request.form.get('g1', ''); settings.gate_2_name = request.form.get('g2', ''); settings.gate_3_name = request.form.get('g3', ''); settings.gates_test_message = request.form.get('test_msg', '')
            elif act == 'close_gates_mode': settings.gates_mode_active = False
            elif act == 'judge_gates':
                fates = {1: request.form.get('fate_1'), 2: request.form.get('fate_2'), 3: request.form.get('fate_3')}
                for u in User.objects(gate_status='waiting', status='active'):
                    f = fates.get(getattr(u, 'chosen_gate', 0))
                    if f == 'pass': u.gate_status = 'passed'
                    elif f == 'kill': u.status = 'eliminated'; u.freeze_reason = 'البوابة التهمته'
                    elif f == 'test': u.gate_status = 'testing'
                    u.save()
            elif act == 'judge_test_user':
                u = User.objects(id=request.form.get('user_id')).first()
                if u: 
                    if request.form.get('decision') == 'pass': u.gate_status = 'passed'
                    else: u.status = 'eliminated'; u.freeze_reason = 'فشل بالاختبار'
                    u.save()
            elif act == 'toggle_floor3': settings.floor3_mode_active = not getattr(settings, 'floor3_mode_active', False)
            elif act == 'punish_floor3_slackers':
                slackers = User.objects(has_voted=False, status='active', role='hunter')
                active_voters = User.objects(has_voted=True, status='active', role='hunter')
                if slackers.count() > 0 and active_voters.count() > 0:
                    bonus = (slackers.count() * 100) // active_voters.count()
                    for v in active_voters: v.survival_votes = getattr(v, 'survival_votes', 0) + bonus; v.save()
                for s in slackers: s.status = 'eliminated'; s.freeze_reason = 'لم يصوت'; s.save()
            elif act == 'update_war_settings':
                settings.bleed_rate_minutes = int(request.form.get('bleed_rate_minutes') or 60); settings.bleed_amount = int(request.form.get('bleed_amount') or 1); settings.safe_time_minutes = int(request.form.get('safe_time_minutes') or 120)
            elif act == 'update_nav_names':
                settings.nav_home = request.form.get('nav_home', getattr(settings, 'nav_home', '')); settings.nav_profile = request.form.get('nav_profile', getattr(settings, 'nav_profile', '')); settings.nav_friends = request.form.get('nav_friends', getattr(settings, 'nav_friends', '')); settings.nav_news = request.form.get('nav_news', getattr(settings, 'nav_news', '')); settings.nav_puzzles = request.form.get('nav_puzzles', getattr(settings, 'nav_puzzles', '')); settings.nav_decs = request.form.get('nav_decs', getattr(settings, 'nav_decs', '')); settings.nav_store = request.form.get('nav_store', getattr(settings, 'nav_store', '')); settings.nav_grave = request.form.get('nav_grave', getattr(settings, 'nav_grave', ''))
            elif act == 'update_home_settings':
                settings.home_title = request.form.get('home_title', 'البوابة'); settings.home_color = request.form.get('home_color', 'var(--zone-0-black)')
                file = request.files.get('banner_file')
                if file and file.filename != '': settings.banner_url = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            elif act == 'toggle_global_news':
                settings.global_news_active = not getattr(settings, 'global_news_active', False); settings.global_news_text = request.form.get('global_news_text', '')
            settings.save()
        except: pass
        return redirect(url_for('admin_panel', date=sel_date))
    
    users = User.objects(hunter_id__ne=1000).order_by('hunter_id')
    return render_template('admin.html', users=users, settings=settings, logs=logs, current_date=sel_date, 
                           test_users=User.objects(gate_status='testing', status='active'),
                           gate_stats={1: User.objects(chosen_gate=1, status='active').count(), 2: User.objects(chosen_gate=2, status='active').count(), 3: User.objects(chosen_gate=3, status='active').count()},
                           floor3_leaders=User.objects(status='active', role='hunter').order_by('-survival_votes')[:5] if getattr(settings, 'floor3_mode_active', False) else [])

@app.route('/download_logs/<log_date>')
@admin_required
def download_logs(log_date):
    logs = ActionLog.objects(log_date=log_date).order_by('created_at')
    out = f"--- سجلات المتاهة ليوم {log_date} ---\n\n"
    for l in logs: out += f"[{l.created_at.strftime('%H:%M:%S')}] ({l.category}): {l.action_text}\n"
    return Response(out, mimetype="text/plain", headers={"Content-disposition": f"attachment; filename=logs_{log_date}.txt"})

if __name__ == '__main__': 
    app.run(debug=True)

