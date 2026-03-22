from flask_mongoengine import MongoEngine
from datetime import datetime

db = MongoEngine()

class User(db.Document):
    meta = {
        'strict': False,
        'indexes': [
            'hunter_id',
            'username',
            'status',
            'chosen_gate',
            ('status', 'role'),
            'last_active',
            'gate_status',
            'friends',
            'friend_requests',
            'created_at'
        ]
    }
    
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
    achievements = db.ListField(db.StringField(), default=list)
    created_at = db.DateTimeField(default=datetime.utcnow)
    last_active = db.DateTimeField(default=datetime.utcnow)
    last_action_time = db.DateTimeField(default=datetime.utcnow)
    last_health_check = db.DateTimeField(default=datetime.utcnow)
    freeze_reason = db.StringField(default='')
    chosen_gate = db.IntField(default=0)
    gate_status = db.StringField(default='')
    survival_votes = db.IntField(default=0)
    has_voted = db.BooleanField(default=False)
    quicksand_lock_until = db.DateTimeField()
    tajis_eye_until = db.DateTimeField()
    unlocked_lore_room = db.BooleanField(default=False)
    unlocked_top_room = db.BooleanField(default=False)
    stats_ghosts_caught = db.IntField(default=0)
    stats_puzzles_solved = db.IntField(default=0)
    stats_items_bought = db.IntField(default=0)
    destroyed_seals = db.IntField(default=0)
    gate_test_answer = db.StringField(default='')
    last_name_change = db.DateTimeField()
    last_password_change = db.DateTimeField()
    last_seen_news = db.DateTimeField()
    last_seen_decs = db.DateTimeField()
    last_seen_store = db.DateTimeField()
    last_seen_puzzles = db.DateTimeField()
    facebook_link = db.StringField(default='')
    secret_achievements = db.ListField(db.StringField(), default=list)
    
    # الحقول الجديدة للميكانيكيات المضافة
    has_shield = db.BooleanField(default=False)      # وشاح الحماية (يحمي من العين واليد)
    totem_self = db.BooleanField(default=False)      # توتم إحياء النفس (يُستعمل مرة واحدة)

class News(db.Document):
    meta = {
        'strict': False,
        'indexes': [
            'category',
            'status',
            'created_at',
            ('category', 'status', 'created_at')
        ]
    }
    title = db.StringField(required=True)
    content = db.StringField(required=True)
    category = db.StringField(default='news')
    puzzle_type = db.StringField(default='none')   # none, text, click_count, word_order, quicksand_trap, fake_account, cursed_ghost, hidden_link, secret_word
    puzzle_answer = db.StringField(default='')
    reward_points = db.IntField(default=0)
    max_winners = db.IntField(default=1)
    current_winners = db.IntField(default=0)
    winners_list = db.ListField(db.StringField(), default=list)
    trap_duration_minutes = db.IntField(default=0)
    trap_penalty_points = db.IntField(default=0)
    author = db.StringField(default='الإمبراطور')
    status = db.StringField(default='approved')
    image_data = db.StringField(default='')
    likes = db.ListField(db.StringField(), default=list)
    laughs = db.ListField(db.StringField(), default=list)
    created_at = db.DateTimeField(default=datetime.utcnow)

class StoreItem(db.Document):
    meta = {
        'strict': False,
        'indexes': [
            'name',
            'item_type',
            'created_at'
        ]
    }
    name = db.StringField(required=True, unique=True)
    description = db.StringField(default='')
    price = db.IntField(default=0)
    item_type = db.StringField(default='box')  # weapon, heal, spy, steal, seal, shield, totem_self, totem_other
    effect_amount = db.IntField(default=0)
    is_mirage = db.BooleanField(default=False)
    mirage_message = db.StringField(default='')
    is_luck = db.BooleanField(default=False)
    luck_min = db.IntField(default=0)
    luck_max = db.IntField(default=0)
    image = db.StringField(default='')
    created_at = db.DateTimeField(default=datetime.utcnow)

class GlobalSettings(db.Document):
    meta = {
        'strict': False,
        'indexes': [
            'setting_name'
        ]
    }
    setting_name = db.StringField(unique=True, default='main_config')
    maze_name = db.StringField(default='متاهة سيفار')
    home_title = db.StringField(default='البوابة')
    banner_url = db.StringField(default='')
    global_news_active = db.BooleanField(default=False)
    global_news_text = db.StringField(default='')
    nav_home = db.StringField(default='الرئيسية')
    nav_profile = db.StringField(default='هويتي')
    nav_friends = db.StringField(default='التحالفات')
    nav_news = db.StringField(default='المراسيم')
    nav_puzzles = db.StringField(default='النقوش')
    nav_decs = db.StringField(default='التصريحات')
    nav_store = db.StringField(default='السوق المظلم')
    nav_altar = db.StringField(default='مذبح الطلاسم')
    nav_grave = db.StringField(default='المقبرة')
    maintenance_mode = db.BooleanField(default=False)
    maintenance_until = db.DateTimeField()
    maintenance_pages = db.ListField(db.StringField(), default=list)
    war_mode = db.BooleanField(default=False)
    war_end_time = db.DateTimeField()
    war_kill_target = db.IntField(default=15)
    bleed_rate_minutes = db.IntField(default=60)
    bleed_amount = db.IntField(default=1)
    final_battle_mode = db.BooleanField(default=False)
    gates_mode_active = db.BooleanField(default=False)
    gates_end_time = db.DateTimeField()
    gates_description = db.StringField(default='')
    gate_1_name = db.StringField(default='بوابة 1')
    gate_2_name = db.StringField(default='بوابة 2')
    gate_3_name = db.StringField(default='بوابة 3')
    gates_selection_locked = db.BooleanField(default=False)
    gates_test_message = db.StringField(default='الاختبار')
    floor3_mode_active = db.BooleanField(default=False)
    vote_end_time = db.DateTimeField()
    vote_top_n = db.IntField(default=5)
    poneglyph_text = db.StringField(default='')
    dead_count = db.IntField(default=0)

class SpellConfig(db.Document):
    meta = {
        'strict': False,
        'indexes': [
            'spell_word',
            'expires_at'
        ]
    }
    spell_word = db.StringField(required=True, unique=True)
    spell_type = db.StringField(required=True)   # hp_gain, hp_loss, points_gain, points_loss, item_reward, unlock_lore, unlock_top, kill_emperor
    effect_value = db.IntField(default=0)
    is_percentage = db.BooleanField(default=False)
    item_name = db.StringField(default='')
    max_uses = db.IntField(default=1)
    used_by = db.ListField(db.StringField(), default=list)
    expires_at = db.DateTimeField()
    created_at = db.DateTimeField(default=datetime.utcnow)
