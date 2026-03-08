from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings
from functools import wraps
from datetime import datetime
import os
import base64

app = Flask(__name__)

# الاتصال بقاعدة البيانات السحابية
app.config['MONGODB_SETTINGS'] = {
    'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db')
}
app.config['SECRET_KEY'] = 'super-secret-hunter-key-change-later'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 # أقصى حجم للصورة 5 ميجا

db.init_app(app)

# --- الحماية ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('يجب تسجيل الدخول أولاً.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        user = User.objects(id=session['user_id']).first()
        if not user or user.role != 'admin':
            flash('منطقة محرمة!', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

# --- مسارات التسجيل والأساسيات ---
@app.route('/')
def home():
    active_users = User.objects(status='active')
    current_zone_num = max([u.zone for u in active_users]) if active_users else 0
    zones = {0: 'المنطقة الأساسية', 1: 'المنطقة الأولى', 2: 'المنطقة الثانية', 3: 'المنطقة الثالثة', 4: 'المنطقة الرابعة', 5: 'القمة'}
    return render_template('index.html', current_zone=zones.get(current_zone_num, 'المنطقة الأساسية'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.objects(username=request.form['username']).first():
            flash('الاسم مستخدم بالفعل.', 'error')
            return redirect(url_for('register'))
        is_first = User.objects.count() == 0
        last_user = User.objects.order_by('-hunter_id').first()
        new_id = (last_user.hunter_id + 1) if last_user and last_user.hunter_id else 1000
        new_user = User(hunter_id=new_id, username=request.form['username'], facebook_link=request.form['facebook_link'], password_hash=generate_password_hash(request.form['password']), role='admin' if is_first else 'hunter', status='active' if is_first else 'pending')
        new_user.save()
        flash('تم التسجيل! بانتظار التفعيل.' if not is_first else 'تم إنشاء حساب الإدارة!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = str(user.id)
            flash(f'أهلاً بك يا {user.username}', 'success')
            return redirect(url_for('home'))
        flash('بيانات خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).first()
    if not user: session.pop('user_id', None); return redirect(url_for('login'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    banner_url = settings.banner_url if settings else 'https://via.placeholder.com/800x200/111/FFD700?text=Borj+Al-Sayd'
    zones_classes = {0: 'floor-0', 1: 'floor-1', 2: 'floor-2', 3: 'floor-3', 4: 'floor-4', 5: 'floor-5'}
    return render_template('profile.html', user=user, zone_class=zones_classes.get(user.zone, 'floor-0'), banner_url=banner_url)

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    action = request.form.get('action')
    if action == 'change_avatar':
        file = request.files.get('avatar_file')
        if file and file.filename != '':
            encoded = base64.b64encode(file.read()).decode('utf-8')
            user.avatar = f"data:{file.content_type};base64,{encoded}"
            flash('تم تحديث الصورة!', 'success')
    elif action == 'change_name':
        new_name = request.form.get('new_name')
        if User.objects(username=new_name).first(): flash('الاسم محجوز!', 'error')
        else:
            now = datetime.utcnow()
            if user.last_name_change is None or (now - user.last_name_change).days >= 15:
                user.username = new_name; user.last_name_change = now; flash('تم تغيير الاسم!', 'success')
            else:
                flash(f'انتظر {15 - (now - user.last_name_change).days} يوم.', 'error')
    user.save()
    return redirect(url_for('profile'))

# --- التصريحات والمخطوطات والألغاز ---
@app.route('/declarations')
@login_required
def declarations():
    decs = News.objects(category='declaration').order_by('-created_at')
    return render_template('declarations.html', news_list=decs)

@app.route('/manuscripts', methods=['GET', 'POST'])
@login_required
def manuscripts():
    user = User.objects(id=session['user_id']).first()
    mans = News.objects(category='manuscript').order_by('-created_at')
    
    # حل لغز الكلمة السرية
    if request.method == 'POST':
        guess = request.form.get('guess')
        news_id = request.form.get('news_id')
        puzzle = News.objects(id=news_id).first()
        
        if puzzle and guess == puzzle.puzzle_answer:
            if str(user.id) in puzzle.winners_list:
                flash('لقد قمت بحل هذا اللغز مسبقاً!', 'error')
            elif puzzle.current_winners >= puzzle.max_winners:
                flash('للأسف، اكتمل عدد الفائزين المسموح به لهذا اللغز!', 'error')
            else:
                user.points += puzzle.reward_points
                puzzle.current_winners += 1
                puzzle.winners_list.append(str(user.id))
                user.save(); puzzle.save()
                flash(f'إجابة أسطورية! كسبت {puzzle.reward_points} نقطة.', 'success')
        else:
            flash('إجابة خاطئة.', 'error')
        return redirect(url_for('manuscripts'))
    return render_template('manuscripts.html', news_list=mans, user=user)

# رابط اللغز السري
@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link_claim(puzzle_id):
    user = User.objects(id=session['user_id']).first()
    try:
        puzzle = News.objects(id=puzzle_id, puzzle_type='secret_link').first()
        if not puzzle: return redirect(url_for('home'))
        
        if str(user.id) in puzzle.winners_list:
            flash('لقد اكتشفت هذا الرابط مسبقاً وأخذت الجائزة!', 'error')
        elif puzzle.current_winners >= puzzle.max_winners:
            flash('لقد سبقك صيادون آخرون واكتشفوا الرابط قبلك، نفدت الجوائز!', 'error')
        else:
            user.points += puzzle.reward_points
            puzzle.current_winners += 1
            puzzle.winners_list.append(str(user.id))
            user.save(); puzzle.save()
            flash(f'🎉 اكتشاف عظيم! لقد وجدت الرابط السري وكسبت {puzzle.reward_points} نقطة!', 'success')
    except:
        pass
    return redirect(url_for('manuscripts'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='frozen'))

@app.route('/store')
@login_required
def store(): return render_template('store.html', items=StoreItem.objects())

# --- غرفة الإدارة ---
@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    users = User.objects()
    if request.method == 'POST':
        action = request.form.get('action')
        if action in ['activate', 'freeze', 'add_points', 'change_zone', 'change_rank']:
            user = User.objects(id=request.form.get('user_id')).first()
            if user:
                if action == 'activate': user.status = 'active'
                elif action == 'freeze': user.status = 'frozen'
                elif action == 'add_points': user.points = int(request.form.get('points_amount', 0))
                elif action == 'change_zone': user.zone = int(request.form.get('zone_num', 0))
                elif action == 'change_rank': user.special_rank = request.form.get('special_rank')
                user.save()
                
        elif action == 'add_news':
            new_news = News(
                title=request.form.get('title'),
                content=request.form.get('content'),
                category=request.form.get('category'),
                puzzle_type=request.form.get('puzzle_type'),
                puzzle_answer=request.form.get('puzzle_answer'),
                reward_points=int(request.form.get('reward_points', 0)),
                max_winners=int(request.form.get('max_winners', 1))
            )
            new_news.save()
            
        elif action == 'add_store_item':
            new_item = StoreItem(name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price')))
            file = request.files.get('item_image')
            if file and file.filename != '':
                encoded = base64.b64encode(file.read()).decode('utf-8')
                new_item.image = f"data:{file.content_type};base64,{encoded}"
            new_item.save()
            
        elif action == 'update_banner':
            settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config')
            file = request.files.get('banner_file')
            if file and file.filename != '':
                encoded = base64.b64encode(file.read()).decode('utf-8')
                settings.banner_url = f"data:{file.content_type};base64,{encoded}"
                settings.save()
                
        flash('تم التنفيذ بنجاح!', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin.html', users=users)

if __name__ == '__main__': app.run(debug=True)

