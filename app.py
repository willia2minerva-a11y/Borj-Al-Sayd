from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, StoreItem
import os

app = Flask(__name__)

# إعدادات قاعدة البيانات والأمان
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///borj_database.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'super-secret-hunter-key-change-later' # مفتاح تشفير الجلسات

db.init_app(app)

with app.app_context():
    db.create_all()

# --- المسار الرئيسي ---
@app.route('/')
def home():
    current_floor = "البوابة" 
    return render_template('index.html', current_floor=current_floor)

# --- نظام التسجيل ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        facebook_link = request.form['facebook_link']
        password = request.form['password']

        # التأكد من أن الاسم غير مكرر
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('هذا الاسم مستخدم بالفعل، اختر اسماً آخر.', 'error')
            return redirect(url_for('register'))

        # تشفير كلمة المرور وحفظ اللاعب الجديد (حالته ستكون pending تلقائياً كما حددنا في models)
        hashed_pw = generate_password_hash(password)
        new_user = User(username=username, facebook_link=facebook_link, password_hash=hashed_pw)
        
        db.session.add(new_user)
        db.session.commit()

        flash('تم التسجيل بنجاح! حسابك الآن قيد المراجعة. راسل الإدارة لتفعيله.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# --- نظام تسجيل الدخول ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        
        # التحقق من الاسم وتطابق كلمة المرور المشفرة
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id # فتح جلسة للاعب
            flash(f'أهلاً بك مجدداً يا {user.username}!', 'success')
            return redirect(url_for('home'))
        else:
            flash('الاسم أو كلمة المرور غير صحيحة.', 'error')

    return render_template('login.html')

# --- تسجيل الخروج ---
@app.route('/logout')
def logout():
    session.pop('user_id', None) # إغلاق الجلسة
    flash('تم تسجيل الخروج. نراك قريباً!', 'info')
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)
