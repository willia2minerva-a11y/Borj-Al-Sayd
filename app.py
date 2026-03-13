from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, BattleLog
from functools import wraps
from datetime import datetime, timedelta
import os
import base64
import random
import math

app = Flask(__name__)
app.config['MONGODB_SETTINGS'] = {'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db')}
app.config['SECRET_KEY'] = 'sephar-maze-ultimate-key'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
db.init_app(app)

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

        if settings and settings.maintenance_mode:
            now = datetime.utcnow()
            if settings.maintenance_until and now > settings.maintenance_until:
                settings.maintenance_mode = False; settings.maintenance_pages = []; settings.save()
            else:
                if not user or user.role != 'admin':
                    ep = request.endpoint or ''
                    m_pages = settings.maintenance_pages or []
                    if 'all' in m_pages or ep in m_pages:
                        return render_template('locked.html', message='جاري ترميم ونقش هذه الصفحة. ستعود قريباً ⏳')

        if user:
            check_lazy_death_and_bleed(user, settings)
            if user.quicksand_lock_until and datetime.utcnow() < user.quicksand_lock_until:
                time_left = user.quicksand_lock_until - datetime.utcnow()
                mins, secs = divmod(time_left.seconds, 60)
                return render_template('locked.html', message=f'مقيد لـ {mins}د و {secs}ث')
                
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
    except Exception: pass
    
    if 'user_id' in session:
        try:
            user = User.objects(id=session['user_id']).first()
            if user:
                notifs['current_user'] = user; now = datetime.utcnow()
                notifs['un_news'] = News.objects(category='news', status='approved', created_at__gt=user.last_seen_news or now).count()
                notifs['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=user.last_seen_puzzles or now).count()
                notifs['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=user.last_seen_decs or now).count()
                notifs['un_store'] = StoreItem.objects(created_at__gt=user.last_seen_store or now).count()
        except Exception: pass 
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
        except Exception: return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def home():
    try:
        settings = GlobalSettings.objects(setting_name='main_config').first()
        latest_news = News.objects(category='news', status='approved').order_by('-created_at').first()
        latest_dec = News.objects(category='declaration', status='approved').order_by('-created_at').first()
        last_frozen = User.objects(status='eliminated').order_by('-id').first()
        active_voters_count = User.objects(status='active', role='hunter', has_voted=True).count() if settings and settings.floor3_mode_active else 0
        return render_template('index.html', settings=settings, news=latest_news, dec=latest_dec, last_frozen=last_frozen, active_voters_count=active_voters_count)
    except Exception: return "عذراً، جارٍ تهيئة المتاهة، حدث الصفحة."

@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': return redirect(url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    if not settings or not settings.gates_mode_active or settings.gates_selection_locked: return redirect(url_for('home'))
    gate_num = int(request.form.get('gate_num') or 0)
    if gate_num in [1, 2, 3] and user.chosen_gate == 0:
        user.chosen_gate = gate_num; user.gate_status = 'waiting'; user.save(); flash('تم تسجيل مسارك!', 'success')
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    user = User.objects(id=session['user_id']).first()
    if user.gate_status == 'testing': user.gate_test_answer = request.form.get('test_answer', ''); user.save()
    return redirect(url_for('home'))

@app.route('/submit_floor3_votes', methods=['POST'])
@login_required
def submit_floor3_votes():
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active' or user.has_voted: return redirect(url_for('home'))
    try:
        t_ids = [int(request.form.get(f'target_{i}') or 0) for i in range(1, 6)]
        amounts = [int(request.form.get(f'amount_{i}') or 0) for i in range(1, 6)]
    except Exception: return redirect(request.referrer or url_for('home'))
    if len(set(t_ids)) != 5 or sum(amounts) != 100 or any(a < 1 for a in amounts) or user.hunter_id in t_ids: return redirect(request.referrer or url_for('home'))
    targets = User.objects(hunter_id__in=t_ids, status='active')
    if targets.count() != 5: return redirect(request.referrer or url_for('home'))
    for i, tid in enumerate(t_ids):
        t = User.objects(hunter_id=tid).first(); t.survival_votes = (t.survival_votes or 0) + amounts[i]; t.save()
    user.has_voted = True; user.save(); flash('تم التثبيت!', 'success')
    return redirect(url_for('home'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.objects(username=request.form['username']).first(): flash('الاسم مستخدم.', 'error'); return redirect(url_for('register'))
        last_u = User.objects.order_by('-id').first()
        new_id = (last_u.hunter_id + 1) if last_u else 1000
        User(hunter_id=new_id, username=request.form['username'], password_hash=generate_password_hash(request.form['password']), role='admin' if new_id==1000 else 'hunter').save()
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

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    action = request.form.get('action')
    if action == 'change_avatar':
        file = request.files.get('avatar_file')
        if file and file.filename != '': user.avatar = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"; flash('تم!', 'success')
    elif action == 'change_name':
        new_name = request.form.get('new_name')
        now = datetime.utcnow()
        if user.last_name_change and (now - user.last_name_change).days < 15: flash('كل 15 يوم فقط!', 'error')
        elif User.objects(username=new_name).first(): flash('الاسم مستخدم!', 'error')
        else: user.username = new_name; user.last_name_change = now; flash('تم التغيير!', 'success')
    user.save(); return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or target_user.role in ['ghost', 'cursed_ghost']: return redirect(url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').first(); check_lazy_death_and_bleed(target_user, settings)
    current_user = User.objects(id=session['user_id']).first()
    my_items = StoreItem.objects(name__in=current_user.inventory) if current_user.inventory else []
    return render_template('hunter_profile.html', target_user=target_user, banner_url=settings.banner_url if settings else '', my_weapons=[i for i in my_items if i.item_type=='weapon'], my_heals=[i for i in my_items if i.item_type=='heal'], my_spies=[i for i in my_items if i.item_type=='spy'], my_steals=[i for i in my_items if i.item_type=='steal'])

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
            target_user.save(); flash('تم التعديل!', 'success')
        except Exception: flash('خطأ في الإدخال', 'error')
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
            if 0 < amt <= sender.points: sender.points -= amt; receiver.points += amt; sender.save(); receiver.save(); flash('تم التحويل!', 'success')
        except Exception: pass
    elif ttype == 'item':
        itm = request.form.get('item_name')
        if itm in sender.inventory: sender.inventory.remove(itm); receiver.inventory.append(itm); sender.save(); receiver.save(); flash('تم الإرسال!', 'success')
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
    
    if item.item_type == 'seal':
        if target.id == attacker.id:
            attacker.destroyed_seals = (attacker.destroyed_seals or 0) + 1; attacker.inventory.remove(item_name)
            if attacker.destroyed_seals >= 4:
                if settings: settings.war_mode = False; settings.final_battle_mode = False; settings.save()
                User.objects(status='active').update(health=100); flash('دُمرت اللعنة!', 'success')
            else: flash('دُمر الختم!', 'success')
            attacker.save()
        return redirect(request.referrer or url_for('home'))

    if not target or target.status != 'active': return redirect(request.referrer or url_for('home'))
    
    if item.item_type == 'weapon':
        if settings and settings.war_mode and target.hunter_id not in attacker.friends:
            target.health -= (item.effect_amount or 0)
            if target.health <= 0: target.health = 0; target.status = 'eliminated'; settings.dead_count = (settings.dead_count or 0) + 1; settings.save()
            try: BattleLog(victim_name=target.username, weapon_name=item.name, remaining_hp=target.health).save()
            except Exception: pass
            target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); flash('ضُرب!', 'success')
            
    elif item.item_type == 'heal':
        if target.id == attacker.id or target.hunter_id in attacker.friends:
            if target.role == 'admin': target.health += (item.effect_amount or 0)
            else: target.health = min(100, target.health + (item.effect_amount or 0))
            target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); flash('عُولج!', 'success')

    elif item.item_type == 'spy':
        if any('حجاب' in i or 'درع' in i for i in target.inventory): attacker.inventory.remove(item_name); attacker.save(); flash('محمي!', 'error')
        else: attacker.tajis_eye_until = now + timedelta(hours=1); attacker.inventory.remove(item_name); attacker.save(); flash('فُتحت عينك!', 'success')

    elif item.item_type == 'steal':
        stolen_item = request.form.get('target_item')
        if stolen_item in target.inventory:
            has_shield = False; shield_name = ""
            for i in target.inventory:
                if 'حجاب' in i or 'درع' in i or 'عباءة' in i: has_shield = True; shield_name = i; break
            if has_shield: target.inventory.remove(shield_name); target.save(); attacker.inventory.remove(item_name); attacker.save(); flash('محمي! احترقت يدك.', 'error')
            else: target.inventory.remove(stolen_item); target.save(); attacker.inventory.remove(item_name); attacker.inventory.append(stolen_item); attacker.save(); flash('تمت السرقة!', 'success')
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
    if target.status != 'active' and target.role not in ['ghost', 'cursed_ghost']: return redirect(request.referrer or url_for('home'))
        
    if target.role in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target.hunter_id)).first()
        if target.role == 'cursed_ghost' and trap: user.points -= (trap.trap_penalty_points or 0); user.save(); flash('شبح ملعون!', 'error')
        elif trap and str(user.id) not in trap.winners_list and (trap.current_winners or 0) < (trap.max_winners or 1):
            if trap.reward_points > 0: user.points += trap.reward_points
            user.stats_ghosts_caught = (user.stats_ghosts_caught or 0) + 1; trap.current_winners = (trap.current_winners or 0) + 1; trap.winners_list.append(str(user.id))
            user.save(); trap.save(); check_achievements(user); flash('اصطدت شبحاً!', 'success')
        return redirect(request.referrer or url_for('home'))
        
    if target.hunter_id not in user.friends and user.hunter_id not in target.friend_requests:
        target.friend_requests.append(user.hunter_id); target.save(); flash('أُرسل الطلب', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = User.objects(id=session['user_id']).first(); target = User.objects(hunter_id=target_id).first()
    if target:
        if user.hunter_id in target.friend_requests: target.friend_requests.remove(user.hunter_id)
        elif target.hunter_id in user.friends: user.friends.remove(target.hunter_id); target.friends.remove(user.hunter_id)
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
        if f: f.friends.append(user.hunter_id); f.save()
        user.save(); check_achievements(user); flash('قُبل! 🤝', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/news')
@login_required
def news():
    user = User.objects(id=session['user_id']).first(); user.last_seen_news = datetime.utcnow(); user.save()
    return render_template('news.html', news_list=News.objects(category='news', status='approved').order_by('-created_at'))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if user.status != 'active': return redirect(url_for('puzzles'))
        guess = request.form.get('guess'); puzzle = News.objects(id=request.form.get('puzzle_id')).first()
        if puzzle and guess == puzzle.puzzle_answer and str(user.id) not in puzzle.winners_list:
            user.points += (puzzle.reward_points or 0); user.stats_puzzles_solved = (user.stats_puzzles_solved or 0) + 1; puzzle.winners_list.append(str(user.id))
            puzzle.save(); user.save(); flash('إجابة صحيحة!', 'success')
        return redirect(url_for('puzzles'))
    user.last_seen_puzzles = datetime.utcnow(); user.save()
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': return redirect(request.referrer or url_for('home'))
    try: puzzle = News.objects(id=puzzle_id).first()
    except Exception: return redirect(request.referrer or url_for('home'))
    if puzzle and puzzle.puzzle_type == 'quicksand_trap':
        user.quicksand_lock_until = datetime.utcnow() + timedelta(minutes=(puzzle.trap_duration_minutes or 5))
        user.save(); flash('وقعت في فخ الرمال!', 'error')
    elif puzzle and str(user.id) not in puzzle.winners_list and (puzzle.current_winners or 0) < (puzzle.max_winners or 1):
        user.points += (puzzle.reward_points or 0); puzzle.current_winners = (puzzle.current_winners or 0) + 1; puzzle.winners_list.append(str(user.id))
        user.save(); puzzle.save(); flash('جائزة سرية!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if user.status != 'active': return redirect(url_for('declarations'))
        img_b64 = ''; file = request.files.get('image_file')
        if file and file.filename != '': img_b64 = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
        content_text = request.form.get('content', '').strip() or ' '
        News(title=f"تصريح من {user.username}", content=content_text, image_data=img_b64, category='declaration', author=user.username, status='approved' if getattr(user, 'role', '') == 'admin' else 'pending').save()
        flash('تم النشر', 'success'); return redirect(url_for('declarations'))
    user.last_seen_decs = datetime.utcnow(); user.save()
    return render_template('declarations.html', decs=News.objects(category='declaration', status='approved').order_by('-created_at'), current_user=user)

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
        if item.is_luck:
            l_min = item.luck_min or 0; l_max = item.luck_max or 0
            if l_min > l_max: l_min, l_max = l_max, l_min
            outcome = random.randint(l_min, l_max) if l_min != l_max else l_min
            user.points += outcome
            if outcome > 0: flash(f'حظ موفق! +{outcome}', 'success')
            elif outcome < 0: flash(f'حظ سيء! -{abs(outcome)}', 'error')
            else: flash('الصندوق فارغ!', 'info')
        elif item.is_mirage:
            flash(item.mirage_message or 'فخ!', 'error')
        else:
            user.inventory.append(item.name); flash('تم الشراء!', 'success')
        user.save()
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated').order_by('-id'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'setup_maintenance':
                dur = int(request.form.get('m_duration') or 0)
                pages = request.form.getlist('m_pages')
                if dur > 0 and pages:
                    settings.maintenance_mode = True
                    settings.maintenance_until = datetime.utcnow() + timedelta(minutes=dur)
                    settings.maintenance_pages = pages
                    flash('تم تشغيل الصيانة المجدولة!', 'success')
                else:
                    settings.maintenance_mode = False; settings.maintenance_until = None; settings.maintenance_pages = []
                    flash('تم إيقاف الصيانة!', 'success')
                settings.save()
                
            elif action == 'toggle_war':
                settings.war_mode = not settings.war_mode
                if not settings.war_mode:
                    User.objects(status='active').update(health=100); settings.dead_count = 0
                    try: BattleLog.objects.delete()
                    except Exception: pass
                settings.save(); flash('تغيرت حالة الحرب!', 'success')
                
            elif action == 'set_admin_hp':
                admin_user = User.objects(id=session['user_id']).first(); admin_user.health = int(request.form.get('admin_hp') or 100); admin_user.save(); flash('تم رفع صحتك!', 'success')
            elif action == 'toggle_final_battle': settings.final_battle_mode = not settings.final_battle_mode; settings.save()
            elif action == 'setup_gates':
                settings.gates_mode_active = True; settings.gates_selection_locked = bool(request.form.get('locked')); settings.gates_description = request.form.get('desc', ''); settings.gate_1_name = request.form.get('g1', ''); settings.gate_2_name = request.form.get('g2', ''); settings.gate_3_name = request.form.get('g3', ''); settings.gates_test_message = request.form.get('test_msg', ''); settings.save(); flash('تم تفعيل البوابات!', 'success')
            elif action == 'close_gates_mode': settings.gates_mode_active = False; settings.save()
            elif action == 'judge_gates':
                fates = {1: request.form.get('fate_1'), 2: request.form.get('fate_2'), 3: request.form.get('fate_3')}
                for u in User.objects(gate_status='waiting', status='active'):
                    f = fates.get(u.chosen_gate)
                    if f == 'pass': u.gate_status = 'passed'
                    elif f == 'kill': u.status = 'eliminated'; u.freeze_reason = 'اختار بوابة الموت'
                    elif f == 'test': u.gate_status = 'testing'
                    u.save()
                flash('تم الحكم!', 'success')
            elif action == 'judge_test_user':
                u = User.objects(id=request.form.get('user_id')).first()
                if u:
                    if request.form.get('decision') == 'pass': u.gate_status = 'passed'
                    else: u.status = 'eliminated'; u.freeze_reason = 'فشل في الاختبار'
                    u.save()
            elif action == 'toggle_floor3': settings.floor3_mode_active = not settings.floor3_mode_active; settings.save()
            elif action == 'punish_floor3_slackers':
                slackers = User.objects(has_voted=False, status='active', role='hunter')
                if slackers.count() > 0:
                    total_stolen = slackers.count() * 100; active_voters = User.objects(has_voted=True, status='active', role='hunter')
                    if active_voters.count() > 0:
                        bonus = total_stolen // active_voters.count()
                        for v in active_voters: v.survival_votes = (v.survival_votes or 0) + bonus; v.save()
                    for s in slackers: s.status = 'eliminated'; s.freeze_reason = 'خائن لم يوزع أصواته'; s.save()
                    flash('تم الإعدام!', 'success')
            elif action == 'toggle_global_news': settings.global_news_active = not settings.global_news_active; settings.global_news_text = request.form.get('global_news_text', ''); settings.save()
            elif action == 'update_war_settings': settings.bleed_rate_minutes = int(request.form.get('bleed_rate_minutes') or 60); settings.bleed_amount = int(request.form.get('bleed_amount') or 1); settings.safe_time_minutes = int(request.form.get('safe_time_minutes') or 120); settings.save()
            elif action == 'update_nav_names': settings.nav_home = request.form.get('nav_home', settings.nav_home); settings.nav_profile = request.form.get('nav_profile', settings.nav_profile); settings.nav_friends = request.form.get('nav_friends', settings.nav_friends); settings.nav_news = request.form.get('nav_news', settings.nav_news); settings.nav_puzzles = request.form.get('nav_puzzles', settings.nav_puzzles); settings.nav_decs = request.form.get('nav_decs', settings.nav_decs); settings.nav_store = request.form.get('nav_store', settings.nav_store); settings.nav_grave = request.form.get('nav_grave', settings.nav_grave); settings.save()
            elif action == 'update_home_settings':
                settings.home_title = request.form.get('home_title', 'البوابة'); settings.home_color = request.form.get('home_color', 'var(--zone-0-black)'); file = request.files.get('banner_file'); 
                if file and file.filename != '': settings.banner_url = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
                settings.save(); flash('تم الحفظ', 'success')
            elif action == 'add_news': News(title=request.form.get('title'), content=request.form.get('content'), category='puzzle' if request.form.get('puzzle_type') != 'none' else 'news', puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1)).save(); flash('تم النشر!', 'success')
            elif action == 'add_standalone_puzzle':
                ptype = request.form.get('puzzle_type'); panswer = request.form.get('puzzle_answer', '')
                News(title="لغز مخفي", content="خفي", category='hidden', puzzle_type=ptype, puzzle_answer=panswer, reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1), trap_duration_minutes=int(request.form.get('trap_duration') or 0), trap_penalty_points=int(request.form.get('trap_penalty') or 0)).save()
                if ptype in ['fake_account', 'cursed_ghost'] and panswer.isdigit() and not User.objects(hunter_id=int(panswer)).first(): User(hunter_id=int(panswer), username=f"شبح_{panswer}", password_hash="dummy", role='ghost' if ptype == 'fake_account' else 'cursed_ghost', status='active', avatar='👻').save()
                flash('تم زرع الفخ!', 'success')
            elif action == 'add_store_item':
                item = StoreItem(name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price') or 0), item_type=request.form.get('item_type', 'normal'), effect_amount=int(request.form.get('effect_amount') or 0), is_mirage=bool(request.form.get('is_mirage')), mirage_message=request.form.get('mirage_message', ''), is_luck=bool(request.form.get('is_luck')), luck_min=int(request.form.get('luck_min') or 0), luck_max=int(request.form.get('luck_max') or 0))
                file = request.files.get('item_image')
                if file and file.filename != '': item.image = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
                item.save(); flash('تم إضافة الأداة!', 'success')
            elif action == 'bulk_action':
                selected = request.form.getlist('selected_users'); bulk_type = request.form.get('bulk_type')
                for uid in selected:
                    u = User.objects(id=uid).first()
                    if u and getattr(u, 'hunter_id', 0) != 1000:
                        if bulk_type == 'activate': u.status = 'active'; u.health = 100
                        elif bulk_type == 'freeze': u.status = 'frozen'; u.freeze_reason = request.form.get('bulk_reason', 'مقيّد')
                        elif bulk_type == 'eliminate': u.status = 'eliminated'; u.freeze_reason = request.form.get('bulk_reason', 'هلك')
                        u.save()
                flash('تم التنفيذ!', 'success')
        except Exception as e:
            flash(f'خطأ أثناء التنفيذ: {str(e)}', 'error')
            
        return redirect(url_for('admin_panel'))
        
    users = [u for u in User.objects() if getattr(u, 'role', 'hunter') not in ['ghost', 'cursed_ghost']]
    test_users = User.objects(gate_status='testing', status='active')
    gate_stats = {1: User.objects(chosen_gate=1, status='active').count(), 2: User.objects(chosen_gate=2, status='active').count(), 3: User.objects(chosen_gate=3, status='active').count()}
    floor3_leaders = User.objects(status='active', role='hunter').order_by('-survival_votes')[:5] if getattr(settings, 'floor3_mode_active', False) else []
    
    return render_template('admin.html', users=users, settings=settings, test_users=test_users, gate_stats=gate_stats, floor3_leaders=floor3_leaders)

if __name__ == '__main__': app.run(debug=True)ج
