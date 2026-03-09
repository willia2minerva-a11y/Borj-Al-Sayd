from flask_mongoengine import MongoEngine
from datetime import datetime

db = MongoEngine()

class User(db.Document):
    hunter_id = db.IntField(unique=True)
    username = db.StringField(unique=True, required=True)
    facebook_link = db.StringField()
    password_hash = db.StringField(required=True)
    avatar = db.StringField(default='👤')
    points = db.IntField(default=0)
    zone = db.IntField(default=0)
    special_rank = db.StringField(default='صائد مبتدئ')
    status = db.StringField(default='pending') 
    freeze_reason = db.StringField(default='') 
    role = db.StringField(default='hunter')
    inventory = db.ListField(db.StringField())
    last_name_change = db.DateTimeField(default=None)
    ip_address = db.StringField()
    friends = db.ListField(db.IntField())
    friend_requests = db.ListField(db.IntField())
    last_guess_time = db.DateTimeField(default=None) # توقيت آخر إجابة على لغز
    created_at = db.DateTimeField(default=datetime.utcnow)

class News(db.Document):
    title = db.StringField(required=True)
    content = db.StringField(required=True)
    category = db.StringField(default='news') 
    author = db.StringField(default='الإدارة')
    puzzle_type = db.StringField(default='none') 
    puzzle_answer = db.StringField()
    reward_points = db.IntField(default=0)
    max_winners = db.IntField(default=1)
    current_winners = db.IntField(default=0)
    winners_list = db.ListField(db.StringField())
    created_at = db.DateTimeField(default=datetime.utcnow)

class StoreItem(db.Document):
    name = db.StringField(required=True)
    description = db.StringField(required=True)
    price = db.IntField(required=True)
    image = db.StringField(default='')

class GlobalSettings(db.Document):
    setting_name = db.StringField(unique=True, default='main_config')
    banner_url = db.StringField(default='https://via.placeholder.com/800x200/111/FFD700?text=Borj+Al-Sayd')
