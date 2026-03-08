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
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
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

# --- الرئيسية والتسجيل ---
@app.route('/')
def home():
    active_users = User.objects(status='active')
    current_zone = max([u.zone for u in active_users]) if active_users else 0
    zones = {0: 'البوابة', 1: 'المنطقة الأولى', 2: 'المنطقة الثانية', 3: 'المنطقة الثالثة', 4: 'المنطقة الرابعة', 5: 'القمة'}
    
    # جلب أحدث العناصر للواجهة الحيوية
    latest_news = News.objects(category='news').order_by('-created_at').first()
    latest_dec = News.objects(category='declaration').order_by('-created_at').first()
    latest_item = StoreItem.objects().order_by('-id').first()
    
    return render_template('index.html', current_zone=zones.get(current_zone, 'البوابة'), news=latest_news, dec=latest_dec, item=latest_item)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0]
        if User.objects(ip_address=ip).count() >= 2:
            flash('تم الوصول للحد الأقصى من الحسابات على هذه الشبكة!', 'error')
            return redirect(url_for('register'))
            
        if User.objects(username=request.form['username']).first():
            flash('الاسم مستخدم.', 'error'); return redirect(url_for('register'))
            
        is_first = User.objects.count() == 0
        last_u = User.objects.order_by('-hunter_id').first()
        new_id = (last_u.hunter_id + 1) if last_u else 1000
        new_user = User(hunter_id=new_id, username=request.form['username'], facebook_link=request.form['facebook_link'], password_hash=generate_password_hash(request.form['password']), role='admin' if is_first else 'hunter', status='active' if is_first else 'pending', ip_address=ip)
        new_user.save()
        flash('تم التسجيل!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = str(user.id)
            return redirect(url_for('home'))
        flash('بيانات خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.pop('user_id', None); return redirect(url_for('home'))

# --- الرخصة والأصدقاء ---
@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).first()
    if not user: session.pop('user_id', None); return redirect(url_for('login'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    banner = settings.banner_url if settings else ''
    zones_classes = {0: 'floor-0', 1: 'floor-1', 2: 'floor-2', 3: 'floor-3', 4: 'floor-4', 5: 'floor-5'}
    friend_requests = User.objects(hunter_id__in=user.friend_requests)
    friends = User.objects(hunter_id__in=user.friends)
    return render_template('profile.html', user=user, zone_class=zones_classes.get(user.zone, 'floor-0'), banner_url=banner, friend_requests=friend_requests, friends=friends)

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user = User.objects(id=session['user_id']).first()
    target_id = int(request.form.get('target_id'))
    
    # التحقق من فخ الحساب الوهمي
    trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(target_id)).first()
    if trap and trap.current_winners < trap.max_winners and str(user.id) not in trap.winners_list:
        user.points += trap.reward_points; trap.current_winners += 1; trap.winners_list.append(str(user.id))
        user.save(); trap.save()
        flash('لقد وقعت في الفخ! ولكنك كسبت نقاط اللغز لذكائك!', 'success')
        return redirect(url_for('profile'))
        
    target = User.objects(hunter_id=target_id).first()
    if target and target.status != 'frozen' and target.hunter_id not in user.friends and user.hunter_id not in target.friend_requests:
        target.friend_requests.append(user.hunter_id)
        target.save()
        flash('تم إرسال طلب الصداقة.', 'success')
    return redirect(url_for('profile'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = User.objects(id=session['user_id']).first()
    if friend_id in user.friend_requests:
        user.friend_requests.remove(friend_id)
        user.friends.append(friend_id)
        friend = User.objects(hunter_id=friend_id).first()
        if friend: friend.friends.append(user.hunter_id); friend.save()
        user.save()
    return redirect(url_for('profile'))

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    action = request.form.get('action')
    if action == 'change_avatar':
        file = request.files.get('avatar_file')
        if file and file.filename != '':
            user.avatar = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
    elif action == 'change_name':
        new_name = request.form.get('new_name')
        if not User.objects(username=new_name).first():
            now = datetime.utcnow()
            if not user.last_name_change or (now - user.last_name_change).days >= 15:
                user.username = new_name; user.last_name_change = now
    user.save(); return redirect(url_for('profile'))

# --- القوائم المنفصلة ---
@app.route('/news', methods=['GET', 'POST'])
@login_required
def news():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        guess = request.form.get('guess'); news_id = request.form.get('news_id')
        puzzle = News.objects(id=news_id).first()
        if puzzle and guess == puzzle.puzzle_answer and str(user.id) not in puzzle.winners_list and puzzle.current_winners < puzzle.max_winners:
            user.points += puzzle.reward_points; puzzle.current_winners += 1; puzzle.winners_list.append(str(user.id))
            user.save(); puzzle.save(); flash('إجابة صحيحة!', 'success')
        return redirect(url_for('news'))
    return render_template('news.html', news_list=News.objects(category='news').order_by('-created_at'), user=user)

@app.route('/declarations')
@login_required
def declarations(): return render_template('declarations.html', decs=News.objects(category='declaration').order_by('-created_at'))

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
    return redirect(url_for('news'))

@app.route('/store')
@login_required
def store(): return render_template('store.html', items=StoreItem.objects())

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='frozen'))

# --- الإدارة والمهام الجماعية ---
@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    if request.method == 'POST':
        action = request.form.get('action')
        # المهام الجماعية (Bulk Actions)
        if action == 'bulk_action':
            selected = request.form.getlist('selected_users')
            bulk_type = request.form.get('bulk_type')
            for uid in selected:
                u = User.objects(id=uid).first()
                if u:
                    if bulk_type == 'activate': u.status = 'active'
                    elif bulk_type == 'freeze': u.status = 'frozen'
                    elif bulk_type == 'add_points': u.points += int(request.form.get('bulk_points', 0))
                    u.save()
            flash('تم تنفيذ الأمر الجماعي!', 'success')
            
        elif action == 'add_news':
            News(title=request.form.get('title'), content=request.form.get('content'), category=request.form.get('category'), author=request.form.get('author', 'الإدارة'), puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points', 0)), max_winners=int(request.form.get('max_winners', 1))).save()
        
        elif action == 'add_store_item':
            item = StoreItem(name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price')))
            file = request.files.get('item_image')
            if file and file.filename != '': item.image = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
            item.save()
            
        return redirect(url_for('admin_panel'))
    return render_template('admin.html', users=User.objects())

if __name__ == '__main__': app.run(debug=True)

