from flask_mongoengine import MongoEngine
from datetime import datetime

db = MongoEngine()

class User(db.Document):
    hunter_id = db.IntField(unique=True) # الـ ID المميز للاعب (مثال: 1001)
    username = db.StringField(unique=True, required=True)
    facebook_link = db.StringField()
    password_hash = db.StringField(required=True)
    
    avatar = db.StringField(default='👤') # صورة الملف الشخصي أو إيموجي
    points = db.IntField(default=0)
    zone = db.IntField(default=0) # 0: المنطقة الأساسية، 1: المنطقة الأولى...
    
    special_rank = db.StringField(default='صائد مبتدئ') # الرتبة المميزة التي يمنحها الأدمن
    status = db.StringField(default='pending') # pending, active, frozen
    role = db.StringField(default='hunter') # hunter, admin
    
    inventory = db.ListField(db.StringField()) # حقيبة المنتجات المشتراة
    last_name_change = db.DateTimeField(default=None) # تاريخ آخر تغيير للاسم
    created_at = db.DateTimeField(default=datetime.utcnow)

class News(db.Document):
    title = db.StringField(required=True)
    content = db.StringField(required=True)
    puzzle_type = db.StringField(default='none')
    puzzle_answer = db.StringField()
    reward_points = db.IntField(default=0)
    created_at = db.DateTimeField(default=datetime.utcnow)

class StoreItem(db.Document):
    name = db.StringField(required=True)
    description = db.StringField(required=True)
    price = db.IntField(required=True)

class GlobalSettings(db.Document):
    # لحفظ الغلاف الموحد الذي يضعه الأدمن
    setting_name = db.StringField(unique=True, default='main_config')
    banner_url = db.StringField(default='https://i.imgur.com/default_banner.jpg')
