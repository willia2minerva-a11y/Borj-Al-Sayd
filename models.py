from flask_mongoengine import MongoEngine
from datetime import datetime

db = MongoEngine()

# 1. إعدادات المتاهة الإمبراطورية
class GlobalSettings(db.Document):
    setting_name = db.StringField(unique=True)
    
    # هوية المتاهة (الأسماء الديناميكية)
    maze_name = db.StringField(default="متاهة سيفار")
    home_title = db.StringField(default="بوابة المتاهة")
    home_color = db.StringField(default="#ffffff")
    banner_url = db.StringField()
    global_news_active = db.BooleanField(default=False)
    global_news_text = db.StringField()
    
    # أسماء الصفحات
    nav_home = db.StringField(default="الرئيسية 🏰")
    nav_profile = db.StringField(default="هويتي 👤")
    nav_friends = db.StringField(default="التحالفات 🤝")
    nav_news = db.StringField(default="المخطوطات 📜")
    nav_puzzles = db.StringField(default="النقوش 🧩")
    nav_decs = db.StringField(default="التصريحات 📢")
    nav_store = db.StringField(default="السوق المظلم 🐪")
    nav_grave = db.StringField(default="المقبرة 💀")
    
    # الصيانة
    maintenance_mode = db.BooleanField(default=False)
    maintenance_until = db.DateTimeField()
    maintenance_pages = db.ListField(db.StringField())
    
    # مود البوابات
    gates_mode_active = db.BooleanField(default=False)
    gates_selection_locked = db.BooleanField(default=False)
    gates_description = db.StringField()
    gate_1_name = db.StringField(default="بوابة 1")
    gate_2_name = db.StringField(default="بوابة 2")
    gate_3_name = db.StringField(default="بوابة 3")
    gates_test_message = db.StringField()
    
    # مود الحرب الشاملة وضريبة الدم
    war_mode = db.BooleanField(default=False)
    war_kill_target = db.IntField(default=15) # عدد القتلى لإنهاء الحرب
    dead_count = db.IntField(default=0) # العداد الحالي للقتلى
    bleed_rate_minutes = db.IntField(default=60)
    bleed_amount = db.IntField(default=1)
    safe_time_minutes = db.IntField(default=120)
    
    # مود التصويت
    floor3_mode_active = db.BooleanField(default=False)
    
    # مود المعركة الأخيرة
    final_battle_mode = db.BooleanField(default=False)

# 2. أرواح الرحالة (اللاعبين)
class User(db.Document):
    hunter_id = db.IntField(unique=True)
    username = db.StringField(unique=True, required=True)
    password_hash = db.StringField(required=True)
    role = db.StringField(default='hunter') 
    status = db.StringField(default='inactive') # active, inactive, eliminated
    avatar = db.StringField()
    
    # الموارد
    health = db.IntField(default=100)
    points = db.IntField(default=0)
    inventory = db.ListField(db.StringField())
    
    # الإحصائيات النفسية (الجديدة)
    intelligence_points = db.IntField(default=0)
    loyalty_points = db.IntField(default=0)
    
    # الحماية والأدوات النشطة
    has_shield = db.BooleanField(default=False)
    has_totem = db.BooleanField(default=False)
    hidden_in_logs_until = db.DateTimeField() # تعويذة التخفي
    
    # الغرف السرية المفتوحة للاعب
    unlocked_lore_room = db.BooleanField(default=False)
    unlocked_top_room = db.BooleanField(default=False)
    
    # التحالفات
    friends = db.ListField(db.IntField())
    friend_requests = db.ListField(db.IntField())
    
    # التتبع الزمني
    created_at = db.DateTimeField(default=datetime.utcnow)
    last_active = db.DateTimeField()
    last_name_change = db.DateTimeField()
    last_password_change = db.DateTimeField()
    
    # الإشعارات
    last_seen_news = db.DateTimeField(default=datetime.utcnow)
    last_seen_puzzles = db.DateTimeField(default=datetime.utcnow)
    last_seen_decs = db.DateTimeField(default=datetime.utcnow)
    last_seen_store = db.DateTimeField(default=datetime.utcnow)
    
    # إحصائيات اللعب
    achievements = db.ListField(db.StringField())
    stats_puzzles_solved = db.IntField(default=0)
    stats_ghosts_caught = db.IntField(default=0)
    stats_items_bought = db.IntField(default=0)
    
    # المودات والفخاخ
    quicksand_lock_until = db.DateTimeField()
    tajis_eye_until = db.DateTimeField()
    freeze_reason = db.StringField()
    
    # البوابات
    chosen_gate = db.IntField(default=0)
    gate_status = db.StringField(default='none') 
    gate_test_answer = db.StringField()
    
    # الحرب والتصويت
    last_health_check = db.DateTimeField()
    last_action_time = db.DateTimeField()
    destroyed_seals = db.IntField(default=0)
    has_voted = db.BooleanField(default=False)
    survival_votes = db.IntField(default=0)

# 3. الأخبار والألغاز المفتوحة
class News(db.Document):
    title = db.StringField(required=True)
    content = db.StringField(required=True)
    category = db.StringField(default='news') # news, puzzle, declaration, hidden
    target_group = db.StringField(default='all') 
    created_at = db.DateTimeField(default=datetime.utcnow)
    
    author = db.StringField()
    status = db.StringField(default='approved')
    image_data = db.StringField()
    
    puzzle_type = db.StringField(default='none') 
    puzzle_answer = db.StringField()
    reward_points = db.IntField(default=0)
    winners_list = db.ListField(db.StringField())
    max_winners = db.IntField(default=1)
    current_winners = db.IntField(default=0)
    
    trap_duration_minutes = db.IntField(default=0)
    trap_penalty_points = db.IntField(default=0)

# 4. سجلات السرد القصصي (Lore Logs - غرفة بونغلاف)
class LoreLog(db.Document):
    content = db.StringField()
    created_at = db.DateTimeField(default=datetime.utcnow)
    is_epic = db.BooleanField(default=False) # لتمييز الأحداث الكبرى (كقتل الإمبراطور)

# 5. مستودع التعاويذ السحرية (الجديد)
class SpellConfig(db.Document):
    spell_word = db.StringField(unique=True, required=True)
    spell_type = db.StringField(required=True) # hp_loss, hp_gain, points_loss, item_reward, revive_friend, stealth, unlock_lore, unlock_top, kill_emperor
    effect_value = db.IntField(default=0) # القيمة (مثلاً 5)
    is_percentage = db.BooleanField(default=False) # هل هي 5% أم 5 نقاط ثابتة؟
    item_name = db.StringField() # إذا كان نوع التعويذة إعطاء أداة
    lore_message = db.StringField() # الرسالة المرعبة التي تظهر عند تفعيلها

# 6. السوق المظلم
class StoreItem(db.Document):
    name = db.StringField(unique=True, required=True)
    description = db.StringField(required=True)
    price = db.IntField(required=True)
    item_type = db.StringField(default='normal') # normal, weapon, heal, spy, steal, seal, shield, totem
    effect_amount = db.IntField(default=0)
    image = db.StringField()
    
    is_luck = db.BooleanField(default=False)
    luck_min = db.IntField(default=0)
    luck_max = db.IntField(default=0)
    
    is_mirage = db.BooleanField(default=False)
    mirage_message = db.StringField()

# 7. سجلات المعارك المباشرة
class BattleLog(db.Document):
    victim_name = db.StringField()
    weapon_name = db.StringField()
    remaining_hp = db.IntField()
    created_at = db.DateTimeField(default=datetime.utcnow)

