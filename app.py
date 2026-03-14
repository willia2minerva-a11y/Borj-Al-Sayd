from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, BattleLog
from functools import wraps
from datetime import datetime, timedelta
import os, base64, random, math, json

app = Flask(__name__)
app.config['MONGODB_SETTINGS'] = {'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db')}
app.config['SECRET_KEY'] = 'sephar-maze-ultimate-key-pro-final'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
db.init_app(app)

# 📜 نموذج سجلات الأحداث الإمبراطوري الشامل
class ActionLog(db.Document):
    meta = {'strict': False}
    action_text = db.StringField()
    category = db.StringField() # combat, social, puzzle, system
    created_at = db.DateTimeField(default=datetime.utcnow)
    log_date = db.StringField(default=lambda: datetime.utcnow().strftime('%Y-%m-%d'))

def log_action(text, cat):
    try: 
        ActionLog(action_text=text, category=cat).save()
    except: pass

# --- الدوال المساعدة ونظام الحماية الإمبراطوري ---

def check_achievements(user):
    try:
        new_ach = []
        if user.stats_ghosts_caught >= 5 and 'صائد الأشباح 👻' not in user.achievements:
            user.achievements.append('صائد الأشباح 👻'); new_ach.append('صائد الأشباح 👻')
        if user.stats_puzzles_solved >= 5 and 'حكيم سيفار 📜' not in user.achievements:
            user.achievements.append('حكيم سيفار 📜'); new_ach.append('حكيم سيفار 📜')
        if user.stats_items_bought >= 5 and 'التاجر الخبير 🐪' not in user.achievements:
            user.achievements.append('التاجر الخبير 🐪'); new_ach.append('التاجر الخبير 🐪')
        if len(user.friends) >= 5 and 'حليف القوم 🤝' not in user.achievements:
            user.achievements.append('حليف القوم 🤝'); new_ach.append('حليف القوم 🤝')
        if new_ach: flash(f'🏆 إنجاز جديد: {", ".join(new_ach)}', 'success')
        user.save()
    except Exception: pass

def check_lazy_death_and_bleed(user, settings):
    try:
        if not user or user.role == 'admin' or user.status != 'active': return
        now = datetime.utcnow()
        last_act = user.last_active or user.created_at or now
        
        if (now - last_act).total_seconds() / 3600.0 > 72:
            user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'ابتلعته الرمال لغيابه 72 ساعة'
            log_action(f"💀 هلك {user.username} بسبب غياب 72 ساعة", "system")
            user.save(); return

        if settings and settings.war_mode:
            last_action = user.last_action_time or now
            safe_mins = settings.safe_time_minutes or 120
            safe_until = last_action + timedelta(minutes=safe_mins)
            
            if now > safe_until:
                start_bleed_time = max(user.last_health_check or safe_until, safe_until)
                minutes_passed = (now - start_bleed_time).total_seconds() / 60.0
                bleed_rate = settings.bleed_rate_minutes or 60
                bleed_amount = settings.bleed_amount or 1
                
                if bleed_rate > 0 and minutes_passed >= bleed_rate:
                    cycles = math.floor(minutes_passed / bleed_rate)
                    user.health -= cycles * bleed_amount
                    user.last_health_check = now
                    if user.health <= 0:
                        user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'نزف حتى الموت في الحرب'
                        settings.dead_count = (settings.dead_count or 0) + 1; settings.save()
                        log_action(f"🩸 نزف {user.username} حتى الموت في الساحة", "combat")
                    user.save()
    except Exception: pass

@app.before_request
def check_locks_and_status():
    try:
        if request.endpoint in ['static', 'login', 'logout', 'register']: return
        settings = GlobalSettings.objects(setting_name='main_config').first()
        if not settings: settings = GlobalSettings(setting_name='main_config').save()
        
        user = None
        if 'user_id' in session:
            user = User.objects(id=session['user_id']).first()
            if not user: session.pop('user_id', None); session.pop('role', None)
            else: user.last_active = datetime.utcnow(); user.save()

        if getattr(settings, 'maintenance_mode', False):
            now = datetime.utcnow()
            m_until = getattr(settings, 'maintenance_until', None)
            if m_until and now > m_until:
                settings.maintenance_mode = False; settings.maintenance_pages = []; settings.save()
            else:
                if not user or user.role != 'admin':
                    ep = request.endpoint or ''
                    m_pages = getattr(settings, 'maintenance_pages', []) or []
                    if 'all' in m_pages or ep in m_pages:
                        return render_template('locked.html', message='جاري ترميم ونقش هذه الصفحة. ستعود قريباً ⏳')

        if user:
            check_lazy_death_and_bleed(user, settings)
            if user.quicksand_lock_until and datetime.utcnow() < user.quicksand_lock_until:
                time_left = user.quicksand_lock_until - datetime.utcnow()
                return render_template('locked.html', message=f'مقيد في الرمال لـ {time_left.seconds // 60}د و {time_left.seconds % 60}ث')
                
            if user.gate_status == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']:
                return render_template('gate_test.html', message=settings.gates_test_message or 'الاختبار', user=user)
    except Exception: pass

@app.context_processor
def inject_notifications():
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'current_user': None, 'war_settings': None, 'battle_logs': []}
    try:
        settings = GlobalSettings.objects(setting_name='main_config').first()
        notifs['war_settings'] = settings
        if settings and settings.war_mode:
            notifs['battle_logs'] = BattleLog.objects().order_by('-created_at')[:3]
    except: pass
    
    if 'user_id' in session:
        try:
            user = User.objects(id=session['user_id']).first()
            if user:
                notifs['current_user'] = user; now = datetime.utcnow()
                notifs['un_news'] = News.objects(category='news', status='approved', created_at__gt=user.last_seen_news).count()
                notifs['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=user.last_seen_puzzles).count()
                notifs['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=user.last_seen_decs).count()
                notifs['un_store'] = StoreItem.objects(created_at__gt=user.last_seen_store).count()
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
        try:
            user = User.objects(id=session['user_id']).first()
            if not user or user.role != 'admin': return redirect(url_for('home'))
        except: return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

# --- مسارات الصفحة الرئيسية والتسجيل ---

@app.route('/')
def home():
    try:
        settings = GlobalSettings.objects(setting_name='main_config').first()
        user = User.objects(id=session.get('user_id')).first() if 'user_id' in session else None
        
        # 🎯 نظام الأخبار الموجهة
        news_query = db.Q(category='news', status='approved', target_group='all')
        if user:
            if user.gate_status == 'testing': news_query |= db.Q(target_group='testing')
            if user.status == 'eliminated': news_query |= db.Q(target_group='ghosts')
            if user.role == 'hunter': news_query |= db.Q(target_group='hunters')

        latest_news = News.objects(news_query).order_by('-created_at').first()
        latest_dec = News.objects(category='declaration', status='approved').order_by('-created_at').first()
        last_frozen = User.objects(status='eliminated').order_by('-id').first()
        
        # 🗳️ قائمة التصويت (حظر الإمبراطور 1000)
        hunters_list = []
        if settings and settings.floor3_mode_active:
            hunters = User.objects(status='active', role='hunter', hunter_id__ne=1000)
            hunters_list = [{'id': h.hunter_id, 'name': h.username} for h in hunters]

        return render_template('index.html', settings=settings, news=latest_news, dec=latest_dec, 
                               last_frozen=last_frozen, active_hunters_json=json.dumps(hunters_list))
    except Exception: return "عذراً، حدث خطأ في المتاهة، حدث الصفحة."

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.objects(username=request.form['username']).first(): flash('الاسم مستخدم.', 'error'); return redirect(url_for('register'))
        existing_users = User.objects().order_by('hunter_id')
        new_id = 1000
        for u in existing_users:
            if u.hunter_id == new_id: new_id += 1
            elif u.hunter_id > new_id: break
        User(hunter_id=new_id, username=request.form['username'], password_hash=generate_password_hash(request.form['password']), role='admin' if new_id==1000 else 'hunter').save()
        log_action(f"✨ رحالة جديد انضم: {request.form['username']} (#{new_id})", "system")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session.permanent = True; session['user_id'] = str(user.id); session['role'] = user.role; return redirect(url_for('home'))
        flash('بيانات خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).first(); settings = GlobalSettings.objects(setting_name='main_config').first()
    my_items = StoreItem.objects(name__in=user.inventory) if user.inventory else []
    return render_template('profile.html', user=user, banner_url=settings.banner_url if settings else '', my_items=my_items, my_seals=[i for i in my_items if i.item_type == 'seal'])
# --- تابع لملف app.py : الجزء الثاني ---

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    action = request.form.get('action')
    if action == 'change_avatar':
        file = request.files.get('avatar_file')
        if file and file.filename != '': 
            user.avatar = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            flash('تم تحديث النقش بنجاح!', 'success')
    elif action == 'change_name':
        new_name = request.form.get('new_name')
        now = datetime.utcnow()
        last_change = getattr(user, 'last_name_change', None)
        if last_change and (now - last_change).days < 15: flash('يسمح بالتغيير كل 15 يوماً فقط!', 'error')
        elif User.objects(username=new_name).first(): flash('الاسم مستخدم مسبقاً!', 'error')
        else: 
            user.username = new_name; user.last_name_change = now
            flash('تم تغيير الهوية بنجاح!', 'success')
    user.save(); return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']: return redirect(url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    check_lazy_death_and_bleed(target_user, settings)
    current_user = User.objects(id=session['user_id']).first()
    my_items = StoreItem.objects(name__in=current_user.inventory) if current_user.inventory else []
    return render_template('hunter_profile.html', target_user=target_user, banner_url=getattr(settings, 'banner_url', ''), 
                           my_weapons=[i for i in my_items if i.item_type=='weapon'], 
                           my_heals=[i for i in my_items if i.item_type=='heal'], 
                           my_spies=[i for i in my_items if i.item_type=='spy'], 
                           my_steals=[i for i in my_items if i.item_type=='steal'])

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
        except Exception: flash('خطأ في الإدخال', 'error')
    return redirect(url_for('hunter_profile', target_id=target_id))

@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    sender = User.objects(id=session['user_id']).first()
    receiver = User.objects(hunter_id=target_id).first()
    if sender.status != 'active' or not receiver or receiver.status != 'active' or receiver.hunter_id not in sender.friends: return redirect(request.referrer or url_for('home'))
    ttype = request.form.get('transfer_type')
    if ttype == 'points':
        try:
            amt = int(request.form.get('amount') or 0)
            if 0 < amt <= sender.points: 
                sender.points -= amt; receiver.points += amt; sender.save(); receiver.save()
                log_action(f"📦 {sender.username} هرّب {amt} نقطة إلى {receiver.username}", "social")
                flash('تم التهريب!', 'success')
        except Exception: pass
    elif ttype == 'item':
        itm = request.form.get('item_name')
        if itm in sender.inventory: 
            sender.inventory.remove(itm); receiver.inventory.append(itm); sender.save(); receiver.save()
            log_action(f"📦 {sender.username} أرسل أداة ({itm}) إلى {receiver.username}", "social")
            flash('تم الإرسال!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    attacker = User.objects(id=session['user_id']).first()
    if attacker.status != 'active': return redirect(request.referrer or url_for('home'))
    target = User.objects(hunter_id=target_id).first(); settings = GlobalSettings.objects(setting_name='main_config').first()
    item_name = request.form.get('item_name'); item = StoreItem.objects(name=item_name).first()
    if not item or item_name not in attacker.inventory: return redirect(request.referrer or url_for('home'))
    now = datetime.utcnow()
    
    if getattr(item, 'item_type', '') == 'seal':
        if target.id == attacker.id:
            attacker.destroyed_seals = getattr(attacker, 'destroyed_seals', 0) + 1; attacker.inventory.remove(item_name)
            if attacker.destroyed_seals >= 4:
                if settings: settings.war_mode = False; settings.final_battle_mode = False; settings.save()
                User.objects(status='active').update(health=100); flash('دُمرت اللعنة النهائية!', 'success')
            else: flash('تم تدمير الختم!', 'success')
            attacker.save()
        return redirect(request.referrer or url_for('home'))

    if not target or target.status != 'active': return redirect(request.referrer or url_for('home'))
    
    if item.item_type == 'weapon':
        if settings and settings.war_mode and target.hunter_id not in attacker.friends:
            target.health -= item.effect_amount
            log_action(f"⚔️ {attacker.username} طعن {target.username} بـ {item.name}", "combat")
            if target.health <= 0: 
                target.health = 0; target.status = 'eliminated'; settings.dead_count = getattr(settings, 'dead_count', 0) + 1; settings.save()
                log_action(f"💀 {target.username} هلك على يد {attacker.username}", "combat")
            BattleLog(victim_name=target.username, weapon_name=item.name, remaining_hp=target.health).save()
            target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); flash('تمت الضربة!', 'success')
            
    elif item.item_type == 'heal':
        if target.id == attacker.id or target.hunter_id in attacker.friends:
            target.health = target.health + item.effect_amount if target.role == 'admin' else min(100, target.health + item.effect_amount)
            log_action(f"🧪 {attacker.username} استخدم علاجاً على {target.username}", "combat")
            target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); flash('عُولج!', 'success')

    elif item.item_type == 'spy':
        if any('حجاب' in i or 'درع' in i for i in target.inventory): attacker.inventory.remove(item_name); attacker.save(); flash('الهدف محصن!', 'error')
        else:
            attacker.tajis_eye_until = now + timedelta(hours=1); attacker.inventory.remove(item_name); attacker.save()
            log_action(f"👁️ {attacker.username} فتح عين تاجيس على حقيبة {target.username}", "social")
            flash('فتحت عين تاجيس لمدة ساعة!', 'success')

    elif item.item_type == 'steal':
        stolen_item = request.form.get('target_item')
        if stolen_item in target.inventory:
            has_shield = any('حجاب' in i or 'درع' in i or 'عباءة' in i for i in target.inventory)
            if has_shield: flash('الهدف محمي! احترقت يدك.', 'error')
            else:
                target.inventory.remove(stolen_item); attacker.inventory.append(stolen_item); attacker.inventory.remove(item_name)
                attacker.save(); target.save()
                log_action(f"🖐️ {attacker.username} سرق {stolen_item} من {target.username}", "social")
                flash('تمت السرقة بنجاح!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/friends', methods=['GET'])
@login_required
def friends():
    user = User.objects(id=session['user_id']).first()
    search_query = request.args.get('search'); search_result = None
    if search_query:
        if search_query.isdigit(): search_result = User.objects(hunter_id=int(search_query)).first()
        else: search_result = User.objects(username__icontains=search_query).first()
    return render_template('friends.html', user=user, search_result=search_result, friend_requests=User.objects(hunter_id__in=user.friend_requests), friends=User.objects(hunter_id__in=user.friends))

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': return redirect(request.referrer or url_for('home'))
    try: target_id = int(request.form.get('target_id') or 0)
    except Exception: return redirect(request.referrer or url_for('home'))
    target = User.objects(hunter_id=target_id).first()
    if not target: return redirect(request.referrer or url_for('home'))
    if target.status != 'active' and getattr(target, 'role', '') not in ['ghost', 'cursed_ghost']: return redirect(request.referrer or url_for('home'))
        
    if getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target.hunter_id)).first()
        if getattr(target, 'role', '') == 'cursed_ghost' and trap: 
            user.points -= getattr(trap, 'trap_penalty_points', 0); user.save()
            log_action(f"💀 {user.username} وقع في فخ الشبح الملعون #{target.hunter_id}", "puzzle")
            flash('أيقظت شبحاً ملعوناً!', 'error')
        elif trap and str(user.id) not in trap.winners_list and (getattr(trap, 'current_winners', 0)) < (getattr(trap, 'max_winners', 1)):
            if getattr(trap, 'reward_points', 0) > 0: user.points += trap.reward_points
            user.stats_ghosts_caught = getattr(user, 'stats_ghosts_caught', 0) + 1; trap.current_winners = (trap.current_winners or 0) + 1; trap.winners_list.append(str(user.id))
            user.save(); trap.save(); log_action(f"👻 {user.username} اصطاد الشبح المرشد #{target.hunter_id}", "puzzle")
            flash('اصطدت شبحاً بنجاح!', 'success')
        return redirect(request.referrer or url_for('home'))
        
    if target.hunter_id not in user.friends and user.hunter_id not in target.friend_requests:
        target.friend_requests.append(user.hunter_id); target.save()
        log_action(f"🤝 {user.username} أرسل طلب تحالف لـ {target.username}", "social")
        flash('تم إرسال الطلب', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = User.objects(id=session['user_id']).first(); target = User.objects(hunter_id=target_id).first()
    if target:
        if user.hunter_id in target.friend_requests: target.friend_requests.remove(user.hunter_id)
        elif target.hunter_id in user.friends: 
            user.friends.remove(target.hunter_id); target.friends.remove(user.hunter_id)
            log_action(f"💔 انهار التحالف بين {user.username} و {target.username}", "social")
        user.save(); target.save(); flash('تم الإلغاء', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = User.objects(id=session['user_id']).first()
    if user.status == 'active' and friend_id in user.friend_requests:
        f = User.objects(hunter_id=friend_id).first()
        if f and f.status != 'active': user.friend_requests.remove(friend_id); user.save(); return redirect(request.referrer or url_for('home'))
        user.friend_requests.remove(friend_id); user.friends.append(friend_id)
        if f: 
            f.friends.append(user.hunter_id); f.save()
            log_action(f"🤝 تحالف جديد نشأ بين {user.username} و {f.username}", "social")
        user.save(); check_achievements(user); flash('تم القبول! 🤝', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/news')
@login_required
def news():
    user = User.objects(id=session['user_id']).first(); user.last_seen_news = datetime.utcnow(); user.save()
    news_q = db.Q(category='news', status='approved', target_group='all')
    if user.gate_status == 'testing': news_q |= db.Q(target_group='testing')
    if user.status == 'eliminated': news_q |= db.Q(target_group='ghosts')
    if user.role == 'hunter': news_q |= db.Q(target_group='hunters')
    return render_template('news.html', news_list=News.objects(news_q).order_by('-created_at'))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if user.status != 'active': return redirect(url_for('puzzles'))
        guess = request.form.get('guess'); puzzle = News.objects(id=request.form.get('puzzle_id')).first()
        if puzzle and guess == getattr(puzzle, 'puzzle_answer', '') and str(user.id) not in puzzle.winners_list:
            if getattr(puzzle, 'current_winners', 0) < getattr(puzzle, 'max_winners', 1):
                user.points += getattr(puzzle, 'reward_points', 0); user.stats_puzzles_solved = getattr(user, 'stats_puzzles_solved', 0) + 1
                puzzle.winners_list.append(str(user.id)); puzzle.current_winners = (puzzle.current_winners or 0) + 1
                puzzle.save(); user.save()
                log_action(f"🧩 {user.username} حل لغز ({puzzle.title})", "puzzle")
                flash('إجابة صحيحة وحصلت على الجائزة!', 'success')
            else: flash('إجابة صحيحة، لكن الجوائز نفدت!', 'error')
        else: flash('إجابة خاطئة أو أنك حللته مسبقاً.', 'error')
        return redirect(url_for('puzzles'))
    user.last_seen_puzzles = datetime.utcnow(); user.save()
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/delete_puzzle/<puzzle_id>', methods=['POST'])
@admin_required
def delete_puzzle(puzzle_id):
    try: News.objects(id=puzzle_id).delete(); flash('تم حذف اللغز!', 'success')
    except: pass
    return redirect(url_for('puzzles'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': return redirect(request.referrer or url_for('home'))
    try: puzzle = News.objects(id=puzzle_id).first()
    except Exception: return redirect(request.referrer or url_for('home'))
    if puzzle and getattr(puzzle, 'puzzle_type', '') == 'quicksand_trap':
        user.quicksand_lock_until = datetime.utcnow() + timedelta(minutes=getattr(puzzle, 'trap_duration_minutes', 5))
        user.save(); log_action(f"🕸️ وقع {user.username} في فخ رمال متحركة", "puzzle")
        flash('وقعت في فخ الرمال!', 'error')
    elif puzzle and str(user.id) not in puzzle.winners_list and (getattr(puzzle, 'current_winners', 0)) < (getattr(puzzle, 'max_winners', 1)):
        user.points += getattr(puzzle, 'reward_points', 0); puzzle.current_winners = (puzzle.current_winners or 0) + 1; puzzle.winners_list.append(str(user.id))
        user.save(); puzzle.save(); log_action(f"🎁 عثر {user.username} على رابط سري لنقاط", "puzzle")
        flash('جائزة سرية!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if user.status != 'active': return redirect(url_for('declarations'))
        img_b64 = ''; file = request.files.get('image_file')
        if file and file.filename != '': img_b64 = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
        News(title=f"تصريح من {user.username}", content=request.form.get('content', '').strip() or ' ', image_data=img_b64, category='declaration', author=user.username, status='approved' if user.role == 'admin' else 'pending').save()
        log_action(f"📢 نشر {user.username} تدوينة جديدة", "social")
        flash('تم الإرسال (سينشر بعد موافقة الإدارة)', 'success'); return redirect(url_for('declarations'))
    user.last_seen_decs = datetime.utcnow(); user.save()
    approved_decs = News.objects(category='declaration', status='approved').order_by('-created_at')
    my_pending_decs = News.objects(category='declaration', status='pending', author=user.username).order_by('-created_at')
    pending_all = News.objects(category='declaration', status='pending') if user.role == 'admin' else []
    return render_template('declarations.html', approved_decs=approved_decs, my_pending_decs=my_pending_decs, pending_decs=pending_all, current_user=user)

@app.route('/delete_declaration/<dec_id>', methods=['POST'])
@login_required
def delete_declaration(dec_id):
    user = User.objects(id=session['user_id']).first(); dec = News.objects(id=dec_id).first()
    if dec and (dec.author == user.username or user.role == 'admin'):
        dec.delete(); flash('تم الحذف!', 'success')
    return redirect(url_for('declarations'))

@app.route('/store')
@login_required
def store():
    user = User.objects(id=session['user_id']).first(); user.last_seen_store = datetime.utcnow(); user.save()
    return render_template('store.html', items=StoreItem.objects())

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': return redirect(url_for('store'))
    try: item = StoreItem.objects(id=item_id).first()
    except Exception: return redirect(url_for('store'))
    if user and item and user.points >= item.price:
        user.points -= item.price
        if getattr(item, 'is_luck', False):
            outcome = random.randint(item.luck_min, item.luck_max); user.points += outcome
            log_action(f"🎲 جرب {user.username} حظه في صندوق وربح/خسر {outcome}", "puzzle")
            flash(f'حظ موفق! حصلت على {outcome} نقطة' if outcome > 0 else f'حظ سيء! خسرت {abs(outcome)} نقطة', 'success' if outcome > 0 else 'error')
        elif getattr(item, 'is_mirage', False):
            log_action(f"🕸️ وقع {user.username} في فخ متجر (سراب)", "puzzle")
            flash(item.mirage_message or 'فخ السراب!', 'error')
        else:
            user.inventory.append(item.name); user.stats_items_bought = getattr(user, 'stats_items_bought', 0) + 1
            log_action(f"🐪 اشترى {user.username} أداة ({item.name}) من السوق", "social")
            flash('اشتريت الأداة بنجاح!', 'success')
        user.save()
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated').order_by('-id'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    selected_date = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    logs = ActionLog.objects(log_date=selected_date).order_by('-created_at')
    
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'moderate_dec':
                dec = News.objects(id=request.form.get('dec_id')).first()
                if dec:
                    if request.form.get('decision') == 'approve': dec.status = 'approved'; dec.save()
                    else: dec.delete()
            elif action == 'setup_maintenance':
                dur = int(request.form.get('m_duration') or 0); pages = request.form.getlist('m_pages')
                if dur > 0 and pages:
                    settings.maintenance_mode = True; settings.maintenance_until = datetime.utcnow() + timedelta(minutes=dur); settings.maintenance_pages = pages
                else: settings.maintenance_mode = False; settings.maintenance_pages = []
                settings.save()
            elif action == 'toggle_war':
                settings.war_mode = not settings.war_mode
                if not settings.war_mode: User.objects(status='active').update(health=100); BattleLog.objects.delete()
                settings.save()
            elif action == 'set_admin_hp':
                admin_user = User.objects(id=session['user_id']).first(); admin_user.health = int(request.form.get('admin_hp') or 100); admin_user.save()
            elif action == 'add_news':
                News(title=request.form.get('title'), content=request.form.get('content'), category='puzzle' if request.form.get('puzzle_type') != 'none' else 'news', puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1)).save()
            elif action == 'add_targeted_news':
                News(title=request.form.get('title'), content=request.form.get('content'), category='news', target_group=request.form.get('target_group')).save()
            elif action == 'bulk_action':
                selected = request.form.getlist('selected_users'); b_type = request.form.get('bulk_type')
                for uid in selected:
                    u = User.objects(id=uid).first()
                    if u and u.hunter_id != 1000:
                        if b_type == 'hard_delete': u.delete()
                        elif b_type == 'activate': u.status = 'active'; u.health = 100; u.save()
                        elif b_type == 'eliminate': u.status = 'eliminated'; u.freeze_reason = request.form.get('bulk_reason', 'هلك'); u.save()
            # ... باقي أوامر الإدارة العامة ...
            settings.save()
        except: pass
        return redirect(url_for('admin_panel', date=selected_date))
    
    users = User.objects(hunter_id__ne=1000).order_by('hunter_id')
    return render_template('admin.html', users=users, settings=settings, logs=logs, current_date=selected_date)

@app.route('/download_logs/<log_date>')
@admin_required
def download_logs(log_date):
    logs = ActionLog.objects(log_date=log_date).order_by('-created_at')
    content = f"سجلات المتاهة التاريخية ليوم: {log_date}\n\n"
    for l in logs: content += f"[{l.created_at.strftime('%H:%M:%S')}] ({l.category}) : {l.action_text}\n"
    return Response(content, mimetype="text/plain", headers={"Content-disposition": f"attachment; filename=logs_{log_date}.txt"})

if __name__ == '__main__': app.run(debug=True)


