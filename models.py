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
    special_rank = db.StringField(default='مستكشف مبتدئ')
    
    status = db.StringField(default='active') # active, frozen, eliminated
    freeze_reason = db.StringField(default='') 
    role = db.StringField(default='hunter') 
    inventory = db.ListField(db.StringField())
    last_name_change = db.DateTimeField(default=None)
    ip_address = db.StringField()
    friends = db.ListField(db.IntField())
    friend_requests = db.ListField(db.IntField())
    last_guess_time = db.DateTimeField(default=None) 
    
    quicksand_lock_until = db.DateTimeField(default=None)
    
    # --- نظام الحرب والمعركة الأخيرة ---
    health = db.IntField(default=100) 
    last_health_check = db.DateTimeField(default=datetime.utcnow) 
    last_action_time = db.DateTimeField(default=datetime.utcnow)
    last_active = db.DateTimeField(default=datetime.utcnow) # لنظام الموت 72 ساعة
    tajis_eye_until = db.DateTimeField(default=None) # وقت انتهاء مفعول عين تاجيس
    destroyed_seals = db.IntField(default=0) # عداد الأختام الأربعة المدمرة
    
    stats_ghosts_caught = db.IntField(default=0)
    stats_puzzles_solved = db.IntField(default=0)
    stats_items_bought = db.IntField(default=0)
    achievements = db.ListField(db.StringField()) 
    
    last_seen_news = db.DateTimeField(default=datetime.utcnow)
    last_seen_puzzles = db.DateTimeField(default=datetime.utcnow)
    last_seen_decs = db.DateTimeField(default=datetime.utcnow)
    last_seen_store = db.DateTimeField(default=datetime.utcnow)
    
    created_at = db.DateTimeField(default=datetime.utcnow)
    meta = {'indexes': ['hunter_id', 'username', 'status', 'role', 'health', 'last_active']}

class News(db.Document):
    title = db.StringField(required=True)
    content = db.StringField(required=True)
    image_data = db.StringField(default='') 
    category = db.StringField(default='news') 
    author = db.StringField(default='الإدارة')
    status = db.StringField(default='approved') 
    puzzle_type = db.StringField(default='none') 
    puzzle_answer = db.StringField()
    reward_points = db.IntField(default=0)
    trap_penalty_points = db.IntField(default=0) 
    trap_duration_minutes = db.IntField(default=0) 
    max_winners = db.IntField(default=1)
    current_winners = db.IntField(default=0)
    winners_list = db.ListField(db.StringField())
    created_at = db.DateTimeField(default=datetime.utcnow)
    meta = {'indexes': ['category', 'status', 'created_at']}

class StoreItem(db.Document):
    name = db.StringField(required=True)
    description = db.StringField(required=True)
    price = db.IntField(required=True)
    image = db.StringField(default='')
    
    # أنواع الأغراض الجديدة (سلاح، علاج، تجسس، سرقة، درع، ختم)
    item_type = db.StringField(default='normal') 
    effect_amount = db.IntField(default=0) 
    
    is_mirage = db.BooleanField(default=False) 
    mirage_message = db.StringField(default='') 
    is_luck = db.BooleanField(default=False)
    luck_min = db.IntField(default=-50)
    luck_max = db.IntField(default=100)
    created_at = db.DateTimeField(default=datetime.utcnow)

class BattleLog(db.Document):
    victim_name = db.StringField(required=True)
    weapon_name = db.StringField(required=True)
    remaining_hp = db.IntField(required=True)
    created_at = db.DateTimeField(default=datetime.utcnow)
    meta = {'indexes': ['-created_at']}

class GlobalSettings(db.Document):
    setting_name = db.StringField(unique=True, default='main_config')
    banner_url = db.StringField(default='')
    home_title = db.StringField(default='بوابة سيفار')
    home_color = db.StringField(default='var(--zone-1-wood)')
    
    maintenance_mode = db.BooleanField(default=False) 
    war_mode = db.BooleanField(default=False) 
    final_battle_mode = db.BooleanField(default=False) # مود المعركة الأخيرة (إخفاء النقاط)
    
    bleed_rate_minutes = db.IntField(default=60) 
    bleed_amount = db.IntField(default=1) 
    safe_time_minutes = db.IntField(default=120) 
    dead_count = db.IntField(default=0) 
    max_dead_to_end = db.IntField(default=15) 
    
    # أسماء الصفحات القابلة للتغيير ديناميكياً
    nav_home = db.StringField(default='🏠 بوابة سيفار (الرئيسية)')
    nav_profile = db.StringField(default='📜 مخطوطتي (الملف الشخصي)')
    nav_friends = db.StringField(default='🤝 التحالفات (الأصدقاء)')
    nav_news = db.StringField(default='📜 أخبار المتاهة (الأخبار)')
    nav_puzzles = db.StringField(default='🧩 مخطوطات سيفار (الألغاز)')
    nav_decs = db.StringField(default='📢 تدوينات الرحالة (التصريحات)')
    nav_store = db.StringField(default='🐪 قافلة التجار (السوق)')
    nav_grave = db.StringField(default='💀 المقبرة المنسية')
