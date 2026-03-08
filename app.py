from flask import Flask, render_template
from models import db, User, StoreItem
import os

app = Flask(__name__)

# إعدادات قاعدة البيانات (تستخدم SQLite محلياً، و Postgres على Render)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///borj_database.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'super-secret-hunter-key-change-later'

db.init_app(app)

# إنشاء الجداول تلقائياً عند أول تشغيل
with app.app_context():
    db.create_all()

@app.route('/')
def home():
    # مؤقتاً سنرسل بيانات وهمية لتجربة التصميم
    current_floor = "البوابة" 
    return render_template('index.html', current_floor=current_floor)
@app.route('/test')
def test():
    return "محرك بايثون يعمل بنجاح والخلل في مجلد القوالب!"

if __name__ == '__main__':
    app.run(debug=True)

