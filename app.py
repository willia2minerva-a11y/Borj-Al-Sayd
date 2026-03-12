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
    new_ach = []
    if user.stats_ghosts_caught >= 5 and 'صائد الأشباح 👻' not in user.achievements:
        user.achievements.append('صائد الأشباح 👻'); new_ach.append('صائد الأشباح 👻')
    if user.stats_puzzles_solved >= 5 and 'حكيم سيفار 📜' not in user.achievements:
        user.achievements.append('حكيم سيفار 📜'); new_ach.append('حكيم سيفار 📜')
    if user.stats_items_bought >= 5 and 'التاجر الخبير 🐪' not in user.achievements:
        user.achievements.append('التاجر الخبير 🐪'); new_ach.append('التاجر الخبير 🐪')
    if len(user.friends) >= 5 and 'حليف القوم 🤝' not in user.achievements:
        user.achievements.append('حليف القوم 🤝'); new_ach.append('حليف القوم 🤝')
    if new_ach:
        flash(f'🏆 إنجاز جديد يضاف لمخطوطتك! لقد حصلت على وسام: {", ".join(new_ach)}', 'success')
    user.save()

def check_lazy_death_and_bleed(user, settings):
    if not user or user.role == 'admin' or user.status != 'active': return
    now = datetime.utcnow()
    
    hours_passed = (now - getattr(user, 'last_active', user.created_at)).total_seconds() / 3600.0
    if hours_passed > 72:
        user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'ابتلعته الرمال المتحركة لغيابه أكثر من 72 ساعة'
        user.save(); return

    if settings and getattr(settings, 'war_mode', False):
        safe_until = getattr(user, 'last_action_time', now) + timedelta(minutes=settings.safe_time_minutes)
        if now > safe_until:
            start_bleed_time = max(getattr(user, 'last_health_check', safe_until), safe_until)
            minutes_passed = (now - start_bleed_time).total_seconds() / 60.0
            if minutes_passed >= settings.bleed_rate_minutes and settings.bleed_rate_minutes > 0:
                cycles = math.floor(minutes_passed / settings.bleed_rate_minutes)
                user.health -= cycles * settings.bleed_amount
                user.last_health_check = now
                if user.health <= 0:
                    user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'نزف حتى الموت في حرب المتاهة'
                    settings.dead_count += 1; settings.save()
                user.save()

@app.before_request
def check_locks_and_status():
    if request.endpoint in ['static', 'login', 'logout', 'register']: return
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    
    user = None
    if 'user_id' in session:
        user = User.objects(id=session['user_id']).first()
        if not user: session.pop('user_id', None); session.pop('role', None)
        else:
            user.last_active = datetime.utcnow(); user.save()

    if settings.maintenance_mode:
        if not user and request.endpoint != 'home':
            return render_template('locked.html', message='تهب عاصفة رملية شديدة في المتاهة... جاري ترميم النقوش. ⏳')
        elif user and getattr(user, 'role', '') != 'admin':
            return render_template('locked.html', message='تهب عاصفة رملية شديدة في المتاهة... جاري ترميم النقوش. ⏳')

    if user:
        check_lazy_death_and_bleed(user, settings)
        
        # إذا كان مقيداً برابط الرمال يعلق هنا
        if user.quicksand_lock_until and datetime.utcnow() < user.quicksand_lock_until:
            time_left = user.quicksand_lock_until - datetime.utcnow()
            mins, secs = divmod(time_left.seconds, 60)
            return render_template('locked.html', message=f'ابتلعتك الرمال! 🏜️ مقيد لـ {mins}د و {secs}ث')
        
        # غرفة الاختبار
        if getattr(user, 'gate_status', '') == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']:
            return render_template('gate_test.html', message=settings.gates_test_message, user=user)

@app.context_processor
def inject_notifications():
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'current_user': None, 'war_settings': None, 'battle_logs': []}
    try:
        notifs['war_settings'] = GlobalSettings.objects(setting_name='main_config').first()
        if getattr(notifs['war_settings'], 'war_mode', False):
            notifs['battle_logs'] = BattleLog.objects().order_by('-created_at')[:5]
    except Exception: pass

    if 'user_id' in session:
        try:
            user = User.objects(id=session['user_id']).first()
            if user:
                notifs['current_user'] = user; now = datetime.utcnow()
                notifs['un_news'] = News.objects(category='news', status='approved', created_at__gt=getattr(user, 'last_seen_news', now) or now).count()
                notifs['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=getattr(user, 'last_seen_puzzles', now) or now).count()
                notifs['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=getattr(user, 'last_seen_decs', now) or now).count()
                notifs['un_store'] = StoreItem.objects(created_at__gt=getattr(user, 'last_seen_store', now) or now).count()
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
        user = User.objects(id=session['user_id']).first()
        if not user or user.role != 'admin': return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def home():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    latest_news = News.objects(category='news', status='approved').order_by('-created_at').first()
    latest_dec = News.objects(category='declaration', status='approved').order_by('-created_at').first()
    last_frozen = User.objects(status='eliminated').order_by('-id').first()
    
    active_voters_count = 0
    if settings and settings.floor3_mode_active:
        active_voters_count = User.objects(status='active', role='hunter', has_voted=True).count()

    return render_template('index.html', settings=settings, news=latest_news, dec=latest_dec, last_frozen=last_frozen, active_voters_count=active_voters_count)

@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': flash('أنت مجمد كالشبح، لا يمكنك الاختيار!', 'error'); return redirect(url_for('home'))
    
    settings = GlobalSettings.objects(setting_name='main_config').first()
    if not settings.gates_mode_active or settings.gates_selection_locked:
        flash('الاختيار غير متاح حالياً!', 'error'); return redirect(url_for('home'))
        
    gate_num = int(request.form.get('gate_num', 0))
    if gate_num in [1, 2, 3] and user.chosen_gate == 0:
        user.chosen_gate = gate_num; user.gate_status = 'waiting'; user.save()
        flash('تم تسجيل مسارك! لا تراجع الآن... انتظر حكم المتاهة.', 'success')
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    user = User.objects(id=session['user_id']).first()
    if user.gate_status == 'testing':
        user.gate_test_answer = request.form.get('test_answer', ''); user.save()
    return redirect(url_for('home'))

@app.route('/submit_floor3_votes', methods=['POST'])
@login_required
def submit_floor3_votes():
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': flash('الأحياء فقط من يصوتون!', 'error'); return redirect(url_for('home'))
    
    settings = GlobalSettings.objects(setting_name='main_config').first()
    if not settings.floor3_mode_active: flash('هذا المود غير مفعل!', 'error'); return redirect(url_for('home'))
    if user.has_voted: flash('لقد قمت بالتصويت وتوزيع أرواحك مسبقاً!', 'error'); return redirect(url_for('home'))
    
    try:
        t_ids = [int(request.form.get(f'target_{i}')) for i in range(1, 6)]
        amounts = [int(request.form.get(f'amount_{i}')) for i in range(1, 6)]
    except: flash('بيانات غير صالحة!', 'error'); return redirect(request.referrer)
        
    if len(set(t_ids)) != 5: flash('وزع الأصوات على 5 أشخاص مختلفين!', 'error'); return redirect(request.referrer)
    if sum(amounts) != 100 or any(a < 1 for a in amounts): flash('يجب توزيع 100 نقطة بالضبط!', 'error'); return redirect(request.referrer)
    if user.hunter_id in t_ids: flash('لا يمكنك التصويت لنفسك!', 'error'); return redirect(request.referrer)

    targets = User.objects(hunter_id__in=t_ids, status='active')
    if targets.count() != 5: flash('أحد الأشخاص غير موجود أو مقصي!', 'error'); return redirect(request.referrer)

    for i, tid in enumerate(t_ids):
        t = User.objects(hunter_id=tid).first(); t.survival_votes += amounts[i]; t.save()
        
    user.has_voted = True; user.save()
    flash('تم تثبيت أصواتك بنجاح!', 'success'); return redirect(url_for('home'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        ip = request.headers.get('X-Forwarded-For', request.remote_addr) or ''
        ip = ip.split(',')[0]
        if User.objects(username=request.form['username']).first():
            flash('الاسم مستخدم مسبقاً.', 'error'); return redirect(url_for('register'))
        is_first = User.objects.count() == 0
        last_u = User.objects.order_by('-hunter_id').first()
        new_id = (last_u.hunter_id + 1) if last_u else 1000
        now = datetime.utcnow()
        User(hunter_id=new_id, username=request.form['username'], facebook_link=request.form['facebook_link'], password_hash=generate_password_hash(request.form['password']), role='admin' if is_first else 'hunter', status='active', ip_address=ip, last_seen_news=now, last_seen_puzzles=now, last_seen_decs=now, last_seen_store=now).save()
        flash('تم التسجيل بنجاح.', 'success'); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session.permanent = True
            session['user_id'] = str(user.id); session['role'] = user.role; return redirect(url_for('home'))
        flash('بيانات الدخول خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.pop('user_id', None); session.pop('role', None); return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).first()
    settings = GlobalSettings.objects(setting_name='main_config').first()
    zones = {0: 'floor-0', 1: 'floor-1', 2: 'floor-2', 3: 'floor-3', 4: 'floor-4', 5: 'floor-5'}
    my_items = StoreItem.objects(name__in=user.inventory) if user.inventory else []
    my_seals = [i for i in my_items if i.item_type == 'seal']
    return render_template('profile.html', user=user, zone_class=zones.get(user.zone, 'floor-0'), banner_url=settings.banner_url if settings else '', my_items=my_items, my_seals=my_seals)

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    settings = GlobalSettings.objects(setting_name='main_config').first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']:
        flash('الرحالة غير موجود!', 'error'); return redirect(request.referrer or url_for('home'))
    check_lazy_death_and_bleed(target_user, settings)
    zones = {0: 'floor-0', 1: 'floor-1', 2: 'floor-2', 3: 'floor-3', 4: 'floor-4', 5: 'floor-5'}
    current_user = User.objects(id=session['user_id']).first()
    my_weapons = []; my_heals = []; my_spies = []; my_steals = []
    if current_user.inventory:
        items = StoreItem.objects(name__in=current_user.inventory)
        my_weapons = [i for i in items if i.item_type == 'weapon']
        my_heals = [i for i in items if i.item_type == 'heal']
        my_spies = [i for i in items if i.item_type == 'spy']
        my_steals = [i for i in items if i.item_type == 'steal']
    return render_template('hunter_profile.html', target_user=target_user, zone_class=zones.get(target_user.zone, 'floor-0'), banner_url=settings.banner_url if settings else '', my_weapons=my_weapons, my_heals=my_heals, my_spies=my_spies, my_steals=my_steals)

@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    sender = User.objects(id=session['user_id']).first()
    if sender.status != 'active': flash('الأشباح لا يمكنها إرسال الهدايا!', 'error'); return redirect(request.referrer)
    receiver = User.objects(hunter_id=target_id).first()
    if not receiver or receiver.status != 'active': flash('لا يمكن الإرسال لميت!', 'error'); return redirect(request.referrer)
    if receiver.hunter_id not in sender.friends: flash('التبادل مسموح للحلفاء فقط!', 'error'); return redirect(request.referrer)
    
    transfer_type = request.form.get('transfer_type')
    if transfer_type == 'points':
        amount = int(request.form.get('amount', 0))
        if amount <= 0 or amount > sender.points: flash('رصيد غير كافي!', 'error'); return redirect(request.referrer)
        sender.points -= amount; receiver.points += amount; sender.save(); receiver.save(); flash(f'تم تحويل {amount} نقطة!', 'success')
    elif transfer_type == 'item':
        item_name = request.form.get('item_name')
        if item_name not in sender.inventory: flash('لا تملك هذا الغرض!', 'error'); return redirect(request.referrer)
        sender.inventory.remove(item_name); receiver.inventory.append(item_name); sender.save(); receiver.save(); flash(f'تم إرسال {item_name}!', 'success')
    return redirect(request.referrer)

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    attacker = User.objects(id=session['user_id']).first()
    if attacker.status != 'active': flash('الأشباح لا تستخدم الأدوات!', 'error'); return redirect(request.referrer)
    
    target = User.objects(hunter_id=target_id).first()
    settings = GlobalSettings.objects(setting_name='main_config').first()
    item_name = request.form.get('item_name')
    item = StoreItem.objects(name=item_name).first()
    
    if not item or item_name not in attacker.inventory: flash('عملية غير صالحة.', 'error'); return redirect(request.referrer)
    now = datetime.utcnow()
    
    if item.item_type == 'seal':
        if target.id != attacker.id: flash('يُدمر من حقيبتك فقط!', 'error'); return redirect(request.referrer)
        attacker.destroyed_seals += 1; attacker.inventory.remove(item_name)
        if attacker.destroyed_seals >= 4:
            flash('🌟 دمرت الأختام الأربعة وفككت اللعنة! أنت الفائز!', 'success')
            settings.war_mode = False; settings.final_battle_mode = False; settings.save()
            User.objects(status='active').update(health=100)
        else: flash(f'🔨 دُمر الختم! ({attacker.destroyed_seals}/4)', 'success')
        attacker.save(); return redirect(request.referrer)

    if not target or target.status != 'active': flash('الهدف ميت!', 'error'); return redirect(request.referrer)
    
    if item.item_type == 'weapon':
        if not getattr(settings, 'war_mode', False): flash('المتاهة في سلام!', 'error'); return redirect(request.referrer)
        if target.hunter_id in attacker.friends: flash('لا يمكنك طعن حليفك!', 'error'); return redirect(request.referrer)
        target.health -= item.effect_amount
        if target.health <= 0:
            target.health = 0; target.status = 'eliminated'; target.freeze_reason = 'صُفي في المعركة'
            settings.dead_count += 1; settings.save()
            flash(f'💀 قُتل {target.username}!', 'success')
        else: flash(f'🗡️ تمت الضربة!', 'success')
        BattleLog(victim_name=target.username, weapon_name=item.name, remaining_hp=target.health).save()
        target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save()
        
    elif item.item_type == 'heal':
        if target.id != attacker.id and target.hunter_id not in attacker.friends: flash('عالج حلفائك!', 'error'); return redirect(request.referrer)
        target.health = min(100, target.health + item.effect_amount); target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); flash(f'🧪 تم العلاج!', 'success')

    elif item.item_type == 'spy':
        if any('حجاب' in i or 'درع' in i for i in target.inventory):
            attacker.inventory.remove(item_name); attacker.save(); flash('👁️ الهدف محمي بحجاب! احترقت عينك.', 'error')
        else:
            attacker.tajis_eye_until = now + timedelta(hours=1); attacker.inventory.remove(item_name); attacker.save(); flash('👁️ فُتحت عين تاجيس لساعة.', 'success')

    elif item.item_type == 'steal':
        stolen_item = request.form.get('target_item')
        if not stolen_item or stolen_item not in target.inventory: flash('الغرض غير موجود!', 'error'); return redirect(request.referrer)
        has_shield = False; shield_name = ""
        for i in target.inventory:
            if 'حجاب' in i or 'درع' in i or 'عباءة' in i: has_shield = True; shield_name = i; break
        if has_shield:
            target.inventory.remove(shield_name); target.save(); attacker.inventory.remove(item_name); attacker.save(); flash(f'🖐️ الهدف محمي! احترقت يدك!', 'error')
        else:
            target.inventory.remove(stolen_item); target.save(); attacker.inventory.remove(item_name); attacker.inventory.append(stolen_item); attacker.save(); flash(f'🖐️ تمت السرقة!', 'success')

    return redirect(request.referrer)

@app.route('/admin_update_profile/<int:target_id>', methods=['POST'])
@admin_required
def admin_update_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if target_user:
        action = request.form.get('action')
        if action == 'edit_name':
            target_user.username = request.form.get('new_name'); target_user.save(); flash('تم التعديل!', 'success')
        elif action == 'edit_points':
            target_user.points = int(request.form.get('new_points')); target_user.save(); flash('تم التعديل!', 'success')
        elif action == 'edit_hp':
            target_user.health = int(request.form.get('new_hp'))
            if target_user.health <= 0: target_user.health = 0; target_user.status = 'eliminated'
            elif target_user.status == 'eliminated': target_user.status = 'active'
            target_user.save(); flash('تم التعديل!', 'success')
    return redirect(url_for('hunter_profile', target_id=target_id))

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    file = request.files.get('avatar_file')
    if file: user.avatar = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"; flash('تُحدثت!', 'success')
    user.save(); return redirect(url_for('profile'))

@app.route('/friends', methods=['GET'])
@login_required
def friends():
    user = User.objects(id=session['user_id']).first()
    return render_template('friends.html', user=user, friend_requests=User.objects(hunter_id__in=user.friend_requests), friends=User.objects(hunter_id__in=user.friends))

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': flash('الأشباح لا تتحالف!', 'error'); return redirect(request.referrer)
    
    target = User.objects(hunter_id=int(request.form.get('target_id'))).first()
    if not target: flash('غير موجود!', 'error'); return redirect(request.referrer)
    
    if target.status != 'active' and getattr(target, 'role', '') not in ['ghost', 'cursed_ghost']:
        flash('لا يمكنك التحالف مع الأموات!', 'error'); return redirect(request.referrer)
        
    if getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target.hunter_id)).first()
        if getattr(target, 'role', '') == 'cursed_ghost' and trap:
            user.points -= trap.trap_penalty_points; user.save(); flash(f'أيقظت شبحاً ملعوناً! خصم {trap.trap_penalty_points} نقطة.', 'error')
        elif trap and str(user.id) not in trap.winners_list and trap.current_winners < trap.max_winners:
            if trap.reward_points > 0: user.points += trap.reward_points
            user.stats_ghosts_caught += 1; trap.current_winners += 1; trap.winners_list.append(str(user.id))
            user.save(); trap.save(); check_achievements(user); flash('اصطدت الشبح بنجاح! 👻', 'success')
        else: flash('الشبح هرب.', 'error')
        return redirect(request.referrer)
        
    if target.hunter_id not in user.friends and user.hunter_id not in target.friend_requests:
        target.friend_requests.append(user.hunter_id); target.save(); flash('تم الإرسال.', 'success')
    return redirect(request.referrer)

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = User.objects(id=session['user_id']).first()
    target = User.objects(hunter_id=target_id).first()
    if target:
        if user.hunter_id in target.friend_requests: target.friend_requests.remove(user.hunter_id)
        elif target.hunter_id in user.friends: user.friends.remove(target.hunter_id); target.friends.remove(user.hunter_id)
        user.save(); target.save(); flash('تم الإلغاء.', 'success')
    return redirect(request.referrer)

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': flash('الأشباح لا تقبل التحالفات!', 'error'); return redirect(request.referrer)
    
    if friend_id in user.friend_requests:
        f = User.objects(hunter_id=friend_id).first()
        if f and f.status != 'active':
            user.friend_requests.remove(friend_id); user.save(); flash('صاحب الطلب ميت!', 'error'); return redirect(request.referrer)
            
        user.friend_requests.remove(friend_id); user.friends.append(friend_id)
        if f: f.friends.append(user.hunter_id); f.save()
        user.save(); check_achievements(user); flash('تم القبول! 🤝', 'success')
    return redirect(request.referrer)

@app.route('/news')
@login_required
def news():
    user = User.objects(id=session['user_id']).first()
    user.last_seen_news = datetime.utcnow(); user.save()
    return render_template('news.html', news_list=News.objects(category='news', status='approved').order_by('-created_at'))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if user.status != 'active': flash('الأموات لا يحلون الألغاز!', 'error'); return redirect(url_for('puzzles'))
        guess = request.form.get('guess'); puzzle = News.objects(id=request.form.get('puzzle_id')).first()
        if puzzle and guess == puzzle.puzzle_answer and str(user.id) not in puzzle.winners_list:
            user.points += puzzle.reward_points; user.stats_puzzles_solved += 1; puzzle.winners_list.append(str(user.id))
            puzzle.save(); user.save(); flash('صحيح!', 'success')
        return redirect(url_for('puzzles'))
    user.last_seen_puzzles = datetime.utcnow(); user.save()
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if user.status != 'active': flash('الأشباح لا تصرح!', 'error'); return redirect(url_for('declarations'))
        content_text = request.form.get('content', '').strip()
        News(title=request.form.get('title'), content=content_text, category='declaration', author=user.username, status='approved' if getattr(user, 'role', '') == 'admin' else 'pending').save()
        flash('تم النشر/قيد المراجعة', 'success')
        return redirect(url_for('declarations'))
    user.last_seen_decs = datetime.utcnow(); user.save()
    return render_template('declarations.html', decs=News.objects(category='declaration', status='approved').order_by('-created_at'))

@app.route('/store')
@login_required
def store():
    user = User.objects(id=session['user_id']).first()
    user.last_seen_store = datetime.utcnow(); user.save()
    return render_template('store.html', items=StoreItem.objects())

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': flash('الأشباح لا تشتري!', 'error'); return redirect(url_for('store'))
    item = StoreItem.objects(id=item_id).first()
    if user and item and user.points >= item.price:
        user.points -= item.price; user.inventory.append(item.name); user.save(); flash('اشتريت الأداة', 'success')
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated').order_by('-id'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'toggle_global_news':
            settings.global_news_active = not settings.global_news_active
            settings.global_news_text = request.form.get('global_news_text', '')
            settings.save(); flash('تحديث الشريط الإخباري', 'success')

        elif action == 'setup_gates':
            settings.gates_mode_active = True
            settings.gates_selection_locked = True if request.form.get('locked') else False
            settings.gates_description = request.form.get('desc', '')
            settings.gate_1_name = request.form.get('g1', ''); settings.gate_2_name = request.form.get('g2', ''); settings.gate_3_name = request.form.get('g3', '')
            settings.gates_test_message = request.form.get('test_msg', '')
            settings.save(); flash('تم ضبط البوابات!', 'success')

        elif action == 'close_gates_mode':
            settings.gates_mode_active = False; settings.save(); flash('تم إيقاف المود', 'success')
            
        elif action == 'judge_gates':
            fates = {1: request.form.get('fate_1'), 2: request.form.get('fate_2'), 3: request.form.get('fate_3')}
            for u in User.objects(gate_status='waiting', status='active'):
                fate = fates.get(u.chosen_gate)
                if fate == 'pass': u.gate_status = 'passed'
                elif fate == 'kill': u.status = 'eliminated'; u.freeze_reason = 'اختار بوابة الموت'
                elif fate == 'test': u.gate_status = 'testing'
                u.save()
            flash('تم إصدار الحكم!', 'success')

        elif action == 'judge_test_user':
            uid = request.form.get('user_id'); decision = request.form.get('decision')
            u = User.objects(id=uid).first()
            if u:
                if decision == 'pass': u.gate_status = 'passed'; flash(f'إنجاح {u.username}', 'success')
                elif decision == 'kill': u.status = 'eliminated'; u.freeze_reason = 'فشل في الاختبار'; flash(f'إعدام {u.username}', 'success')
                u.save()

        elif action == 'emergency_gate':
            uid = int(request.form.get('hunter_id', 0)); gate_num = int(request.form.get('gate_num', 0))
            u = User.objects(hunter_id=uid).first()
            if u: u.chosen_gate = gate_num; u.gate_status = 'waiting'; u.save(); flash('تدخل يدوي ناجح', 'success')
                
        elif action == 'toggle_floor3':
            settings.floor3_mode_active = not settings.floor3_mode_active; settings.save(); flash('تبديل الطابق الثالث', 'success')

        elif action == 'punish_floor3_slackers':
            slackers = User.objects(has_voted=False, status='active', role='hunter')
            if slackers.count() > 0:
                total_stolen = slackers.count() * 100
                active_voters = User.objects(has_voted=True, status='active', role='hunter')
                if active_voters.count() > 0:
                    bonus = total_stolen // active_voters.count()
                    for v in active_voters: v.survival_votes += bonus; v.save()
                for s in slackers: s.status = 'eliminated'; s.freeze_reason = 'خائن لم يوزع أصواته'; s.save()
                flash(f'أعدمت الكسالى ووزعت {total_stolen} صوت!', 'success')
        
        return redirect(url_for('admin_panel'))
        
    users = [u for u in User.objects() if getattr(u, 'role', 'hunter') not in ['ghost', 'cursed_ghost']]
    test_users = User.objects(gate_status='testing', status='active')
    gate_stats = {1: User.objects(chosen_gate=1, status='active').count(), 2: User.objects(chosen_gate=2, status='active').count(), 3: User.objects(chosen_gate=3, status='active').count()}
    floor3_leaders = User.objects(status='active', role='hunter').order_by('-survival_votes')[:5] if settings.floor3_mode_active else []
    
    return render_template('admin.html', users=users, settings=settings, test_users=test_users, gate_stats=gate_stats, floor3_leaders=floor3_leaders)

if __name__ == '__main__': app.run(debug=True)
