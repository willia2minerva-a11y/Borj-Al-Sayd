from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings
from functools import wraps
from datetime import datetime
import os

app = Flask(__name__)

# الاتصال بقاعدة البيانات السحابية (MongoDB)
app.config['MONGODB_SETTINGS'] = {
    'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db')
}
app.config['SECRET_KEY'] = 'super-secret-hunter-key-change-later'

db.init_app(app)

# --- الحماية (Decorators) ---
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
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.objects(id=session['user_id']).first()
        if not user or user.role != 'admin':
            flash('منطقة محرمة! هذا المكان مخصص لإدارة البرج فقط.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

# --- المسارات العامة ---
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
            flash('الاسم مستخدم بالفعل، اختر اسماً آخر.', 'error')
            return redirect(url_for('register'))
        
        is_first = User.objects.count() == 0
        last_user = User.objects.order_by('-hunter_id').first()
        new_id = (last_user.hunter_id + 1) if last_user and last_user.hunter_id else 1000
        
        new_user = User(
            hunter_id=new_id,
            username=request.form['username'],
            facebook_link=request.form['facebook_link'],
            password_hash=generate_password_hash(request.form['password']),
            role='admin' if is_first else 'hunter',
            status='active' if is_first else 'pending'
        )
        new_user.save()
        flash('تم إنشاء حساب الإدارة بنجاح!' if is_first else 'تم التسجيل بنجاح! بانتظار التفعيل من الإدارة.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = str(user.id)
            flash(f'أهلاً بك مجدداً يا {user.username}', 'success')
            return redirect(url_for('home'))
        flash('بيانات الدخول خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('home'))

# --- ملف الصائد والإعدادات ---
@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).first()
    
    # درع حماية: إذا كانت الجلسة قديمة واللاعب غير موجود في القاعدة الجديدة، اطرده لتسجيل الدخول
    if not user:
        session.pop('user_id', None)
        return redirect(url_for('login'))
        
    settings = GlobalSettings.objects(setting_name='main_config').first()
    banner_url = settings.banner_url if settings else 'https://via.placeholder.com/800x200/111/FFD700?text=Borj+Al-Sayd'
    
    zones_classes = {0: 'floor-0', 1: 'floor-1', 2: 'floor-2', 3: 'floor-3', 4: 'floor-4', 5: 'floor-5'}
    zone_class = zones_classes.get(user.zone, 'floor-0')
    
    return render_template('profile.html', user=user, zone_class=zone_class, banner_url=banner_url)

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    if not user:
        session.pop('user_id', None)
        return redirect(url_for('login'))

    action = request.form.get('action')

    if action == 'change_avatar':
        user.avatar = request.form.get('new_avatar')
        flash('تم تحديث صورتك الشخصية بنجاح.', 'success')

    elif action == 'change_name':
        new_name = request.form.get('new_name')
        if User.objects(username=new_name).first():
            flash('هذا الاسم محجوز لصائد آخر!', 'error')
        else:
            now = datetime.utcnow()
            if user.last_name_change is None or (now - user.last_name_change).days >= 15:
                user.username = new_name
                user.last_name_change = now
                flash('تم تغيير اسمك بنجاح!', 'success')
            else:
                days_left = 15 - (now - user.last_name_change).days
                flash(f'عذراً! لا يمكنك تغيير اسمك إلا بعد {days_left} يوم.', 'error')
    
    user.save()
    return redirect(url_for('profile'))

# --- المخطوطات، المقبرة، والمتجر ---
@app.route('/news', methods=['GET', 'POST'])
@login_required
def news():
    news_list = News.objects().order_by('-created_at')
    user = User.objects(id=session['user_id']).first()
    if not user: return redirect(url_for('login'))
    
    if request.method == 'POST':
        guess = request.form.get('guess')
        news_id = request.form.get('news_id')
        news_item = News.objects(id=news_id).first()
        if news_item and guess == news_item.puzzle_answer:
            user.points += news_item.reward_points
            user.save()
            flash(f'إجابة صحيحة! لقد كسبت {news_item.reward_points} نقطة.', 'success')
        else:
            flash('إجابة خاطئة، حاول مجدداً أيها الصائد.', 'error')
        return redirect(url_for('news'))
        
    return render_template('news.html', news_list=news_list)

@app.route('/graveyard')
def graveyard():
    frozen_users = User.objects(status='frozen')
    return render_template('graveyard.html', users=frozen_users)

@app.route('/store')
@login_required
def store():
    items = StoreItem.objects()
    return render_template('store.html', items=items)

# --- لوحة التحكم الإمبراطورية ---
@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    users = User.objects()
    if request.method == 'POST':
        action = request.form.get('action')
        
        # 1. إدارة اللاعبين
        if action in ['activate', 'freeze', 'add_points', 'change_zone', 'change_rank']:
            user = User.objects(id=request.form.get('user_id')).first()
            if user:
                if action == 'activate': user.status = 'active'
                elif action == 'freeze': user.status = 'frozen'
                elif action == 'add_points': user.points = int(request.form.get('points_amount', 0))
                elif action == 'change_zone': user.zone = int(request.form.get('zone_num', 0))
                elif action == 'change_rank': user.special_rank = request.form.get('special_rank')
                user.save()
            
        # 2. إضافة خبر / لغز
        elif action == 'add_news':
            new_news = News(
                title=request.form.get('title'),
                content=request.form.get('content'),
                puzzle_type=request.form.get('puzzle_type'),
                puzzle_answer=request.form.get('puzzle_answer'),
                reward_points=int(request.form.get('reward_points', 0))
            )
            new_news.save()
            
        # 3. إضافة منتج للمتجر
        elif action == 'add_store_item':
            new_item = StoreItem(
                name=request.form.get('item_name'),
                description=request.form.get('item_desc'),
                price=int(request.form.get('item_price'))
            )
            new_item.save()
            
        # 4. تغيير الغلاف الموحد
        elif action == 'update_banner':
            settings = GlobalSettings.objects(setting_name='main_config').first()
            if not settings:
                settings = GlobalSettings(setting_name='main_config')
            settings.banner_url = request.form.get('banner_url')
            settings.save()
            
        flash('تم تنفيذ الأمر الإمبراطوري بنجاح!', 'success')
        return redirect(url_for('admin_panel'))
        
    return render_template('admin.html', users=users)

if __name__ == '__main__':
    app.run(debug=True)
