from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings
from functools import wraps
from datetime import datetime
import os
import base64

app = Flask(__name__)
app.config['MONGODB_SETTINGS'] = {'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db')}
app.config['SECRET_KEY'] = 'super-secret-hunter-key-change-later'
db.init_app(app)

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

# --- نظام حساب الإشعارات (المصحح والمحصن 100%) ---
@app.context_processor
def inject_notifications():
    # إرسال أصفار افتراضية دائماً لمنع انهيار التصميم (HTML)
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'current_user': None}
    
    if 'user_id' in session:
        try:
            user = User.objects(id=session['user_id']).first()
            if user:
                notifs['current_user'] = user
                now = datetime.utcnow()
                
                # استخدام getattr لتجنب أي خطأ إذا كانت قاعدة البيانات لم تتحدث
                ls_news = getattr(user, 'last_seen_news', now) or now
                ls_puz = getattr(user, 'last_seen_puzzles', now) or now
                ls_dec = getattr(user, 'last_seen_decs', now) or now
                ls_store = getattr(user, 'last_seen_store', now) or now
                
                notifs['un_news'] = News.objects(category='news', status='approved', created_at__gt=ls_news).count()
                notifs['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=ls_puz).count()
                notifs['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=ls_dec).count()
                notifs['un_store'] = StoreItem.objects(created_at__gt=ls_store).count()
        except Exception as e:
            # إذا حدث أي خطأ غريب، سيتجاهله بهدوء وتظل القيم أصفاراً
            pass 
            
    return notifs

@app.route('/')
def home():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    latest_news = News.objects(category='news', status='approved').order_by('-created_at').first()
    latest_dec = News.objects(category='declaration', status='approved').order_by('-created_at').first()
    last_frozen = User.objects(status='frozen').order_by('-id').first()
    return render_template('index.html', settings=settings, news=latest_news, dec=latest_dec, last_frozen=last_frozen)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        ip = request.headers.get('X-Forwarded-For', request.remote_addr) or ''
        ip = ip.split(',')[0]
        if User.objects(username=request.form['username']).first():
            flash('الاسم مستخدم.', 'error'); return redirect(url_for('register'))
        is_first = User.objects.count() == 0
        last_u = User.objects.order_by('-hunter_id').first()
        new_id = (last_u.hunter_id + 1) if last_u else 1000
        now = datetime.utcnow()
        User(hunter_id=new_id, username=request.form['username'], facebook_link=request.form['facebook_link'], password_hash=generate_password_hash(request.form['password']), role='admin' if is_first else 'hunter', status='active' if is_first else 'pending', ip_address=ip, last_seen_news=now, last_seen_puzzles=now, last_seen_decs=now, last_seen_store=now).save()
        flash('تم التسجيل بنجاح!', 'success'); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = str(user.id); session['role'] = user.role
            return redirect(url_for('home'))
        flash('بيانات خاطئة.', 'error')
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
    if not target_user or getattr(target_user, 'role', '') == 'ghost':
        flash('هذا الصائد غير موجود!', 'error'); return redirect(request.referrer or url_for('home'))
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
        flash('تم تحديث الصورة!', 'success')
    elif action == 'change_name':
        new_name = request.form.get('new_name')
        if not User.objects(username=new_name).first() and (not user.last_name_change or (datetime.utcnow() - user.last_name_change).days >= 15):
            user.username = new_name; user.last_name_change = datetime.utcnow()
            flash('تم تغيير الاسم بنجاح!', 'success')
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
    target_id = int(request.form.get('target_id'))
    target = User.objects(hunter_id=target_id).first()
    
    if target and getattr(target, 'role', '') == 'ghost':
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target_id)).first()
        if trap and str(user.id) not in trap.winners_list and trap.current_winners < trap.max_winners:
            user.points += trap.reward_points; trap.current_winners += 1; trap.winners_list.append(str(user.id))
            user.save(); trap.save(); flash('وقعـت فـي فـخ الشـبح! كسبت النقاط ببراعة.', 'success')
        else: flash('هذا الشبح لم يعد يمتلك جوائز.', 'error')
        return redirect(request.referrer or url_for('friends'))
        
    if target and target.status != 'frozen' and target.hunter_id not in user.friends and user.hunter_id not in target.friend_requests:
        target.friend_requests.append(user.hunter_id); target.save(); flash('تم إرسال الطلب.', 'success')
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
        user.save(); flash('تم قبول التحالف!', 'success')
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
        now = datetime.utcnow()
        if getattr(user, 'role', '') != 'admin' and user.last_guess_time:
            time_passed = (now - user.last_guess_time).total_seconds()
            if time_passed < 300:
                flash(f'انتظر {int((300 - time_passed) // 60)} دقيقة لمنع التخمين العشوائي.', 'error'); return redirect(url_for('puzzles'))
        
        guess = request.form.get('guess'); puzzle_id = request.form.get('puzzle_id')
        puzzle = News.objects(id=puzzle_id).first()
        user.last_guess_time = now 
        
        if puzzle and puzzle.current_winners < puzzle.max_winners and guess == puzzle.puzzle_answer and str(user.id) not in puzzle.winners_list:
            user.points += puzzle.reward_points; puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
            puzzle.save(); flash('إجابة صحيحة!', 'success')
        else: flash('إجابة خاطئة أو نفدت الجوائز!', 'error')
        user.save(); return redirect(url_for('puzzles'))
        
    user.last_seen_puzzles = datetime.utcnow(); user.save()
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if getattr(user, 'status', '') != 'active':
            flash('فقط الصيادين النشطين يمكنهم التصريح!', 'error')
        else:
            News(title=request.form.get('title'), content=request.form.get('content'), category='declaration', author=user.username, status='pending').save()
            flash('تم إرسال تصريحك للقيادة بانتظار الموافقة!', 'success')
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
    item = StoreItem.objects(id=item_id).first()
    if user and item:
        if item.name in user.inventory: flash('تملك هذه الأداة مسبقاً!', 'error')
        elif user.points >= item.price: user.points -= item.price; user.inventory.append(item.name); user.save(); flash('تم الشراء!', 'success')
        else: flash('نقاطك لا تكفي!', 'error')
    return redirect(url_for('store'))

@app.route('/delete_news/<news_id>', methods=['POST'])
@admin_required
def delete_news(news_id):
    n = News.objects(id=news_id).first()
    if n: n.delete(); flash('تم السحق 🗑️', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/approve_dec/<news_id>', methods=['POST'])
@admin_required
def approve_dec(news_id):
    n = News.objects(id=news_id).first()
    if n: n.status = 'approved'; n.created_at = datetime.utcnow(); n.save(); flash('تمت الموافقة وتم النشر!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    try:
        puzzle = News.objects(id=puzzle_id, puzzle_type='secret_link').first()
        if puzzle and str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
            user.points += puzzle.reward_points; puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
            user.save(); puzzle.save(); flash('اكتشفت الرابط السري!', 'success')
    except: pass
    return redirect(url_for('puzzles'))

@app.route('/multi_click/<puzzle_id>')
@login_required
def multi_click(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    try:
        puzzle = News.objects(id=puzzle_id, puzzle_type='multi_click').first()
        if puzzle and str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
            user.points += puzzle.reward_points; puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
            user.save(); puzzle.save(); flash('إصرارك أثمر! حصلت على النقطة.', 'success')
    except: pass
    return redirect(request.referrer or url_for('home'))

@app.route('/delete_store_item/<item_id>', methods=['POST'])
@admin_required
def delete_store_item(item_id):
    item = StoreItem.objects(id=item_id).first()
    if item: item.delete(); flash('تم سحب الأداة من السوق نهائياً! 🗑️', 'success')
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
        item.save(); flash('تم تحديث بيانات الأداة بنجاح! 🛠️', 'success')
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='frozen').order_by('-id'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'bulk_action':
            selected = request.form.getlist('selected_users'); bulk_type = request.form.get('bulk_type')
            for uid in selected:
                u = User.objects(id=uid).first()
                if u and u.hunter_id != 1000:
                    if bulk_type == 'activate': u.status = 'active'
                    elif bulk_type == 'freeze': u.status = 'frozen'; u.freeze_reason = request.form.get('bulk_reason', 'تم الإقصاء')
                    u.save()
            flash('تم تنفيذ الأمر الجماعي!', 'success')
            
        elif action == 'update_home_settings':
            settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config')
            settings.home_title = request.form.get('home_title', 'البوابة')
            settings.home_color = request.form.get('home_color', 'var(--zone-0-black)')
            file = request.files.get('banner_file')
            if file and file.filename != '': settings.banner_url = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            settings.save(); flash('تم تحديث الرئيسية', 'success')
            
        elif action == 'add_news':
            cat = 'puzzle' if request.form.get('puzzle_type') != 'none' else 'news'
            News(title=request.form.get('title'), content=request.form.get('content'), category=cat, puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points', 0)), max_winners=int(request.form.get('max_winners', 1))).save()
            flash('تم النشر!', 'success')
            
        elif action == 'add_standalone_puzzle':
            ptype = request.form.get('puzzle_type'); panswer = request.form.get('puzzle_answer')
            News(title="لغز مخفي", content="لغز خفي", category='hidden', puzzle_type=ptype, puzzle_answer=panswer, reward_points=int(request.form.get('reward_points', 0)), max_winners=int(request.form.get('max_winners', 1))).save()
            if ptype == 'fake_account' and panswer.isdigit():
                if not User.objects(hunter_id=int(panswer)).first():
                    User(hunter_id=int(panswer), username=f"Ghost_{panswer}", password_hash="dummy", role='ghost', status='active', avatar='👻').save()
            flash('تم توليد الفخ', 'success')
            
        elif action == 'add_store_item':
            item = StoreItem(name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price')))
            file = request.files.get('item_image')
            if file: item.image = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            item.save(); flash('تم الإضافة', 'success')
            
        elif action in ['activate', 'freeze', 'add_points', 'change_zone', 'change_rank', 'make_admin', 'remove_admin']:
            user = User.objects(id=request.form.get('user_id')).first()
            if user:
                if action == 'freeze' and user.hunter_id != 1000: user.status = 'frozen'; user.freeze_reason = request.form.get('freeze_reason', '')
                elif action == 'activate': user.status = 'active'
                elif action == 'add_points': user.points = int(request.form.get('points_amount', 0))
                elif action == 'change_zone': user.zone = int(request.form.get('zone_num', 0))
                elif action == 'change_rank': user.special_rank = request.form.get('special_rank')
                elif action == 'make_admin': user.role = 'admin'
                elif action == 'remove_admin' and user.hunter_id != 1000: user.role = 'hunter'
                user.save(); flash('تم حفظ التعديلات', 'success')

        return redirect(url_for('admin_panel'))
        
    pending_decs = News.objects(category='declaration', status='pending')
    hidden_puzzles = News.objects(category='hidden')
    settings = GlobalSettings.objects(setting_name='main_config').first()
    return render_template('admin.html', users=User.objects(role__ne='ghost'), pending_decs=pending_decs, hidden_puzzles=hidden_puzzles, settings=settings)

if __name__ == '__main__': app.run(debug=True)
