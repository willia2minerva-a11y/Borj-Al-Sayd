from flask_mongoengine import MongoEngine
from datetime import datetime

db = MongoEngine()

class User(db.Document):
    meta = {'strict': False} # هذا السطر يتجاهل الحقول القديمة المحذوفة
    
    hunter_id = db.IntField(unique=True, required=True)
    username = db.StringField(max_length=50, unique=True, required=True)
    password_hash = db.StringField(required=True)
    role = db.StringField(default='hunter') # admin, ghost, hunter
    status = db.StringField(default='inactive') # active, inactive, eliminated, frozen, dead_body
    freeze_reason = db.StringField(default='')
    health = db.IntField(default=100)
    points = db.IntField(default=0)
    intelligence_points = db.IntField(default=0)
    loyalty_points = db.IntField(default=0)
    zone = db.StringField(default='البوابات')
    special_rank = db.StringField(default='مستكشف')
    achievements = db.ListField(db.StringField(), default=list)
    avatar = db.StringField(default='')
    facebook_link = db.StringField(default='')
    created_at = db.DateTimeField(default=datetime.utcnow)
    last_active = db.DateTimeField(default=datetime.utcnow)

    # Inventory & Stats
    inventory = db.ListField(db.StringField(), default=list)
    collected_seals = db.ListField(db.StringField(), default=list)
    friends = db.ListField(db.IntField(), default=list)
    friend_requests = db.ListField(db.IntField(), default=list)
    sent_requests = db.ListField(db.IntField(), default=list)

    # Cooldowns and Limits
    last_action_time = db.DateTimeField()
    last_health_check = db.DateTimeField()
    last_name_change = db.DateTimeField()
    last_password_change = db.DateTimeField()
    quicksand_lock_until = db.DateTimeField()
    tajis_eye_until = db.DateTimeField()
    has_shield = db.BooleanField(default=False)

    # Floor 1 (Among Us)
    group_id = db.IntField(default=0)
    is_cursed = db.BooleanField(default=False)
    current_room = db.StringField(default='الساحة')
    f1_tasks = db.ListField(db.DictField(), default=list)
    f1_has_voted = db.BooleanField(default=False)
    f1_votes_received = db.IntField(default=0)
    f1_last_move = db.DateTimeField()
    f1_last_kill = db.DateTimeField()
    used_vent = db.BooleanField(default=False)
    emergency_used = db.BooleanField(default=False)
    gems_collected = db.IntField(default=0)
    f1_will = db.StringField(max_length=150, default='')

    # Floor 3 (Court)
    has_voted = db.BooleanField(default=False)
    survival_votes = db.FloatField(default=0.0)
    f3_votes_cast = db.DictField(default=dict)
    f3_vote_target = db.IntField(default=0)

    # Gates
    chosen_gate = db.IntField(default=0)
    gate_status = db.StringField(default='') # waiting, passed, testing
    gate_test_answer = db.StringField(default='')

    # Lore Rooms
    unlocked_lore_room = db.BooleanField(default=False)
    unlocked_top_room = db.BooleanField(default=False)

    stats_puzzles_solved = db.IntField(default=0)
    stats_items_bought = db.IntField(default=0)
    stats_ghosts_caught = db.IntField(default=0)


class GlobalSettings(db.Document):
    meta = {'strict': False} # هذا السطر السحري يحل المشكلة
    
    setting_name = db.StringField(default='main_config', unique=True)
    home_title = db.StringField(default='برج صيد')
    banner_url = db.StringField(default='')
    global_news_active = db.BooleanField(default=False)
    global_news_text = db.StringField(default='')
    maze_winner_id = db.IntField(default=0)
    dead_count = db.IntField(default=0)
    poneglyph_text = db.StringField(default='النقوش ممسوحة...')

    # Sleep Mode (إدارة السبات وتجميد الزمن)
    sleep_mode_active = db.BooleanField(default=False)
    sleep_start_time = db.DateTimeField()
    scheduled_sleep_start = db.StringField(default='') 
    scheduled_sleep_end = db.StringField(default='')   

    # Maintenance
    maintenance_mode = db.BooleanField(default=False)
    maintenance_until = db.DateTimeField()
    maintenance_pages = db.ListField(db.StringField(), default=list)

    # War (Floor 2)
    war_mode = db.BooleanField(default=False)
    war_end_time = db.DateTimeField()
    war_kill_target = db.IntField(default=15)
    bleed_rate_minutes = db.IntField(default=60)
    bleed_amount = db.IntField(default=1)
    attack_cooldown_minutes = db.IntField(default=5)
    last_global_bleed = db.DateTimeField()
    safe_time_minutes = db.IntField(default=120)

    # Gates
    gates_mode_active = db.BooleanField(default=False)
    gates_end_time = db.DateTimeField()
    gates_description = db.StringField(default='')
    gate_1_name = db.StringField(default='بوابة 1')
    gate_2_name = db.StringField(default='بوابة 2')
    gate_3_name = db.StringField(default='بوابة 3')
    gates_test_question = db.StringField(default='ما هو سر المتاهة؟')
    gates_test_answer = db.StringField(default='سيفار')

    # Floor 1
    floor1_mode_active = db.BooleanField(default=False)
    floor1_gems_target = db.IntField(default=10)
    floor1_move_cooldown = db.IntField(default=30)
    floor1_kill_cooldown = db.IntField(default=60)
    f1_cursed_win_percent = db.IntField(default=50)
    f1_active_meetings = db.DictField(default=dict)
    floor1_darkness_until = db.DateTimeField()
    floor1_locked_room = db.StringField(default='')

    # Floor 3
    floor3_mode_active = db.BooleanField(default=False)
    floor3_paused = db.BooleanField(default=False)
    floor3_time_left = db.IntField(default=0)
    vote_end_time = db.DateTimeField()
    vote_top_n = db.IntField(default=5)
    floor3_results_active = db.BooleanField(default=False)

    # Final Battle
    final_battle_mode = db.BooleanField(default=False)
    emperor_max_hp = db.IntField(default=100000)


class News(db.Document):
    meta = {'strict': False}
    title = db.StringField(required=True)
    content = db.StringField(required=True)
    category = db.StringField(default='news') 
    author = db.StringField(default='الإمبراطور')
    image_data = db.StringField(default='')
    created_at = db.DateTimeField(default=datetime.utcnow)
    status = db.StringField(default='approved') 
    likes = db.ListField(db.StringField(), default=list)
    laughs = db.ListField(db.StringField(), default=list)

    puzzle_type = db.StringField(default='none') 
    puzzle_answer = db.StringField(default='')
    reward_points = db.IntField(default=0)
    max_winners = db.IntField(default=1)
    current_winners = db.IntField(default=0)
    winners_list = db.ListField(db.StringField(), default=list)
    
    trap_penalty_points = db.IntField(default=0)
    reward_item = db.StringField(default='')
    trap_duration_minutes = db.IntField(default=0)


class StoreItem(db.Document):
    meta = {'strict': False}
    name = db.StringField(required=True, unique=True)
    description = db.StringField(default='')
    price = db.IntField(required=True)
    item_type = db.StringField(default='weapon') 
    effect_amount = db.IntField(default=0)
    
    is_mirage = db.BooleanField(default=False)
    mirage_message = db.StringField(default='')
    is_luck = db.BooleanField(default=False)
    luck_min = db.IntField(default=0)
    luck_max = db.IntField(default=0)


class SpellConfig(db.Document):
    meta = {'strict': False}
    spell_word = db.StringField(required=True, unique=True)
    spell_type = db.StringField(required=True) 
    effect_value = db.IntField(default=0)
    is_percentage = db.BooleanField(default=False)
    item_name = db.StringField(default='')
    max_uses = db.IntField(default=1)
    used_by = db.ListField(db.StringField(), default=list)
    created_at = db.DateTimeField(default=datetime.utcnow)
    expires_at = db.DateTimeField()


class Notification(db.Document):
    meta = {'strict': False}
    target_hunter_id = db.IntField(required=True)
    message = db.StringField(required=True)
    notif_type = db.StringField(default='info') 
    created_at = db.DateTimeField(default=datetime.utcnow)
    is_read = db.BooleanField(default=False)


class GroupMessage(db.Document):
    meta = {'strict': False}
    group_id = db.IntField(required=True)
    sender_name = db.StringField(required=True)
    message = db.StringField(required=True)
    is_system_msg = db.BooleanField(default=False)
    created_at = db.DateTimeField(default=datetime.utcnow)
