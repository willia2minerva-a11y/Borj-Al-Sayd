from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings
from functools import wraps
from datetime import datetime, timedelta
import os
import base64

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

@app.before_request
def check_locks_and_status():
    if request.endpoint in ['login', 'register', 'logout', 'static']: return
    if 'user_id' in session:
        user = User.objects(id=session['user_id']).first()
        if not user: return redirect(url_for('logout'))
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

@app.context_processor
def inject_notifications():
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'current_user': None}
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
    return render_template('profile.html', user=user, zone_class=zones.get(user.zone, 'floor-0'), banner_url=settings.banner_url if settings else '')

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or getattr(target_user, 'role', '') in ['ghost', 'cursed_ghost']:
        flash('هذا الرحالة غير موجود!', 'error'); return redirect(request.referrer or url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    zones = {0: 'floor-0', 1: 'floor-1', 2: 'floor-2', 3: 'floor-3', 4: 'floor-4', 5: 'floor-5'}
    return render_template('hunter_profile.html', target_user=target_user, zone_class=zones.get(target_user.zone, 'floor-0'), banner_url=settings.banner_url if settings else '')

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    action = request.form.get('action')
    if action == 'change_avatar':
        file = request.files.get('avatar_file')
        if file: user.avatar = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
        flash('تم تحديث صورتك في المخطوطة!', 'success')
    elif action == 'change_name':
        new_name = request.form.get('new_name')
        if not User.objects(username=new_name).first() and (not user.last_name_change or (datetime.utcnow() - user.last_name_change).days >= 15):
            user.username = new_name; user.last_name_change = datetime.utcnow()
            flash('تم تغيير اسمك بنجاح!', 'success')
        else: flash('لا يمكنك تغيير الاسم الآن أو الاسم محجوز.', 'error')
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
    if user.status == 'frozen': flash('أنت مقيد! لا يمكنك التحالف أو الصيد.', 'error'); return redirect(request.referrer or url_for('friends'))
    
    target_id = int(request.form.get('target_id'))
    target = User.objects(hunter_id=target_id).first()
    
    if target and getattr(target, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target_id)).first()
        if getattr(target, 'role', '') == 'cursed_ghost' and trap:
            user.points -= trap.trap_penalty_points; user.save()
            flash(f'لقد أيقظت شبحاً ملعوناً من سيفار! خصم منك {trap.trap_penalty_points} نقطة كعقوبة. 💀', 'error')
        elif trap and str(user.id) not in trap.winners_list and trap.current_winners < trap.max_winners:
            user.points += trap.reward_points; user.stats_ghosts_caught += 1
            trap.current_winners += 1; trap.winners_list.append(str(user.id))
            user.save(); trap.save(); check_achievements(user)
            flash(f'نجحت باصطياد شبح من أشباح المتاهة! حصلت على {trap.reward_points} نقطة حكمة 👻', 'success')
        else: flash('هذا الشبح هرب أو استنزفت طاقته.', 'error')
        return redirect(request.referrer or url_for('friends'))
        
    if target and target.status != 'eliminated' and target.hunter_id not in user.friends and user.hunter_id not in target.friend_requests:
        target.friend_requests.append(user.hunter_id); target.save(); flash('تم إرسال طلب التحالف للقافلة.', 'success')
    return redirect(request.referrer or url_for('friends'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    user = User.objects(id=session['user_id']).first()
    target = User.objects(hunter_id=target_id).first()
    if target and user.hunter_id in target.friend_requests:
        target.friend_requests.remove(user.hunter_id); target.save(); flash('تم إلغاء الطلب.', 'success')
    return redirect(request.referrer or url_for('friends'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = User.objects(id=session['user_id']).first()
    if friend_id in user.friend_requests:
        user.friend_requests.remove(friend_id); user.friends.append(friend_id)
        friend = User.objects(hunter_id=friend_id).first()
        if friend: friend.friends.append(user.hunter_id); friend.save()
        user.save(); check_achievements(user); flash('تم قبول التحالف! 🤝', 'success')
    return redirect(request.referrer or url_for('friends'))

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
        if user.status == 'frozen': flash('أطرافك متجمدة، لا يمكنك فك المخطوطات الآن.', 'error'); return redirect(url_for('puzzles'))
        now = datetime.utcnow()
        if getattr(user, 'role', '') != 'admin' and user.last_guess_time:
            time_passed = (now - user.last_guess_time).total_seconds()
            if time_passed < 300:
                flash(f'انتظر {int((300 - time_passed) // 60)} دقيقة لتستعيد تركيزك.', 'error'); return redirect(url_for('puzzles'))
        
        guess = request.form.get('guess'); puzzle_id = request.form.get('puzzle_id')
        puzzle = News.objects(id=puzzle_id).first()
        user.last_guess_time = now 
        
        if puzzle and puzzle.current_winners < puzzle.max_winners and guess == puzzle.puzzle_answer and str(user.id) not in puzzle.winners_list:
            user.points += puzzle.reward_points; user.stats_puzzles_solved += 1
            puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
            puzzle.save(); user.save(); check_achievements(user)
            flash(f'نجحت في فك طلاسم المخطوطة! حصلت على {puzzle.reward_points} نقطة 📜', 'success')
        else: flash('إجابة خاطئة... طلاسم معقدة!', 'error')
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
        user.points += puzzle.reward_points; user.stats_puzzles_solved += 1
        puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
        user.save(); puzzle.save(); check_achievements(user)
        flash(f'عثرت على ممر سري في المتاهة! أُضيفت لك {puzzle.reward_points} نقطة 🏜️', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/multi_click/<puzzle_id>')
@login_required
def multi_click(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    try:
        puzzle = News.objects(id=puzzle_id, puzzle_type='multi_click').first()
        if puzzle and str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
            user.points += puzzle.reward_points; user.stats_puzzles_solved += 1
            puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
            user.save(); puzzle.save(); check_achievements(user)
            flash('إصرارك أثمر! عثرت على نقش مخفي وكسبت النقاط 👁️', 'success')
    except: pass
    return redirect(request.referrer or url_for('home'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if getattr(user, 'status', '') != 'active':
            flash('الرحالة النشطون فقط يمكنهم تدوين المخطوطات!', 'error')
        else:
            img_b64 = ''
            file = request.files.get('image_file')
            if file and file.filename != '':
                img_b64 = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            News(title=request.form.get('title'), content=request.form.get('content', ' '), image_data=img_b64, category='declaration', author=user.username, status='pending').save()
            flash('تم إرسال تدوينتك لحكماء المتاهة بانتظار الموافقة!', 'success')
        return redirect(url_for('declarations'))
        
    user.last_seen_decs = datetime.utcnow(); user.save()
    return render_template('declarations.html', decs=News.objects(category='declaration', status='approved').order_by('-created_at'))

@app.route('/approve_dec/<news_id>', methods=['POST'])
@admin_required
def approve_dec(news_id):
    n = News.objects(id=news_id).first()
    if n: n.status = 'approved'; n.created_at = datetime.utcnow(); n.save(); flash('تمت الموافقة وتم النشر!', 'success')
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
    if user.status == 'frozen': flash('لا يمكنك مقايضة القوافل وأنت مقيد!', 'error'); return redirect(url_for('store'))
    
    item = StoreItem.objects(id=item_id).first()
    if user and item:
        if item.name in user.inventory: flash('تملك هذه الأداة مسبقاً في حقيبتك!', 'error')
        elif user.points >= item.price:
            user.points -= item.price
            if item.is_mirage:
                flash(f'لقد طاردت سراباً في الصحراء... {item.mirage_message} (خسرت {item.price} نقطة) 💨', 'error')
            else:
                user.inventory.append(item.name); user.stats_items_bought += 1; check_achievements(user)
                flash('تمت المقايضة بنجاح! 🐪', 'success')
            user.save()
        else: flash('نقاطك لا تكفي لقوافل سيفار!', 'error')
    return redirect(url_for('store'))

@app.route('/delete_news/<news_id>', methods=['POST'])
@admin_required
def delete_news(news_id):
    n = News.objects(id=news_id).first()
    if n: n.delete(); flash('تم تمزيق المخطوطة/الفخ 🗑️', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/delete_store_item/<item_id>', methods=['POST'])
@admin_required
def delete_store_item(item_id):
    item = StoreItem.objects(id=item_id).first()
    if item: item.delete(); flash('تم سحب الأداة من القوافل نهائياً! 🗑️', 'success')
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
        item.save(); flash('تم تحديث بيانات الأداة! 🛠️', 'success')
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated').order_by('-id'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    if request.method == 'POST':
        action = request.form.get('action')
        
        # التحديد الجماعي والإقصاء
        if action == 'bulk_action':
            selected = request.form.getlist('selected_users'); bulk_type = request.form.get('bulk_type')
            for uid in selected:
                u = User.objects(id=uid).first()
                if u and u.hunter_id != 1000:
                    if bulk_type == 'activate': u.status = 'active'
                    elif bulk_type == 'freeze': u.status = 'frozen'; u.freeze_reason = request.form.get('bulk_reason', 'تم تقييدك')
                    elif bulk_type == 'eliminate': u.status = 'eliminated'; u.freeze_reason = request.form.get('bulk_reason', 'هلك في المتاهة')
                    u.save()
            flash('تم تنفيذ الحكم على المحددين!', 'success')
            
        elif action == 'update_home_settings':
            settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config')
            settings.home_title = request.form.get('home_title', 'بوابة سيفار')
            settings.home_color = request.form.get('home_color', 'var(--zone-0-black)')
            file = request.files.get('banner_file')
            if file and file.filename != '': settings.banner_url = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            settings.save(); flash('تم تحديث البوابة', 'success')
            
        elif action == 'add_news':
            cat = 'puzzle' if request.form.get('puzzle_type') != 'none' else 'news'
            News(title=request.form.get('title'), content=request.form.get('content'), category=cat, puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points', 0)), max_winners=int(request.form.get('max_winners', 1))).save()
            flash('تم النشر بنجاح!', 'success')
            
        elif action == 'add_standalone_puzzle':
            ptype = request.form.get('puzzle_type')
            panswer = request.form.get('puzzle_answer', '')
            trap_dur = int(request.form.get('trap_duration', 0))
            trap_pen = int(request.form.get('trap_penalty', 0))
            News(title="لغز مخفي", content="لغز خفي", category='hidden', puzzle_type=ptype, puzzle_answer=panswer, reward_points=int(request.form.get('reward_points', 0)), max_winners=int(request.form.get('max_winners', 1)), trap_duration_minutes=trap_dur, trap_penalty_points=trap_pen).save()
            if ptype in ['fake_account', 'cursed_ghost'] and panswer.isdigit():
                role_type = 'ghost' if ptype == 'fake_account' else 'cursed_ghost'
                if not User.objects(hunter_id=int(panswer)).first():
                    User(hunter_id=int(panswer), username=f"شبح_{panswer}", password_hash="dummy", role=role_type, status='active', avatar='👻').save()
            flash('تم زرع الفخ في المتاهة بنجاح', 'success')
            
        elif action == 'add_store_item':
            is_mirage = True if request.form.get('is_mirage') == 'on' else False
            item = StoreItem(name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price')), is_mirage=is_mirage, mirage_message=request.form.get('mirage_message', ''))
            file = request.files.get('item_image')
            if file: item.image = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            item.save(); flash('تم إرسال البضاعة للقوافل', 'success')
            
        # -- إضافة/إزالة أدوات من حقيبة اللاعب --
        elif action == 'add_inventory':
            u = User.objects(id=request.form.get('user_id')).first()
            item_name = request.form.get('item_name')
            if u and item_name:
                if item_name not in u.inventory: u.inventory.append(item_name); u.save(); flash(f'تمت إضافة {item_name} لحقيبة {u.username}', 'success')
                else: flash('يملك هذه الأداة مسبقاً!', 'error')
        elif action == 'remove_inventory':
            u = User.objects(id=request.form.get('user_id')).first()
            item_name = request.form.get('item_name')
            if u and item_name:
                if item_name in u.inventory: u.inventory.remove(item_name); u.save(); flash(f'تمت مصادرة {item_name} من {u.username}', 'success')
                else: flash('لا يملك هذه الأداة لمصادرتها!', 'error')

        elif action in ['add_points', 'change_zone', 'change_rank', 'make_admin', 'remove_admin']:
            user = User.objects(id=request.form.get('user_id')).first()
            if user:
                if action == 'add_points': user.points = int(request.form.get('points_amount', 0))
                elif action == 'change_zone': user.zone = int(request.form.get('zone_num', 0))
                elif action == 'change_rank': user.special_rank = request.form.get('special_rank')
                elif action == 'make_admin': user.role = 'admin'
                elif action == 'remove_admin' and user.hunter_id != 1000: user.role = 'hunter'
                user.save(); flash('تم حفظ التعديلات الفردية', 'success')

        return redirect(url_for('admin_panel'))
        
    pending_decs = News.objects(category='declaration', status='pending')
    hidden_puzzles = News.objects(category='hidden')
    settings = GlobalSettings.objects(setting_name='main_config').first()
    return render_template('admin.html', users=User.objects(role__nin=['ghost', 'cursed_ghost']), pending_decs=pending_decs, hidden_puzzles=hidden_puzzles, settings=settings)

if __name__ == '__main__': app.run(debug=True)
