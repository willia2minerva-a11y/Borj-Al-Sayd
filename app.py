from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem
from functools import wraps
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///borj_database.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'super-secret-hunter-key-change-later'

db.init_app(app)
with app.app_context():
    db.create_all()

# --- حماية الصفحات (Decorators) ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('يجب تسجيل الدخول أولاً.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if user.role != 'admin':
            flash('هذه المنطقة محرمة على الصيادين العاديين!', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- المسارات الأساسية ---
@app.route('/')
def home():
    current_floor = "البوابة" 
    return render_template('index.html', current_floor=current_floor)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        facebook_link = request.form['facebook_link']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('الاسم مستخدم بالفعل.', 'error')
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(password)
        # إذا كان هو أول حساب يسجل في الموقع، اجعله الآدمن وتلقائياً مفعل
        is_first = User.query.count() == 0
        role = 'admin' if is_first else 'hunter'
        status = 'active' if is_first else 'pending'
        
        new_user = User(username=username, facebook_link=facebook_link, password_hash=hashed_pw, role=role, status=status)
        db.session.add(new_user)
        db.session.commit()
        flash('تم التسجيل! بانتظار تفعيل الإدارة.' if not is_first else 'تم إنشاء حساب الإدارة بنجاح!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = user.id
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
    user = User.query.get(session['user_id'])
    floors = {0: ('البوابة', 'floor-0'), 1: ('الطابق الأول', 'floor-1'), 2: ('الطابق الثاني', 'floor-2'), 
              3: ('الطابق الثالث', 'floor-3'), 4: ('الطابق الرابع', 'floor-4'), 5: ('القمة', 'floor-5')}
    floor_name, floor_class = floors.get(user.floor, ('البوابة', 'floor-0'))
    return render_template('profile.html', user=user, floor_name=floor_name, floor_class=floor_class)

# --- لوحة الإدارة (Admin Dashboard) ---
@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    users = User.query.all()
    if request.method == 'POST':
        # تغيير حالة اللاعب (تفعيل / تجميد)
        user_id = request.form.get('user_id')
        action = request.form.get('action')
        user = User.query.get(user_id)
        if action == 'activate':
            user.status = 'active'
        elif action == 'freeze':
            user.status = 'frozen'
        elif action == 'add_points':
            user.points += int(request.form.get('points_amount', 0))
        db.session.commit()
        flash('تم تنفيذ الأمر بنجاح.', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin.html', users=users)

if __name__ == '__main__':
    app.run(debug=True)
