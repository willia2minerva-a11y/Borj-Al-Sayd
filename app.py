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

def check_war_and_bleed(user, settings):
    if not settings or not getattr(settings, 'war_mode', False) or getattr(user, 'status', '') != 'active' or getattr(user, 'role', '') == 'admin':
        return
        
    now = datetime.utcnow()
    safe_until = getattr(user, 'last_action_time', now) + timedelta(minutes=settings.safe_time_minutes)
    
    if now > safe_until:
        start_bleed_time = max(getattr(user, 'last_health_check', safe_until), safe_until)
        minutes_passed = (now - start_bleed_time).total_seconds() / 60.0
        
        if minutes_passed >= settings.bleed_rate_minutes and settings.bleed_rate_minutes > 0:
            cycles = math.floor(minutes_passed / settings.bleed_rate_minutes)
            total_damage = cycles * settings.bleed_amount
            
            user.health -= total_damage
            user.last_health_check = now
            
            if user.health <= 0:
                user.health = 0
                user.status = 'eliminated'
                user.freeze_reason = 'نزف حتى الموت في حرب المتاهة'
                settings.dead_count += 1
                settings.save()
            user.save()

@app.before_request
def check_locks_and_status():
    if request.endpoint in ['login', 'register', 'logout', 'static']: return
    
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    
    if 'user_id' in session:
        user = User.objects(id=session['user_id']).first()
        if not user: return redirect(url_for('logout'))
        
        if settings.maintenance_mode and user.role != 'admin':
            return render_template('locked.html', message='تهب عاصفة رملية شديدة في المتاهة، الرؤية معدومة... جاري ترميم النقوش، عد لاحقاً. ⏳', time_left=None)
            
        check_war_and_bleed(user, settings)
        
        if user.status == 'eliminated':
            session.pop('user_id', None); session.pop('role', None)
            return render_template('locked.html', message='لقد هلكت في متاهة سيفار... جسدك أصبح مجرد أثر في المقبرة المنسية. 💀', time_left=None)
            
        if user.quicksand_lock_until and datetime.utcnow() < user.quicksand_lock_until:
            time_left = user.quicksand_lock_until - datetime.utcnow()
            mins, secs = divmod(time_left.seconds, 60)
            return render_template('locked.html', message='لقد ابتلعتك الرمال المتحركة! 🏜️ أطرافك مشلولة.', time_left=f"{mins} دقيقة و {secs} ثانية")

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

# 🚀 الحل الجذري تم تطبيقه هنا لمنع انهيار الصفحة للزوار 🚀
@app.context_processor
def inject_notifications():
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'current_user': None, 'war_settings': None, 'battle_logs': []}
    
    # 1. جلب إعدادات الحرب للجميع (الزوار والمسجلين)
    try:
        notifs['war_settings'] = GlobalSettings.objects(setting_name='main_config').first()
        if notifs['war_settings'] and getattr(notifs['war_settings'], 'war_mode', False):
            notifs['battle_logs'] = BattleLog.objects().order_by('-created_at')[:5]
    except Exception:
        pass

    # 2. جلب إشعارات المستخدم إذا كان مسجلاً
    if 'user_id' in session:
        try:
            user = User.objects(id=session['user_id']).first()
            if user:
                notifs['current_user'] = user; now = datetime.utcnow()
                ls_news = getattr(user, 'last_seen_news', now) or now
                ls_puz = getattr(user, 'last_seen_puzzles', now) or now
                ls_dec = getattr(user, 'last_seen_decs', now) or now
                ls_store = getattr(user, 'last_seen_store', now) or now
                notifs['un_news'] = News.objects(category='news', status='approved', created_at__gt=ls_news).count()
                notifs['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=ls_puz).count()
                notifs['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=ls_dec).count()
                notifs['un_store'] = StoreItem.objects(created_at__gt=ls_store).count()
        except Exception: pass 
        
    return notifs

@app.route('/')
def home():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    latest_news = News.objects(category='news', status='approved').order_by('-created_at').first()
    latest_dec = News.objects(category='declaration', status='approved').order_by('-created_at').first()
    last_frozen = User.objects(status='eliminated').order_by('-id').first()
    return render_template('index.html', settings=settings, news=latest_news, dec=latest_dec, last_frozen=last_frozen)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        ip = request.headers.get('X-Forwarded-For', request.remote_addr) or ''
        ip = ip.split(',')[0]
        if User.objects(username=request.form['username']).first():
            flash('الاسم مستخدم مسبقاً في المتاهة.', 'error'); return redirect(url_for('register'))
        is_first = User.objects.count() == 0
        last_u = User.objects.order_by('-hunter_id').first()
        new_id = (last_u.hunter_id + 1) if last_u else 1000
        now = datetime.utcnow()
        User(hunter_id=new_id, username=request.form['username'], facebook_link=request.form['facebook_link'], password_hash=generate_password_hash(request.form['password']), role='admin' if is_first else 'hunter', status='active', ip_address=ip, last_seen_news=now, last_seen_puzzles=now, last_seen_decs=now, last_seen_store=now).save()
        flash('تم التسجيل! مرحباً بك في متاهة سيفار.', 'success'); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
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
    my_items = []
    if user.inventory: my_items = StoreItem.objects(name__in=user.inventory)
    return render_template('profile.html', user=user, zone_class=zones.get(user.zone, 'floor-0'), banner_url=settings.banner_url if settings else '', my_items=my_items)

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']:
        flash('هذا الرحالة غير موجود!', 'error'); return redirect(request.referrer or url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    zones = {0: 'floor-0', 1: 'floor-1', 2: 'floor-2', 3: 'floor-3', 4: 'floor-4', 5: 'floor-5'}
    current_user = User.objects(id=session['user_id']).first()
    my_weapons = []; my_heals = []
    if current_user.inventory:
        items = StoreItem.objects(name__in=current_user.inventory)
        my_weapons = [i for i in items if i.item_type == 'weapon']
        my_heals = [i for i in items if i.item_type == 'heal']
    return render_template('hunter_profile.html', target_user=target_user, zone_class=zones.get(target_user.zone, 'floor-0'), banner_url=settings.banner_url if settings else '', my_weapons=my_weapons, my_heals=my_heals)

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    attacker = User.objects(id=session['user_id']).first()
    target = User.objects(hunter_id=target_id).first()
    settings = GlobalSettings.objects(setting_name='main_config').first()
    item_name = request.form.get('item_name')
    item = StoreItem.objects(name=item_name).first()
    
    if not target or not item or item_name not in attacker.inventory:
        flash('عملية غير صالحة.', 'error'); return redirect(request.referrer)
    if not settings.war_mode and item.item_type in ['weapon', 'heal']:
        flash('المتاهة في حالة سلام حالياً.', 'error'); return redirect(request.referrer)

    now = datetime.utcnow()
    if item.item_type == 'weapon':
        if target.hunter_id in attacker.friends: flash('لا يمكنك طعن حليفك! الغِ التحالف أولاً.', 'error'); return redirect(request.referrer)
        if target.status != 'active': flash('لا يمكنك طعن جثة!', 'error'); return redirect(request.referrer)
            
        target.health -= item.effect_amount
        if target.health <= 0:
            target.health = 0; target.status = 'eliminated'; target.freeze_reason = 'تمت تصفيته في حرب المتاهة'
            settings.dead_count += 1; settings.save()
            flash(f'💀 ضربة قاتلة! تم القضاء على {target.username}!', 'success')
            if settings.dead_count >= settings.max_dead_to_end:
                settings.war_mode = False; settings.dead_count = 0; settings.save()
                User.objects(status='active').update(health=100)
                flash('🔥 سقط العدد المطلوب... توقفت الحرب وعادت صحة الناجين 100%!', 'success')
        else: flash(f'🗡️ تمت الضربة! فقد {item.effect_amount} من صحته.', 'success')
            
        BattleLog(victim_name=target.username, weapon_name=item.name, remaining_hp=target.health).save()
        target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save()
        
    elif item.item_type == 'heal':
        if target.id != attacker.id and target.hunter_id not in attacker.friends:
            flash('عالج نفسك أو حلفائك فقط!', 'error'); return redirect(request.referrer)
        if target.status != 'active': flash('لا يمكن علاج الأموات!', 'error'); return redirect(request.referrer)
            
        target.health = min(100, target.health + item.effect_amount)
        target.save(); attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save()
        flash(f'🧪 تم العلاج! صحة {target.username} أصبحت {target.health}', 'success')
        
    return redirect(request.referrer)

@app.route('/admin_update_profile/<int:target_id>', methods=['POST'])
@admin_required
def admin_update_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if target_user:
        action = request.form.get('action')
        if action == 'edit_name':
            new_name = request.form.get('new_name')
            if not User.objects(username=new_name).first() or new_name == target_user.username:
                target_user.username = new_name; target_user.save(); flash('تم تعديل الاسم!', 'success')
            else: flash('الاسم مستخدم!', 'error')
        elif action == 'edit_points':
            target_user.points = int(request.form.get('new_points', target_user.points))
            target_user.save(); flash('تم التعديل!', 'success')
        elif action == 'edit_hp':
            target_user.health = int(request.form.get('new_hp', target_user.health))
            if target_user.health <= 0:
                target_user.health = 0; target_user.status = 'eliminated'; target_user.freeze_reason = 'أعدم بأمر القيادة'
            elif target_user.health > 0 and target_user.status == 'eliminated':
                target_user.status = 'active'
            target_user.save(); flash('تم تعديل الصحة!', 'success')
    return redirect(url_for('hunter_profile', target_id=target_id))

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    action = request.form.get('action')
    if action == 'change_avatar':
        file = request.files.get('avatar_file')
        if file: user.avatar = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"; flash('تم التحديث!', 'success')
    user.save(); return redirect(url_for('profile'))

@app.route('/friends', methods=['GET'])
@login_required
def friends():
    user = User.objects(id=session['user_id']).first()
    search_query = request.args.get('search')
    search_result = None
    if search_query:
        if search_query.isdigit(): search_result = User.objects(hunter_id=int(search_query)).first()
        else: search_result = User.objects(username__icontains=search_query).first()
    return render_template('friends.html', user=user, search_result=search_result, friend_requests=User.objects(hunter_id__in=user.friend_requests), friends=User.objects(hunter_id__in=user.friends))

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = User.objects(id=session['user_id']).first()
    if user.status != 'active': flash('أنت غير نشط!', 'error'); return redirect(request.referrer)
    
    target_id = int(request.form.get('target_id'))
    target = User.objects(hunter_id=target_id).first()
    if target and getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target_id)).first()
        if getattr(target, 'role', '') == 'cursed_ghost' and trap:
            user.points -= trap.trap_penalty_points; user.save(); flash(f'لقد أيقظت شبحاً ملعوناً! خصم منك {trap.trap_penalty_points} نقطة. 💀', 'error')
        elif trap and str(user.id) not in trap.winners_list and trap.current_winners < trap.max_winners:
            user.points += trap.reward_points; user.stats_ghosts_caught += 1; trap.current_winners += 1; trap.winners_list.append(str(user.id))
            user.save(); trap.save(); check_achievements(user); flash(f'اصطدت شبحاً! +{trap.reward_points} نقطة 👻', 'success')
        else: flash('الشبح هرب.', 'error')
        return redirect(request.referrer)
        
    if target and target.status != 'eliminated' and target.hunter_id not in user.friends and user.hunter_id not in target.friend_requests:
        target.friend_requests.append(user.hunter_id); target.save(); flash('تم الإرسال.', 'success')
    return redirect(request.referrer)

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = User.objects(id=session['user_id']).first()
    target = User.objects(hunter_id=target_id).first()
    if target:
        if user.hunter_id in target.friend_requests:
            target.friend_requests.remove(user.hunter_id); target.save(); flash('تم إلغاء الطلب.', 'success')
        elif target.hunter_id in user.friends:
            user.friends.remove(target.hunter_id); target.friends.remove(user.hunter_id)
            user.save(); target.save(); flash('تم خرق التحالف! 💔 يمكنكم الآن مهاجمة بعضكم.', 'success')
    return redirect(request.referrer)

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = User.objects(id=session['user_id']).first()
    if friend_id in user.friend_requests:
        user.friend_requests.remove(friend_id); user.friends.append(friend_id)
        friend = User.objects(hunter_id=friend_id).first()
        if friend: friend.friends.append(user.hunter_id); friend.save()
        user.save(); check_achievements(user); flash('تم قبول التحالف! 🤝', 'success')
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
        if user.status != 'active': flash('لا يمكنك الحل!', 'error'); return redirect(url_for('puzzles'))
        now = datetime.utcnow()
        if getattr(user, 'role', '') != 'admin' and user.last_guess_time:
            time_passed = (now - user.last_guess_time).total_seconds()
            if time_passed < 300: flash('انتظر!', 'error'); return redirect(url_for('puzzles'))
        
        guess = request.form.get('guess'); puzzle_id = request.form.get('puzzle_id')
        puzzle = News.objects(id=puzzle_id).first()
        user.last_guess_time = now 
        
        if puzzle and puzzle.current_winners < puzzle.max_winners and guess == puzzle.puzzle_answer and str(user.id) not in puzzle.winners_list:
            user.points += puzzle.reward_points; user.stats_puzzles_solved += 1; puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
            puzzle.save(); user.save(); check_achievements(user); flash('صحيح!', 'success')
        else: flash('خطأ!', 'error')
        return redirect(url_for('puzzles'))
        
    user.last_seen_puzzles = datetime.utcnow(); user.save()
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    puzzle = News.objects(id=puzzle_id).first()
    if puzzle and puzzle.puzzle_type == 'quicksand_trap':
        user.quicksand_lock_until = datetime.utcnow() + timedelta(minutes=puzzle.trap_duration_minutes)
        user.save(); return redirect(url_for('home'))
    elif puzzle and puzzle.puzzle_type == 'secret_link' and str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
        user.points += puzzle.reward_points; user.stats_puzzles_solved += 1; puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
        user.save(); puzzle.save(); check_achievements(user); flash('صحيح!', 'success')
    return redirect(request.referrer)

@app.route('/multi_click/<puzzle_id>')
@login_required
def multi_click(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    try:
        puzzle = News.objects(id=puzzle_id, puzzle_type='multi_click').first()
        if puzzle and str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
            user.points += puzzle.reward_points; user.stats_puzzles_solved += 1; puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
            user.save(); puzzle.save(); check_achievements(user); flash('صحيح!', 'success')
    except: pass
    return redirect(request.referrer)

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if getattr(user, 'role', '') != 'admin' and getattr(user, 'status', '') != 'active':
            flash('الرحالة النشطون فقط!', 'error')
        else:
            img_b64 = ''; file = request.files.get('image_file')
            if file and file.filename != '': img_b64 = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            content_text = request.form.get('content', '').strip()
            if not content_text: content_text = "مخطوطة غامضة بلا كلمات..." 
            post_status = 'approved' if getattr(user, 'role', '') == 'admin' else 'pending'
            News(title=request.form.get('title'), content=content_text, image_data=img_b64, category='declaration', author=user.username, status=post_status).save()
            if post_status == 'approved': flash('نُشرت!', 'success')
            else: flash('قيد المراجعة!', 'success')
        return redirect(url_for('declarations'))
        
    user.last_seen_decs = datetime.utcnow(); user.save()
    return render_template('declarations.html', decs=News.objects(category='declaration', status='approved').order_by('-created_at'))

@app.route('/approve_dec/<news_id>', methods=['POST'])
@admin_required
def approve_dec(news_id):
    n = News.objects(id=news_id).first()
    if n: n.status = 'approved'; n.created_at = datetime.utcnow(); n.save(); flash('نُشرت!', 'success')
    return redirect(url_for('admin_panel'))

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
    if user.status != 'active': flash('أنت غير نشط!', 'error'); return redirect(url_for('store'))
    
    item = StoreItem.objects(id=item_id).first()
    if user and item:
        if not item.is_luck and item.name in user.inventory: 
            flash('تملك هذه الأداة/السلاح في حقيبتك مسبقاً! استخدمها أولاً.', 'error')
        elif user.points >= item.price:
            user.points -= item.price
            if item.is_luck:
                outcome = random.randint(item.luck_min, item.luck_max)
                user.points += outcome
                if outcome > 0: flash(f'حظ! +{outcome}', 'success')
                elif outcome < 0: flash(f'لعنة! -{abs(outcome)}', 'error')
                else: flash('فارغ.', 'info')
                user.stats_items_bought += 1; check_achievements(user)
            elif item.is_mirage:
                flash(f'سراب! {item.mirage_message} (-{item.price})', 'error')
            else:
                user.inventory.append(item.name); user.stats_items_bought += 1; check_achievements(user)
                flash('أضيفت لحقيبتك. 🐪', 'success')
            user.save()
        else: flash('نقاط لا تكفي!', 'error')
    return redirect(url_for('store'))

@app.route('/delete_news/<news_id>', methods=['POST'])
@admin_required
def delete_news(news_id):
    n = News.objects(id=news_id).first()
    if n: n.delete(); flash('سُحقت 🗑️', 'success')
    return redirect(request.referrer)

@app.route('/delete_store_item/<item_id>', methods=['POST'])
@admin_required
def delete_store_item(item_id):
    item = StoreItem.objects(id=item_id).first()
    if item: item.delete(); flash('سُحبت 🗑️', 'success')
    return redirect(url_for('store'))

@app.route('/edit_store_item/<item_id>', methods=['POST'])
@admin_required
def edit_store_item(item_id):
    item = StoreItem.objects(id=item_id).first()
    if item:
        item.name = request.form.get('item_name', item.name)
        item.description = request.form.get('item_desc', item.description)
        item.price = int(request.form.get('item_price', item.price))
        file = request.files.get('item_image')
        if file and file.filename != '': item.image = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
        item.save(); flash('تُحدثت!', 'success')
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated').order_by('-id'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'toggle_maintenance':
            settings.maintenance_mode = not settings.maintenance_mode; settings.save(); flash('تم تبديل وضع الصيانة!', 'success')
        elif action == 'toggle_war':
            settings.war_mode = not settings.war_mode
            if not settings.war_mode:
                User.objects(status='active').update(health=100); settings.dead_count = 0; flash('تم إنهاء الحرب! عادة الصحة للناجين.', 'success')
            else: flash('🔥 دقت طبول الحرب! النزيف بدأ.', 'success')
            settings.save()
        elif action == 'update_war_settings':
            settings.bleed_rate_minutes = int(request.form.get('bleed_rate_minutes', 60))
            settings.bleed_amount = int(request.form.get('bleed_amount', 1))
            settings.safe_time_minutes = int(request.form.get('safe_time_minutes', 120))
            settings.max_dead_to_end = int(request.form.get('max_dead_to_end', 15))
            settings.save(); flash('تم حفظ إعدادات الحرب', 'success')
            
        elif action == 'bulk_action':
            selected = request.form.getlist('selected_users'); bulk_type = request.form.get('bulk_type')
            for uid in selected:
                u = User.objects(id=uid).first()
                if u and u.hunter_id != 1000:
                    if bulk_type == 'activate': u.status = 'active'; u.health = 100
                    elif bulk_type == 'freeze': u.status = 'frozen'; u.freeze_reason = request.form.get('bulk_reason', 'مقيّد')
                    elif bulk_type == 'eliminate': u.status = 'eliminated'; u.freeze_reason = request.form.get('bulk_reason', 'هلك')
                    u.save()
            flash('تم!', 'success')
            
        elif action == 'update_home_settings':
            settings.home_title = request.form.get('home_title', 'البوابة')
            settings.home_color = request.form.get('home_color', 'var(--zone-0-black)')
            file = request.files.get('banner_file')
            if file and file.filename != '': settings.banner_url = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            settings.save(); flash('تم!', 'success')
            
        elif action == 'add_news':
            cat = 'puzzle' if request.form.get('puzzle_type') != 'none' else 'news'
            News(title=request.form.get('title'), content=request.form.get('content'), category=cat, puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points', 0)), max_winners=int(request.form.get('max_winners', 1))).save(); flash('نُشرت!', 'success')
            
        elif action == 'add_standalone_puzzle':
            ptype = request.form.get('puzzle_type'); panswer = request.form.get('puzzle_answer', '')
            trap_dur = int(request.form.get('trap_duration', 0) or 0); trap_pen = int(request.form.get('trap_penalty', 0) or 0)
            News(title="لغز مخفي", content="لغز خفي", category='hidden', puzzle_type=ptype, puzzle_answer=panswer, reward_points=int(request.form.get('reward_points', 0)), max_winners=int(request.form.get('max_winners', 1)), trap_duration_minutes=trap_dur, trap_penalty_points=trap_pen).save()
            if ptype in ['fake_account', 'cursed_ghost'] and panswer.isdigit():
                role_type = 'ghost' if ptype == 'fake_account' else 'cursed_ghost'
                if not User.objects(hunter_id=int(panswer)).first(): User(hunter_id=int(panswer), username=f"شبح_{panswer}", password_hash="dummy", role=role_type, status='active', avatar='👻').save()
            flash('زرع الفخ', 'success')
            
        elif action == 'add_store_item':
            item_type = request.form.get('item_type', 'normal')
            effect_amount = int(request.form.get('effect_amount', 0) or 0)
            is_mirage = True if request.form.get('is_mirage') == 'on' else False
            is_luck = True if request.form.get('is_luck') == 'on' else False
            l_min = int(request.form.get('luck_min', 0) or 0); l_max = int(request.form.get('luck_max', 0) or 0)
            item = StoreItem(name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price')), item_type=item_type, effect_amount=effect_amount, is_mirage=is_mirage, mirage_message=request.form.get('mirage_message', ''), is_luck=is_luck, luck_min=l_min, luck_max=l_max)
            file = request.files.get('item_image')
            if file: item.image = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            item.save(); flash('إلى القافلة!', 'success')
            
        elif action == 'add_inventory':
            u = User.objects(id=request.form.get('user_id')).first()
            item_name = request.form.get('item_name')
            if u and item_name:
                if item_name not in u.inventory: u.inventory.append(item_name); u.save(); flash(f'أضيفت لـ {u.username}', 'success')
                else: flash('يملكها!', 'error')
                
        elif action == 'remove_inventory':
            u = User.objects(id=request.form.get('user_id')).first()
            item_name = request.form.get('item_name')
            if u and item_name:
                if item_name in u.inventory: u.inventory.remove(item_name); u.save(); flash(f'صودرت من {u.username}', 'success')
                else: flash('لا يملكها!', 'error')

        elif action == 'add_points':
            user = User.objects(id=request.form.get('user_id')).first()
            if user: user.points = int(request.form.get('points_amount', 0)); user.save(); flash('حُفظت!', 'success')

        return redirect(url_for('admin_panel'))
        
    try:
        pending_decs = News.objects(category='declaration', status='pending')
        pending_count = pending_decs.count()
    except Exception:
        pending_decs = []; pending_count = 0
        
    hidden_puzzles = News.objects(category='hidden')
    safe_users = [u for u in User.objects() if getattr(u, 'role', 'hunter') not in ['ghost', 'cursed_ghost']]
    
    return render_template('admin.html', users=safe_users, pending_decs=pending_decs, pending_count=pending_count, hidden_puzzles=hidden_puzzles, settings=settings)

if __name__ == '__main__': app.run(debug=True)
