# models.py - الملف الكامل والنهائي لمتاهة سيفار

from mongoengine import connect, Document, StringField, IntField, BooleanField, DateTimeField, ListField, DictField, FloatField
from datetime import datetime
import os

# ==========================================
# اتصال قاعدة البيانات
# ==========================================
MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    raise Exception("MONGO_URI environment variable not set")

if 'retryWrites=true' not in MONGO_URI:
    sep = '&' if '?' in MONGO_URI else '?'
    MONGO_URI += f'{sep}retryWrites=true'

# إنشاء الاتصال
db = connect(
    host=MONGO_URI,
    tls=True,
    tlsAllowInvalidCertificates=True,
    connectTimeoutMS=30000,
    socketTimeoutMS=30000,
    serverSelectionTimeoutMS=30000
)

print("✅ تم الاتصال بقاعدة البيانات بنجاح")


# ==========================================
# نموذج المستخدم (User)
# ==========================================
class User(Document):
    # المعلومات الأساسية
    hunter_id = IntField(unique=True, required=True)
    username = StringField(unique=True, required=True)
    password_hash = StringField(required=True)
    role = StringField(default='hunter', choices=['hunter', 'admin', 'ghost', 'cursed_ghost'])
    status = StringField(default='active', choices=['active', 'inactive', 'eliminated', 'frozen', 'dead_body'])
    zone = StringField(default='البوابات')
    special_rank = StringField(default='مستكشف')
    
    # الروابط والإعدادات
    facebook_link = StringField()
    avatar = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    last_active = DateTimeField()
    last_name_change = DateTimeField()
    last_password_change = DateTimeField()
    last_action_time = DateTimeField()
    last_health_check = DateTimeField()
    
    # الإحصائيات والنقاط
    points = IntField(default=0)
    health = IntField(default=100)
    intelligence_points = IntField(default=0)
    loyalty_points = IntField(default=0)
    freeze_reason = StringField()
    
    # الطوابق والمراحل
    chosen_gate = IntField(default=0)
    gate_status = StringField(default='waiting', choices=['waiting', 'testing', 'passed', 'failed'])
    gate_test_answer = StringField()
    
    # التحالفات والأصدقاء
    friends = ListField(IntField(), default=list)
    friend_requests = ListField(IntField(), default=list)
    
    # المخزون والإنجازات
    inventory = ListField(StringField(), default=list)
    collected_seals = ListField(StringField(), default=list)
    achievements = ListField(StringField(), default=list)
    
    # الإحصائيات الإضافية
    stats_ghosts_caught = IntField(default=0)
    stats_puzzles_solved = IntField(default=0)
    stats_items_bought = IntField(default=0)
    
    # ==========================================
    # الطابق الأول (الاستنتاج - Among Us Style)
    # ==========================================
    group_id = IntField(default=0)  # رقم المجموعة
    current_room = StringField(default='قاعة العروش')  # الغرفة الحالية
    is_cursed = BooleanField(default=False)  # هل هو الملعون (القاتل)
    f1_tasks = ListField(DictField(), default=list)  # المهام الموزعة للاعب
    gems_collected = IntField(default=0)  # عدد الأحجار الكريمة المجمعة
    f1_has_voted = BooleanField(default=False)  # هل صوت في الاجتماع الحالي
    f1_votes_received = IntField(default=0)  # عدد الأصوات التي حصل عليها
    used_vent = BooleanField(default=False)  # هل استخدم النفق السري (مرة واحدة)
    emergency_used = BooleanField(default=False)  # هل استخدم زر الطوارئ (مرة واحدة)
    f1_last_move = DateTimeField()  # آخر وقت تحرك
    f1_last_kill = DateTimeField()  # آخر وقت قتل
    
    # ==========================================
    # الطابق الثالث (المحكمة)
    # ==========================================
    has_voted = BooleanField(default=False)  # هل صوت في المحكمة
    survival_votes = FloatField(default=0.0)  # أصوات النجاة
    f3_votes_cast = DictField(default=dict)  # الأصوات التي صوّتها اللاعب
    f3_vote_target = IntField()  # من صوّت ضده
    
    # ==========================================
    # المؤثرات والمهارات الخاصة
    # ==========================================
    quicksand_lock_until = DateTimeField()  # وقت انتهاء تجميد الرمال
    has_shield = BooleanField(default=False)  # هل لديه درع حماية
    totem_self = BooleanField(default=False)  # توتم إعادة الحياة
    tajis_eye_until = DateTimeField()  # وقت انتهاء عين تاجي (التجسس)
    
    # مناطق خاصة مفتوحة
    unlocked_lore_room = BooleanField(default=False)  # هل فتح غرفة البونغليف
    unlocked_top_room = BooleanField(default=False)  # هل فتح قاعة الأساطير
    
    # الأختام الأربعة
    has_seal_fire = BooleanField(default=False)
    has_seal_water = BooleanField(default=False)
    has_seal_earth = BooleanField(default=False)
    has_seal_air = BooleanField(default=False)
    
    meta = {
        'collection': 'users',
        'indexes': [
            'hunter_id',
            'username',
            'status',
            'group_id',
            'current_room'
        ]
    }
    
    def __str__(self):
        return f"{self.username} (ID: {self.hunter_id})"


# ==========================================
# نموذج الأخبار والألغاز (News)
# ==========================================
class News(Document):
    title = StringField(required=True)
    content = StringField(required=True)
    category = StringField(required=True, choices=['news', 'puzzle', 'declaration', 'hidden'])
    image_data = StringField()
    author = StringField()
    status = StringField(default='pending', choices=['pending', 'approved'])
    
    # للحلول والألغاز
    puzzle_type = StringField()
    puzzle_answer = StringField()
    reward_points = IntField(default=0)
    trap_penalty_points = IntField(default=0)
    reward_item = StringField()
    trap_duration_minutes = IntField(default=0)
    
    # للحد من الفائزين
    max_winners = IntField(default=1)
    current_winners = IntField(default=0)
    winners_list = ListField(StringField(), default=list)
    
    # للتفاعلات
    likes = ListField(StringField(), default=list)
    laughs = ListField(StringField(), default=list)
    
    created_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'news',
        'indexes': ['category', 'status', 'created_at']
    }


# ==========================================
# نموذج المتجر (StoreItem)
# ==========================================
class StoreItem(Document):
    name = StringField(required=True, unique=True)
    description = StringField()
    price = IntField(required=True, min_value=0)
    item_type = StringField(choices=['weapon', 'heal', 'spy', 'steal', 'seal', 'special'])
    effect_amount = IntField(default=0)
    effect_description = StringField()
    
    # للعناصر الخاصة
    is_mirage = BooleanField(default=False)
    mirage_message = StringField()
    is_luck = BooleanField(default=False)
    luck_min = IntField(default=0)
    luck_max = IntField(default=0)
    
    # الصورة
    image_url = StringField()
    
    created_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'store_items',
        'indexes': ['name', 'item_type', 'price']
    }


# ==========================================
# نموذج الإعدادات العامة (GlobalSettings)
# ==========================================
class GlobalSettings(Document):
    setting_name = StringField(unique=True, required=True)
    
    # الإعدادات العامة
    home_title = StringField(default='البوابة')
    maze_name = StringField(default='متاهة سيفار')
    banner_url = StringField()
    
    # أسماء القوائم
    nav_home = StringField(default='الرئيسية')
    nav_profile = StringField(default='هويتي')
    nav_friends = StringField(default='التحالفات')
    nav_news = StringField(default='المراسيم')
    nav_puzzles = StringField(default='النقوش')
    nav_store = StringField(default='السوق المظلم')
    nav_altar = StringField(default='مذبح الطلاسم')
    nav_decs = StringField(default='التصريحات')
    nav_grave = StringField(default='المقبرة')
    
    # الإعلانات
    global_news_active = BooleanField(default=False)
    global_news_text = StringField()
    
    # وضع الصيانة
    maintenance_mode = BooleanField(default=False)
    maintenance_until = DateTimeField()
    maintenance_pages = ListField(StringField(), default=list)
    
    # البوابات (Gate)
    gates_mode_active = BooleanField(default=False)
    gates_end_time = DateTimeField()
    gates_description = StringField()
    gate_1_name = StringField()
    gate_2_name = StringField()
    gate_3_name = StringField()
    gates_test_message = StringField()
    
    # ==========================================
    # الطابق الأول (الاستنتاج)
    # ==========================================
    floor1_mode_active = BooleanField(default=False)
    floor1_move_cooldown = IntField(default=30)  # ثواني بين التحركات
    floor1_kill_cooldown = IntField(default=60)  # ثواني بين القتلات
    floor1_gems_target = IntField(default=10)  # عدد الأحجار للفوز
    floor1_locked_room = StringField()
    floor1_locked_until = DateTimeField()
    floor1_darkness_until = DateTimeField()
    f1_active_meetings = DictField(default=dict)  # الاجتماعات النشطة
    
    # ==========================================
    # الطابق الثاني (الحرب)
    # ==========================================
    war_mode = BooleanField(default=False)
    war_end_time = DateTimeField()
    dead_count = IntField(default=0)
    war_kill_target = IntField(default=15)
    bleed_rate_minutes = IntField(default=60)  # كل كم دقيقة ينزف
    bleed_amount = IntField(default=1)  # كم ينقص من الصحة
    safe_time_minutes = IntField(default=120)  # وقت الأمان بعد آخر أكشن
    attack_cooldown_minutes = IntField(default=5)  # تبريد الهجوم
    
    # ==========================================
    # الطابق الثالث (المحكمة)
    # ==========================================
    floor3_mode_active = BooleanField(default=False)
    floor3_paused = BooleanField(default=False)
    floor3_time_left = IntField(default=0)
    floor3_results_active = BooleanField(default=False)
    vote_end_time = DateTimeField()
    vote_top_n = IntField(default=5)
    
    # ==========================================
    # المعركة الأخيرة
    # ==========================================
    final_battle_mode = BooleanField(default=False)
    
    # النصوص الأسطورية
    poneglyph_text = StringField()
    
    meta = {
        'collection': 'global_settings',
        'indexes': ['setting_name']
    }


# ==========================================
# نموذج التعاويذ (SpellConfig)
# ==========================================
class SpellConfig(Document):
    spell_word = StringField(unique=True, required=True)
    spell_type = StringField(choices=['hp_gain', 'hp_loss', 'points_gain', 'points_loss', 'item_reward', 'unlock_lore', 'unlock_top', 'kill_emperor'])
    effect_value = IntField(default=0)
    is_percentage = BooleanField(default=False)
    item_name = StringField()
    max_uses = IntField(default=1)
    used_by = ListField(StringField(), default=list)
    expires_at = DateTimeField()
    created_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'spells',
        'indexes': ['spell_word', 'expires_at']
    }


# ==========================================
# نموذج الإشعارات (Notification)
# ==========================================
class Notification(Document):
    target_hunter_id = IntField(required=True)
    message = StringField(required=True)
    notif_type = StringField(default='info', choices=['info', 'success', 'error', 'danger'])
    is_read = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'notifications',
        'indexes': ['target_hunter_id', 'is_read', 'created_at']
    }


# ==========================================
# نموذج رسائل المجموعة (GroupMessage)
# ==========================================
class GroupMessage(Document):
    group_id = IntField(required=True)
    sender_name = StringField(required=True)
    message = StringField(required=True)
    is_system_msg = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'group_messages',
        'indexes': ['group_id', 'created_at'],
        'ordering': ['created_at']
    }


# ==========================================
# دالة تهيئة قاعدة البيانات
# ==========================================
def init_db():
    """تهيئة قاعدة البيانات وإنشاء المستخدم الإمبراطور والإعدادات الافتراضية"""
    from werkzeug.security import generate_password_hash
    
    # إنشاء المستخدم الإمبراطور إذا لم يكن موجوداً
    if not User.objects(hunter_id=1000).first():
        User(
            hunter_id=1000,
            username='الإمبراطور',
            password_hash=generate_password_hash('admin123'),
            role='admin',
            status='active',
            zone='العرش',
            special_rank='حاكم المتاهة'
        ).save()
        print("✅ تم إنشاء المستخدم الإمبراطور")
    
    # إنشاء الإعدادات العامة إذا لم تكن موجودة
    if not GlobalSettings.objects(setting_name='main_config').first():
        GlobalSettings(setting_name='main_config').save()
        print("✅ تم إنشاء الإعدادات العامة")
    
    print("✅ تم تهيئة قاعدة البيانات بنجاح")


# ==========================================
# دالة ترحيل قاعدة البيانات (لإضافة الحقول الجديدة)
# ==========================================
def migrate_database():
    """ترحيل قاعدة البيانات لإضافة الحقول الجديدة للمستخدمين الموجودين"""
    print("🔄 جاري ترحيل قاعدة البيانات...")
    
    updated_count = 0
    
    for user in User.objects():
        updates = {}
        
        # التحقق من الحقول المفقودة وإضافتها
        if not hasattr(user, 'f1_last_move') or user.f1_last_move is None:
            updates['f1_last_move'] = None
        
        if not hasattr(user, 'f1_last_kill') or user.f1_last_kill is None:
            updates['f1_last_kill'] = None
        
        if not hasattr(user, 'used_vent'):
            updates['used_vent'] = False
        
        if not hasattr(user, 'emergency_used'):
            updates['emergency_used'] = False
        
        if not hasattr(user, 'f1_has_voted'):
            updates['f1_has_voted'] = False
        
        if not hasattr(user, 'f1_votes_received'):
            updates['f1_votes_received'] = 0
        
        if not hasattr(user, 'gems_collected'):
            updates['gems_collected'] = 0
        
        if not hasattr(user, 'is_cursed'):
            updates['is_cursed'] = False
        
        if not hasattr(user, 'group_id'):
            updates['group_id'] = 0
        
        if not hasattr(user, 'current_room'):
            updates['current_room'] = 'قاعة العروش'
        
        if not hasattr(user, 'f1_tasks'):
            updates['f1_tasks'] = []
        
        if updates:
            user.update(**updates)
            updated_count += 1
            print(f"  ✓ تم تحديث {user.username}")
    
    print(f"✅ تم ترحيل قاعدة البيانات بنجاح! (تم تحديث {updated_count} مستخدم)")


# ==========================================
# تشغيل الترحيل تلقائياً عند الاستيراد
# ==========================================
try:
    migrate_database()
except Exception as e:
    print(f"⚠️ تحذير: فشل ترحيل قاعدة البيانات: {e}")
