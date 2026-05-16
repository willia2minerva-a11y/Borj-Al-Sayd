from flask_mongoengine import MongoEngine
from datetime import datetime

db = MongoEngine()

class User(db.Document):
    meta = {'strict': False, 'indexes': ['hunter_id', 'username', 'status', 'group_id', 'current_room']}
    hunter_id = db.IntField(unique=True)
    username = db.StringField(unique=True, required=True)
    password_hash = db.StringField(required=True)
    role = db.StringField(default='hunter')
    status = db.StringField(default='active')
    health = db.IntField(default=100)
    points = db.IntField(default=0)
    loyalty_points = db.IntField(default=0)
    intelligence_points = db.IntField(default=0)
    zone = db.StringField(default='البوابات')
    special_rank = db.StringField(default='')
    avatar = db.StringField(default='')
    inventory = db.ListField(db.StringField(), default=list)
    friends = db.ListField(db.IntField(), default=list)
    friend_requests = db.ListField(db.IntField(), default=list)
    sent_requests = db.ListField(db.IntField(), default=list)
    achievements = db.ListField(db.StringField(), default=list)
    created_at = db.DateTimeField(default=datetime.utcnow)
    last_active = db.DateTimeField(default=datetime.utcnow)
    last_action_time = db.DateTimeField()
    last_health_check = db.DateTimeField()
    freeze_reason = db.StringField(default='')
    
    chosen_gate = db.IntField(default=0)
    gate_status = db.StringField(default='')
    
    survival_votes = db.FloatField(default=0.0) 
    has_voted = db.BooleanField(default=False)
    f3_votes_cast = db.DictField(default=dict) 
    
    quicksand_lock_until = db.DateTimeField()
    tajis_eye_until = db.DateTimeField()
    unlocked_lore_room = db.BooleanField(default=False)
    unlocked_top_room = db.BooleanField(default=False)
    
    stats_ghosts_caught = db.IntField(default=0)
    stats_puzzles_solved = db.IntField(default=0)
    stats_items_bought = db.IntField(default=0)
    collected_seals = db.ListField(db.StringField(), default=list)
    gate_test_answer = db.StringField(default='')
    
    last_name_change = db.DateTimeField()
    last_password_change = db.DateTimeField()
    last_seen_news = db.DateTimeField()
    last_seen_decs = db.DateTimeField()
    last_seen_store = db.DateTimeField()
    last_seen_puzzles = db.DateTimeField()
    
    facebook_link = db.StringField(default='')
    has_shield = db.BooleanField(default=False)
    totem_self = db.BooleanField(default=False)
    
    current_room = db.StringField(default='الساحة')
    is_cursed = db.BooleanField(default=False)
    group_id = db.IntField(default=0)
    gems_collected = db.IntField(default=0)
    last_move_time = db.DateTimeField()
    last_kill_time = db.DateTimeField()
    emergency_used = db.BooleanField(default=False)
    used_vent = db.BooleanField(default=False)
    f1_has_voted = db.BooleanField(default=False)
    f1_votes_received = db.IntField(default=0)
    f1_tasks = db.ListField(db.DictField(), default=list)
    
    # === الحقول الجديدة التي كانت تسبب الخطأ ===
    f1_last_move = db.DateTimeField()
    f1_will = db.StringField(default="")

class News(db.Document):
    meta = {'strict': False}
    title = db.StringField(required=True)
    content = db.StringField(required=True)
    category = db.StringField(default='news')
    puzzle_type = db.StringField(default='none')
    puzzle_answer = db.StringField(default='')
    reward_points = db.IntField(default=0)
    max_winners = db.IntField(default=1)
    current_winners = db.IntField(default=0)
    winners_list = db.ListField(db.StringField(), default=list)
    trap_duration_minutes = db.IntField(default=0)
    trap_penalty_points = db.IntField(default=0)
    reward_item = db.StringField(default='')
    author = db.StringField(default='الإمبراطور')
    status = db.StringField(default='approved')
    image_data = db.StringField(default='')
    likes = db.ListField(db.StringField(), default=list)
    laughs = db.ListField(db.StringField(), default=list)
    created_at = db.DateTimeField(default=datetime.utcnow)

class StoreItem(db.Document):
    meta = {'strict': False}
    name = db.StringField(required=True, unique=True)
    price = db.IntField(default=0)
    item_type = db.StringField(default='box')
    effect_amount = db.IntField(default=0)
    is_mirage = db.BooleanField(default=False)
    mirage_message = db.StringField(default='')
    is_luck = db.BooleanField(default=False)
    luck_min = db.IntField(default=0)
    luck_max = db.IntField(default=0)
    created_at = db.DateTimeField(default=datetime.utcnow)

class GlobalSettings(db.Document):
    meta = {'strict': False}
    setting_name = db.StringField(unique=True, default='main_config')
    home_title = db.StringField(default='برج صيد')
    banner_url = db.StringField(default='')
    global_news_active = db.BooleanField(default=False)
    global_news_text = db.StringField(default='')
    maintenance_mode = db.BooleanField(default=False)
    maintenance_until = db.DateTimeField()
    maintenance_pages = db.ListField(db.StringField(), default=list)
    
    war_mode = db.BooleanField(default=False)
    war_end_time = db.DateTimeField()
    war_kill_target = db.IntField(default=15)
    bleed_rate_minutes = db.IntField(default=60)
    bleed_amount = db.IntField(default=1)
    attack_cooldown_minutes = db.IntField(default=5)
    safe_time_minutes = db.IntField(default=120)
    last_global_bleed = db.DateTimeField() 
    
    final_battle_mode = db.BooleanField(default=False)
    emperor_max_hp = db.IntField(default=100000)
    
    gates_mode_active = db.BooleanField(default=False)
    gates_end_time = db.DateTimeField()
    gates_description = db.StringField(default='')
    gate_1_name = db.StringField(default='بوابة 1')
    gate_2_name = db.StringField(default='بوابة 2')
    gate_3_name = db.StringField(default='بوابة 3')
    gate_1_fate = db.StringField(default='success') 
    gate_2_fate = db.StringField(default='success')
    gate_3_fate = db.StringField(default='success')
    gates_test_message = db.StringField(default='الاختبار')
    
    floor3_mode_active = db.BooleanField(default=False)
    floor3_paused = db.BooleanField(default=False) 
    floor3_time_left = db.IntField(default=0) 
    floor3_results_active = db.BooleanField(default=False) 
    vote_end_time = db.DateTimeField()
    vote_top_n = db.IntField(default=5)
    poneglyph_text = db.StringField(default='')
    dead_count = db.IntField(default=0)
    
    floor1_mode_active = db.BooleanField(default=False)
    f1_active_meetings = db.DictField(default=dict) 
    floor1_move_cooldown = db.IntField(default=30)
    floor1_kill_cooldown = db.IntField(default=60)
    floor1_gems_target = db.IntField(default=10)
    floor1_darkness_until = db.DateTimeField()
    floor1_locked_room = db.StringField(default='')
    floor1_locked_until = db.DateTimeField()
    f1_cursed_win_percent = db.IntField(default=50)
    
    maze_winner_id = db.IntField(default=0)

class SpellConfig(db.Document):
    meta = {'strict': False, 'indexes': ['spell_word', 'expires_at']}
    spell_word = db.StringField(required=True, unique=True)
    spell_type = db.StringField(required=True)
    effect_value = db.IntField(default=0)
    is_percentage = db.BooleanField(default=False)
    item_name = db.StringField(default='')
    max_uses = db.IntField(default=1)
    used_by = db.ListField(db.StringField(), default=list)
    expires_at = db.DateTimeField()
    created_at = db.DateTimeField(default=datetime.utcnow)

class Notification(db.Document):
    meta = {'strict': False, 'indexes': ['target_hunter_id', 'is_read']}
    target_hunter_id = db.IntField(default=0)
    message = db.StringField(required=True)
    notif_type = db.StringField(default='info')
    is_read = db.BooleanField(default=False)
    created_at = db.DateTimeField(default=datetime.utcnow)

class GroupMessage(db.Document):
    meta = {'strict': False, 'indexes': ['group_id', 'created_at']}
    group_id = db.IntField(required=True)
    sender_id = db.IntField()
    sender_name = db.StringField(required=True)
    message = db.StringField(required=True)
    is_system_msg = db.BooleanField(default=False)
    created_at = db.DateTimeField(default=datetime.utcnow)

def init_db():
    from werkzeug.security import generate_password_hash
    if not User.objects(hunter_id=1000).first():
        User(
            hunter_id=1000, username='الإمبراطور', password_hash=generate_password_hash('admin123'),
            role='admin', status='active', zone='العرش', special_rank='حاكم المتاهة', health=100000
        ).save()
    if not GlobalSettings.objects(setting_name='main_config').first():
        GlobalSettings(setting_name='main_config').save()

def migrate_database():
    updated_count = 0
    for user in User.objects():
        updates = {}
        if not hasattr(user, 'used_vent'): updates['used_vent'] = False
        if not hasattr(user, 'emergency_used'): updates['emergency_used'] = False
        if not hasattr(user, 'f1_has_voted'): updates['f1_has_voted'] = False
        if not hasattr(user, 'f1_votes_received'): updates['f1_votes_received'] = 0
        if not hasattr(user, 'gems_collected'): updates['gems_collected'] = 0
        if not hasattr(user, 'is_cursed'): updates['is_cursed'] = False
        if not hasattr(user, 'group_id'): updates['group_id'] = 0
        if not hasattr(user, 'current_room'): updates['current_room'] = 'الساحة'
        if not hasattr(user, 'f1_tasks'): updates['f1_tasks'] = []
        if not hasattr(user, 'f1_will'): updates['f1_will'] = ""
        if updates:
            user.update(**updates)
            updated_count += 1

try:
    init_db()
    migrate_database()
except Exception as e:
    pass
