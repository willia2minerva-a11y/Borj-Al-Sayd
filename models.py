from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    facebook_link = db.Column(db.String(255), nullable=True) # للتأكد من هويته
    password_hash = db.Column(db.String(255), nullable=False)
    
    points = db.Column(db.Integer, default=0) # الرصيد
    floor = db.Column(db.Integer, default=0) # 0: البوابة, 1: الأول, 2: الثاني...
    status = db.Column(db.String(20), default='pending') # pending, active, frozen (المقبرة)
    role = db.Column(db.String(20), default='hunter') # hunter, admin
    
    last_name_change = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # العلاقة مع المشتريات (الحقيبة السرية)
    inventory = db.relationship('Inventory', backref='owner', lazy=True)

class StoreItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Integer, nullable=False)
    stock = db.Column(db.Integer, default=-1) # -1 تعني كمية لا نهائية
    icon = db.Column(db.String(50), default='default_item.png')

class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('store_item.id'), nullable=False)
    purchased_at = db.Column(db.DateTime, default=datetime.utcnow)

