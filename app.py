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
        user = User.query.get(session['user_id'])
        if user.role != 'admin':
            flash('منطقة محرمة!', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

# --- المسارات العامة ---
@app.route('/')
def home():
    # حساب الطابق الحالي بناءً على أعلى طابق وصل له اللاعبون النشطون (أو يمكنك جعله يدوياً من الإدارة)
    active_users = User.query.filter_by(status='active').all()
    current_floor_num = max([u.floor for u in active_users]) if active_users else 0
    floors = {0: 'البوابة', 1: 'الطابق الأول', 2: 'الطابق الثاني', 3: 'الطابق الثالث', 4: 'الطابق الرابع', 5: 'القمة'}
    return render_template('index.html', current_floor=floors.get(current_floor_num, 'البوابة'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form['username']).first():
            flash('الاسم مستخدم بالفعل.', 'error')
            return redirect(url_for('register'))
        is_first = User.query.count() == 0
        new_user = User(
            username=request.form['username'],
            facebook_link=request.form['facebook_link'],
            password_hash=generate_password_hash(request.form['password']),
            role='admin' if is_first else 'hunter',
            status='active' if is_first else 'pending'
        )
        db.session.add(new_user)
        db.session.commit()
        flash('تم إنشاء حساب الإدارة بنجاح!' if is_first else 'تم التسجيل! بانتظار التفعيل.', 'success')
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

# --- مسارات اللاعب ---
@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    floors = {0: ('البوابة', 'floor-0'), 1: ('الطابق الأول', 'floor-1'), 2: ('الطابق الثاني', 'floor-2'), 
              3: ('الطابق الثالث', 'floor-3'), 4: ('الألماسي', 'floor-4'), 5: ('القمة', 'floor-5')}
    floor_name, floor_class = floors.get(user.floor, ('البوابة', 'floor-0'))
    return render_template('profile.html', user=user, floor_name=floor_name, floor_class=floor_class)

@app.route('/news', methods=['GET', 'POST'])
@login_required
def news():
    news_list = News.query.order_by(News.created_at.desc()).all()
    user = User.query.get(session['user_id'])
    
    # حل لغز الكلمة السرية
    if request.method == 'POST':
        guess = request.form.get('guess')
        news_id = request.form.get('news_id')
        news_item = News.query.get(news_id)
        if news_item and guess == news_item.puzzle_answer:
            user.points += news_item.reward_points
            db.session.commit()
            flash(f'إجابة صحيحة! كسبت {news_item.reward_points} نقطة.', 'success')
        else:
            flash('إجابة خاطئة، حاول مجدداً.', 'error')
        return redirect(url_for('news'))
        
    return render_template('news.html', news_list=news_list)

@app.route('/graveyard')
def graveyard():
    frozen_users = User.query.filter_by(status='frozen').all()
    return render_template('graveyard.html', users=frozen_users)

@app.route('/store')
@login_required
def store():
    items = StoreItem.query.all()
    return render_template('store.html', items=items)

# --- مسار الإدارة ---
@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    users = User.query.all()
    if request.method == 'POST':
        action = request.form.get('action')
        # إدارة اللاعبين
        if action in ['activate', 'freeze', 'add_points', 'change_floor']:
            user = User.query.get(request.form.get('user_id'))
            if action == 'activate': user.status = 'active'
            elif action == 'freeze': user.status = 'frozen'
            elif action == 'add_points': user.points += int(request.form.get('points_amount', 0))
            elif action == 'change_floor': user.floor = int(request.form.get('floor_num', 0))
        # إضافة خبر/لغز
        elif action == 'add_news':
            new_news = News(
                title=request.form.get('title'),
                content=request.form.get('content'),
                puzzle_type=request.form.get('puzzle_type'),
                puzzle_answer=request.form.get('puzzle_answer'),
                reward_points=int(request.form.get('reward_points', 0))
            )
            db.session.add(new_news)
        db.session.commit()
        flash('تم التحديث بنجاح.', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin.html', users=users)

if __name__ == '__main__':
    app.run(debug=True)

