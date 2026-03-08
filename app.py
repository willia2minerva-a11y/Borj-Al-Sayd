from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings
from functools import wraps
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# رابط الاتصال بـ MongoDB السحابية (ستضعه لاحقاً في إعدادات Render)
app.config['MONGODB_SETTINGS'] = {
    'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db')
}
app.config['SECRET_KEY'] = 'super-secret-hunter-key-change-later'

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

# --- مسارات التسجيل والدخول ---
@app.route('/')
def home():
    active_users = User.objects(status='active')
    current_zone_num = max([u.zone for u in active_users]) if active_users else 0
    zones = {0: 'المنطقة الأساسية', 1: 'المنطقة الأولى', 2: 'المنطقة الثانية', 3: 'المنطقة الثالث', 4: 'المنطقة الرابعة', 5: 'القمة'}
    return render_template('index.html', current_zone=zones.get(current_zone_num, 'المنطقة الأساسية'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.objects(username=request.form['username']).first():
            flash('الاسم مستخدم بالفعل.', 'error')
            return redirect(url_for('register'))
        
        is_first = User.objects.count() == 0
        last_user = User.objects.order_by('-hunter_id').first()
        new_id = (last_user.hunter_id + 1) if last_user and last_user.hunter_id else 1000 # توليد ID مميز
        
        new_user = User(
            hunter_id=new_id,
            username=request.form['username'],
            facebook_link=request.form['facebook_link'],
            password_hash=generate_password_hash(request.form['password']),
            role='admin' if is_first else 'hunter',
            status='active' if is_first else 'pending'
        )
        new_user.save()
        flash('تم التسجيل! بانتظار التفعيل.' if not is_first else 'تم إنشاء حساب الإدارة بنجاح!', 'success')
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

# --- ملف الصائد والإعدادات ---
@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).first()
    settings = GlobalSettings.objects(setting_name='main_config').first()
    banner_url = settings.banner_url if settings else 'https://via.placeholder.com/800x200/111/FFD700?text=Borj+Al-Sayd'
    
    zones_classes = {0: 'floor-0', 1: 'floor-1', 2: 'floor-2', 3: 'floor-3', 4: 'floor-4', 5: 'floor-5'}
    zone_class = zones_classes.get(user.zone, 'floor-0')
    
    return render_template('profile.html', user=user, zone_class=zone_class, banner_url=banner_url)

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first()
    action = request.form.get('action')

    # تغيير كلمة المرور
    if action == 'change_password':
        user.password_hash = generate_password_hash(request.form.get('new_password'))
        flash('تم تغيير كلمة المرور بنجاح.', 'success')

    # تغيير الصورة (الأفاتار)
    elif action == 'change_avatar':
        user.avatar = request.form.get('new_avatar')
        flash('تم تحديث صورتك الشخصية.', 'success')

    # تغيير الاسم (بشرط مرور 15 يوم)
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
                flash(f'عذراً! يمكنك تغيير اسمك بعد {days_left} يوم.', 'error')
    
    user.save()
    return redirect(url_for('profile'))

# مسارات الأخبار والإدارة بقيت كما هي في الدفعة القادمة...
if __name__ == '__main__':
    app.run(debug=True)
