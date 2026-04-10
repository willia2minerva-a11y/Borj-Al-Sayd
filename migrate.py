# migrate.py
from models import User
from mongoengine import connect
import os

# الاتصال بقاعدة البيانات
MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    print("❌ MONGO_URI not found in environment variables")
    exit(1)

if 'retryWrites=true' not in MONGO_URI:
    sep = '&' if '?' in MONGO_URI else '?'
    MONGO_URI += f'{sep}retryWrites=true'

connect(host=MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)

print("🔄 جاري ترحيل قاعدة البيانات...")

# إضافة الحقول المفقودة لجميع المستخدمين
for user in User.objects():
    updated = False
    
    # قائمة الحقول التي يجب إضافتها
    if not hasattr(user, 'f1_last_move') or user.f1_last_move is None:
        user.update(set__f1_last_move=None)
        updated = True
        print(f"  ✓ Added f1_last_move to {user.username}")
    
    if not hasattr(user, 'f1_last_kill') or user.f1_last_kill is None:
        user.update(set__f1_last_kill=None)
        updated = True
        print(f"  ✓ Added f1_last_kill to {user.username}")
    
    if not hasattr(user, 'used_vent'):
        user.update(set__used_vent=False)
        updated = True
        print(f"  ✓ Added used_vent to {user.username}")
    
    if not hasattr(user, 'emergency_used'):
        user.update(set__emergency_used=False)
        updated = True
        print(f"  ✓ Added emergency_used to {user.username}")
    
    if not hasattr(user, 'f1_has_voted'):
        user.update(set__f1_has_voted=False)
        updated = True
        print(f"  ✓ Added f1_has_voted to {user.username}")
    
    if not hasattr(user, 'f1_votes_received'):
        user.update(set__f1_votes_received=0)
        updated = True
        print(f"  ✓ Added f1_votes_received to {user.username}")
    
    if not hasattr(user, 'gems_collected'):
        user.update(set__gems_collected=0)
        updated = True
        print(f"  ✓ Added gems_collected to {user.username}")
    
    if not hasattr(user, 'is_cursed'):
        user.update(set__is_cursed=False)
        updated = True
        print(f"  ✓ Added is_cursed to {user.username}")
    
    if not hasattr(user, 'group_id'):
        user.update(set__group_id=0)
        updated = True
        print(f"  ✓ Added group_id to {user.username}")
    
    if not hasattr(user, 'current_room'):
        user.update(set__current_room='قاعة العروش')
        updated = True
        print(f"  ✓ Added current_room to {user.username}")
    
    if not hasattr(user, 'f1_tasks'):
        user.update(set__f1_tasks=[])
        updated = True
        print(f"  ✓ Added f1_tasks to {user.username}")
    
    if not updated:
        print(f"  ✓ {user.username} already has all fields")

print("\n✅ تم ترحيل قاعدة البيانات بنجاح!")
