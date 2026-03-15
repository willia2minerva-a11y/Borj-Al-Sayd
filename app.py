from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, BattleLog, LoreLog, SpellConfig
from functools import wraps
from datetime import datetime, timedelta
import os, base64, random, math, json, traceback

app = Flask(__name__)
app.config['MONGODB_SETTINGS'] = {'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db')}
app.config['SECRET_KEY'] = 'sephar-maze-emperor-v11'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
db.init_app(app)

# 🚨 كاشف الأخطاء الجذري: سيظهر لك سبب الخطأ بدقة في الموقع بدلاً من الشاشة البيضاء
@app.errorhandler(Exception)
def handle_exception(e):
    err = traceback.format_exc()
    return f"<div style='direction:ltr; background:#0a0a0a; color:#ff5555; padding:20px; font-family:monospace; border:2px solid red;'><h2>🚨 System Crash Report</h2><pre>{err}</pre></div>", 500

class ActionLog(db.Document):
    meta = {'strict': False}
    action_text = db.StringField(); category = db.StringField()
    created_at = db.DateTimeField(default=datetime.utcnow)
    log_date = db.StringField(default=lambda: datetime.utcnow().strftime('%Y-%m-%d'))

def log_action(text, cat, is_epic=False):
    try: 
        ActionLog(action_text=text, category=cat).save()
        if is_epic: LoreLog(content=text, is_epic=True).save()
        elif random.random() < 0.3: LoreLog(content=text).save()
    except: pass

def check_achievements(u):
    try:
        achs = getattr(u, 'achievements', []) or []; na = []
        if getattr(u, 'stats_ghosts_caught', 0) >= 5 and 'صائد الأشباح 👻' not in achs:
            u.achievements.append('صائد الأشباح 👻'); na.append('صائد الأشباح 👻'); u.intelligence_points += 10
        if getattr(u, 'stats_puzzles_solved', 0) >= 5 and 'حكيم سيفار 📜' not in achs:
            u.achievements.append('حكيم سيفار 📜'); na.append('حكيم سيفار 📜'); u.intelligence_points += 20
        if getattr(u, 'stats_items_bought', 0) >= 5 and 'التاجر الخبير 🐪' not in achs:
            u.achievements.append('التاجر الخبير 🐪'); na.append('التاجر الخبير 🐪')
        if len(getattr(u, 'friends', []) or []) >= 5 and 'حليف القوم 🤝' not in achs:
            u.achievements.append('حليف القوم 🤝'); na.append('حليف القوم 🤝'); u.loyalty_points += 15
        if na: flash(f'🏆 إنجاز جديد: {", ".join(na)}', 'success')
        u.save()
    except: pass

def check_lazy_death_and_bleed(u, s):
    try:
        if not u or getattr(u, 'role', '') == 'admin' or getattr(u, 'status', '') != 'active': return
        now = datetime.utcnow(); la = getattr(u, 'last_active', None) or getattr(u, 'created_at', None) or now
        if (now - la).total_seconds() / 3600.0 > 72:
            u.health = 0; u.status = 'eliminated'; u.freeze_reason = 'ابتلعته الرمال'; log_action(f"💀 هلك {u.username} بسبب الغياب", "system"); u.save(); return
        if s and (getattr(s, 'war_mode', False) or getattr(s, 'final_battle_mode', False)):
            act = getattr(u, 'last_action_time', None) or now; safe = act + timedelta(minutes=getattr(s, 'safe_time_minutes', 120))
            if now > safe:
                st = max(getattr(u, 'last_health_check', None) or safe, safe); mins = (now - st).total_seconds() / 60.0
                br = getattr(s, 'bleed_rate_minutes', 60)
                if br > 0 and mins >= br:
                    cyc = math.floor(mins / br); u.health -= cyc * getattr(s, 'bleed_amount', 1); u.last_health_check = now
                    if u.health <= 0:
                        u.health = 0; u.status = 'eliminated'; u.freeze_reason = 'نزف في المعركة'; s.dead_count = getattr(s, 'dead_count', 0) + 1
                        log_action(f"🩸 نزف {u.username} حتى الموت.", "combat")
                        if getattr(s, 'war_mode', False) and s.dead_count >= getattr(s, 'war_kill_target', 15):
                            s.war_mode = False; log_action(f"🛑 سقط {s.dead_count} ضحية، توقفت الحرب لتبدأ المحكمة!", "system", True)
                        s.save()
                    u.save()
    except: pass

@app.before_request
def check_locks_and_status():
    if request.endpoint in ['static', 'login', 'logout', 'register']: return
    try: settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    except: settings = None
    u = None
    if 'user_id' in session:
        try:
            u = User.objects(id=session.get('user_id')).first()
            if not u: session.clear(); return redirect(url_for('login'))
        except: session.clear(); return redirect(url_for('login'))
    if getattr(settings, 'maintenance_mode', False):
        m_u = getattr(settings, 'maintenance_until', None)
        if m_u and datetime.utcnow() > m_u: settings.maintenance_mode = False; settings.maintenance_pages = []; settings.save()
        elif not u or getattr(u, 'role', '') != 'admin':
            mp = getattr(settings, 'maintenance_pages', []) or []
            if 'all' in mp or request.endpoint in mp: return render_template('locked.html', message='جاري ترميم الصفحة ⏳')
    if u:
        try: u.last_active = datetime.utcnow(); u.save(); check_lazy_death_and_bleed(u, settings)
        except: pass
        q = getattr(u, 'quicksand_lock_until', None)
        if q and datetime.utcnow() < q: tl = q - datetime.utcnow(); return render_template('locked.html', message=f'مقيّد لـ {tl.seconds//60}د')
        if getattr(u, 'gate_status', '') == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']:
            return render_template('gate_test.html', message=getattr(settings, 'gates_test_message', 'الاختبار'), user=u)

@app.context_processor
def inject_notifications():
    n = {'un_news':0, 'un_puz':0, 'un_dec':0, 'un_store':0, 'current_user':None, 'war_settings':None, 'battle_logs':[]}
    try:
        s = GlobalSettings.objects(setting_name='main_config').first(); n['war_settings'] = s
        if s and (getattr(s, 'war_mode', False) or getattr(s, 'final_battle_mode', False)): n['battle_logs'] = BattleLog.objects().order_by('-created_at')[:3]
    except: pass
    if 'user_id' in session:
        try:
            u = User.objects(id=session['user_id']).first()
            if u:
                n['current_user'] = u; now = datetime.utcnow()
                n['un_news'] = News.objects(category='news', status='approved', created_at__gt=(getattr(u, 'last_seen_news', None) or now)).count()
                n['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=(getattr(u, 'last_seen_puzzles', None) or now)).count()
                n['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=(getattr(u, 'last_seen_decs', None) or now)).count()
                n['un_store'] = StoreItem.objects(created_at__gt=(getattr(u, 'last_seen_store', None) or now)).count()
        except: pass
    return n

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        u = User.objects(id=session['user_id']).first()
        if not u or getattr(u, 'role', '') != 'admin': return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def home():
    try: settings = GlobalSettings.objects(setting_name='main_config').first()
    except: settings = None
    user = User.objects(id=session.get('user_id')).first() if 'user_id' in session else None
    
    an = []; all_n = News.objects(category='news', status='approved').order_by('-created_at')
    for x in all_n:
        tg = getattr(x, 'target_group', 'all') or 'all'
        if tg == 'all' or (user and getattr(user, 'gate_status', '') == 'testing' and tg == 'testing') or (user and getattr(user, 'status', '') == 'eliminated' and tg == 'ghosts') or (user and getattr(user, 'role', '') == 'hunter' and tg == 'hunters'): an.append(x)
    
    ln = an[0] if an else None
    ld = News.objects(category='declaration', status='approved').order_by('-created_at').first()
    ac = User.objects(status='active', hunter_id__ne=1000).count()
    dc = User.objects(status='eliminated', hunter_id__ne=1000).count()
    emp = User.objects(hunter_id=1000).first()
    hl = [{'id': h.hunter_id, 'name': h.username} for h in User.objects(status='active', role='hunter', hunter_id__ne=1000)] if settings and getattr(settings, 'floor3_mode_active', False) else []
    
    return render_template('index.html', settings=settings, news=ln, dec=ld, alive_count=ac, dead_count=dc, emperor=emp, active_hunters_json=json.dumps(hl))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.objects(username=request.form['username']).first(): flash('الاسم مستخدم مسبقاً.', 'error'); return redirect(url_for('register'))
        eids = [u.hunter_id for u in User.objects().only('hunter_id').order_by('hunter_id')]; nid = 1000
        for e in eids:
            if e == nid: nid += 1
            elif e > nid: break
        User(hunter_id=nid, username=request.form['username'], password_hash=generate_password_hash(request.form['password']), role='admin' if nid==1000 else 'hunter', status='active' if nid==1000 else 'inactive').save()
        log_action(f"✨ رحالة جديد انضم: {request.form['username']}", "system"); flash('تم التسجيل! حسابك قيد المراجعة.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.objects(username=request.form['username']).first()
        if u and check_password_hash(getattr(u, 'password_hash', ''), request.form['password']):
            session.permanent = True; session['user_id'] = str(u.id); session['role'] = getattr(u, 'role', 'hunter'); log_action(f"🔑 {u.username} دخل", "system")
            return redirect(url_for('home'))
        flash('بيانات خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    u = User.objects(id=session['user_id']).first(); s = GlobalSettings.objects(setting_name='main_config').first(); mi = StoreItem.objects(name__in=getattr(u, 'inventory', []) or [])
    return render_template('profile.html', user=u, banner_url=getattr(s, 'banner_url', ''), my_items=mi, my_seals=[i for i in mi if getattr(i, 'item_type', '') == 'seal'])

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    u = User.objects(id=session['user_id']).first(); act = request.form.get('action'); now = datetime.utcnow()
    if act == 'change_avatar':
        f = request.files.get('avatar_file')
        if f and f.filename != '': u.avatar = f"data:{f.content_type};base64,{base64.b64encode(f.read()).decode('utf-8')}"; flash('تم التحديث!', 'success')
    elif act == 'change_name':
        nn = request.form.get('new_name'); lc = getattr(u, 'last_name_change', None)
        if lc and (now - lc).days < 15: flash('يسمح بالتغيير كل 15 يوماً!', 'error')
        elif User.objects(username=nn).first(): flash('الاسم مستخدم!', 'error')
        else: u.username = nn; u.last_name_change = now; flash('تم التغيير!', 'success')
    elif act == 'change_password':
        op = request.form.get('old_password'); np = request.form.get('new_password'); cp = request.form.get('confirm_password'); lp = getattr(u, 'last_password_change', None)
        if lp and (now - lp).days < 1: flash('مرة واحدة يومياً!', 'error')
        elif not check_password_hash(getattr(u, 'password_hash', ''), op): flash('كلمة السر القديمة خاطئة!', 'error')
        elif np != cp: flash('غير متطابقتين!', 'error')
        else: u.password_hash = generate_password_hash(np); u.last_password_change = now; flash('تم التغيير!', 'success')
    u.save(); return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    tu = User.objects(hunter_id=target_id).first()
    if not tu or getattr(tu, 'role', '') in ['ghost', 'cursed_ghost']: return redirect(url_for('home'))
    s = GlobalSettings.objects(setting_name='main_config').first(); check_lazy_death_and_bleed(tu, s)
    cu = User.objects(id=session['user_id']).first(); mi = StoreItem.objects(name__in=getattr(cu, 'inventory', []) or [])
    return render_template('hunter_profile.html', target_user=tu, banner_url=getattr(s, 'banner_url', ''), my_weapons=[i for i in mi if getattr(i, 'item_type', '')=='weapon'], my_heals=[i for i in mi if getattr(i, 'item_type', '')=='heal'], my_spies=[i for i in mi if getattr(i, 'item_type', '')=='spy'], my_steals=[i for i in mi if getattr(i, 'item_type', '')=='steal'])

@app.route('/admin_update_profile/<int:target_id>', methods=['POST'])
@admin_required
def admin_update_profile(target_id):
    tu = User.objects(hunter_id=target_id).first()
    if tu:
        a = request.form.get('action')
        if a == 'edit_name': tu.username = request.form.get('new_name')
        elif a == 'edit_points': tu.points = int(request.form.get('new_points') or 0)
        elif a == 'edit_hp':
            tu.health = int(request.form.get('new_hp') or 0)
            if tu.health <= 0: tu.health = 0; tu.status = 'eliminated'
            elif tu.status == 'eliminated': tu.status = 'active'
        tu.save(); flash('تم التعديل!', 'success')
    return redirect(url_for('hunter_profile', target_id=target_id))

@app.route('/transfer/<int:target_id>', methods=['POST'])
@login_required
def transfer(target_id):
    s = User.objects(id=session['user_id']).first(); r = User.objects(hunter_id=target_id).first()
    if getattr(s, 'status', '') != 'active' or not r or getattr(r, 'status', '') != 'active' or r.hunter_id not in getattr(s, 'friends', []): return redirect(request.referrer or url_for('home'))
    t = request.form.get('transfer_type')
    if t == 'points':
        amt = int(request.form.get('amount') or 0)
        if 0 < amt <= s.points: s.points -= amt; r.points += amt; s.loyalty_points += 2; s.save(); r.save(); log_action(f"📦 {s.username} حول {amt} نقطة", "social"); flash('تم التحويل!', 'success')
    elif t == 'item':
        itm = request.form.get('item_name')
        if itm in getattr(s, 'inventory', []): s.inventory.remove(itm); r.inventory.append(itm); s.loyalty_points += 5; s.save(); r.save(); flash('تم الإرسال!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    a = User.objects(id=session['user_id']).first(); t = User.objects(hunter_id=target_id).first(); s = GlobalSettings.objects(setting_name='main_config').first()
    iname = request.form.get('item_name'); i = StoreItem.objects(name=iname).first()
    if not i or iname not in getattr(a, 'inventory', []) or getattr(t, 'status', '') != 'active': return redirect(request.referrer or url_for('home'))
    now = datetime.utcnow(); itype = getattr(i, 'item_type', '')
    
    if itype == 'seal':
        if t.id == a.id:
            a.destroyed_seals = getattr(a, 'destroyed_seals', 0) + 1; a.inventory.remove(iname)
            if a.destroyed_seals >= 4:
                if s: s.war_mode = False; s.final_battle_mode = False; s.save()
                User.objects(status='active').update(health=100); flash('دُمرت اللعنة!', 'success'); log_action(f"🛡️ {a.username} دمر الختم 4", "system", True)
            else: flash('تم تدمير ختم!', 'success')
            a.save()
            
    elif itype == 'weapon' and (getattr(s, 'war_mode', False) or getattr(s, 'final_battle_mode', False)) and t.hunter_id not in getattr(a, 'friends', []):
        if getattr(t, 'role', '') == 'admin' and not getattr(s, 'final_battle_mode', False): flash('الإمبراطور محصن!', 'error'); return redirect(request.referrer or url_for('home'))
        hs = False
        for inv in getattr(t, 'inventory', []):
            if 'درع' in inv or 'shield' in inv.lower(): t.inventory.remove(inv); hs = True; break
        if hs: flash('الهدف يمتلك درعاً وضاعت ضربتك!', 'error')
        else:
            t.health -= getattr(i, 'effect_amount', 0); log_action(f"⚔️ {a.username} طعن {t.username}", "combat")
            if t.health <= 0:
                ht = False
                if not getattr(s, 'final_battle_mode', False) and not getattr(s, 'floor3_mode_active', False):
                    for inv in getattr(t, 'inventory', []):
                        if 'طوطم' in inv or 'totem' in inv.lower(): t.inventory.remove(inv); ht = True; break
                if ht: t.health = 50; flash('طوطم الخلود أعاده للحياة!', 'error')
                else:
                    t.health = 0; t.status = 'eliminated'; s.dead_count = getattr(s, 'dead_count', 0) + 1; log_action(f"💀 {t.username} هلك", "combat")
                    if getattr(t, 'role', '') == 'admin': s.final_battle_mode = False; s.war_mode = False; log_action(f"👑 سقط الإمبراطور!", "system", True)
                    if getattr(s, 'war_mode', False) and s.dead_count >= getattr(s, 'war_kill_target', 15): s.war_mode = False; log_action(f"🛑 اكتفت المتاهة", "system", True)
                    s.save()
            BattleLog(victim_name=t.username, weapon_name=i.name, remaining_hp=t.health).save(); flash('تمت الضربة!', 'success')
        a.inventory.remove(iname); a.last_action_time = now; a.save(); t.save()
        
    elif itype == 'heal':
        if t.id == a.id or t.hunter_id in getattr(a, 'friends', []):
            t.health = t.health + getattr(i, 'effect_amount', 0) if getattr(t, 'role', '') == 'admin' else min(100, t.health + getattr(i, 'effect_amount', 0))
            if t.id != a.id: a.loyalty_points += 5
            t.save(); a.inventory.remove(iname); a.last_action_time = now; a.save(); flash('عُولج!', 'success')
            
    elif itype == 'spy':
        if any('حجاب' in x or 'درع' in x for x in getattr(t, 'inventory', [])): flash('الهدف محصن!', 'error'); a.inventory.remove(iname); a.save()
        else: a.tajis_eye_until = now + timedelta(hours=1); a.inventory.remove(iname); a.save(); flash('تجسست بنجاح!', 'success')
        
    elif itype == 'steal':
        si = request.form.get('target_item')
        if si in getattr(t, 'inventory', []):
            if any('حجاب' in x or 'درع' in x for x in getattr(t, 'inventory', [])): flash('الهدف محصن!', 'error'); a.inventory.remove(iname); a.save()
            else:
                t.inventory.remove(si); a.inventory.append(si); a.inventory.remove(iname); a.intelligence_points += 5
                a.save(); t.save(); flash('تمت السرقة!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/altar', methods=['GET', 'POST'])
@login_required
def altar():
    u = User.objects(id=session['user_id']).first()
    if getattr(u, 'status', '') != 'active': return redirect(url_for('home'))
    if request.method == 'POST':
        sw = request.form.get('spell_word', '').strip(); sp = SpellConfig.objects(spell_word=sw).first(); s = GlobalSettings.objects(setting_name='main_config').first()
        if not sp: flash('صمت...', 'error'); return redirect(url_for('altar'))
        st = getattr(sp, 'spell_type', ''); val = getattr(sp, 'effect_value', 0); is_p = getattr(sp, 'is_percentage', False); msg = getattr(sp, 'lore_message', f"الرحالة [user] تلا تعويذة!")
        
        if st == 'hp_loss':
            u.health -= int(u.health * (val/100.0)) if is_p else val
            if u.health <= 0: u.health = 0; u.status = 'eliminated'; u.freeze_reason = 'تعويذة'
            flash('دفعت ضريبة الدم!', 'error')
        elif st == 'hp_gain': u.health = min(100, u.health + (int(u.health * (val/100.0)) if is_p else val)); flash('طاقة تسري بك!', 'success')
        elif st == 'points_loss': u.points = max(0, u.points - (int(u.points * (val/100.0)) if is_p else val)); flash('تبخرت أموالك!', 'error')
        elif st == 'item_reward':
            iname = getattr(sp, 'item_name', '')
            if iname: u.inventory.append(iname); flash(f'ظهرت ({iname})!', 'success')
        elif st == 'unlock_lore': u.unlocked_lore_room = True; flash('غرفة السجلات فُتحت.', 'success')
        elif st == 'unlock_top': u.unlocked_top_room = True; flash('قاعة الأساطير فُتحت.', 'success')
        elif st == 'kill_emperor':
            if getattr(s, 'final_battle_mode', False):
                emp = User.objects(hunter_id=1000).first()
                if emp: emp.health = 0; emp.status = 'eliminated'; emp.save(); s.final_battle_mode = False; s.war_mode = False; s.save(); log_action(f"👑 {u.username} أسقط الإمبراطور!", "system", True); flash('سقط الإمبراطور!', 'success')
            else: flash('محصن حالياً.', 'error')
        log_action(msg.replace('[user]', u.username), "puzzle", True); u.save(); return redirect(url_for('altar'))
    return render_template('altar.html')

@app.route('/lore_room')
@login_required
def lore_room():
    u = User.objects(id=session['user_id']).first()
    if getattr(u, 'status', '') != 'active' or not getattr(u, 'unlocked_lore_room', False): return redirect(url_for('home'))
    return render_template('lore_room.html', logs=LoreLog.objects().order_by('-created_at'))

@app.route('/top_room')
@login_required
def top_room():
    u = User.objects(id=session['user_id']).first()
    if getattr(u, 'status', '') != 'active' or not getattr(u, 'unlocked_top_room', False): return redirect(url_for('home'))
    return render_template('top_room.html', top_iq=User.objects(hunter_id__ne=1000, status='active').order_by('-intelligence_points')[:10], top_loyal=User.objects(hunter_id__ne=1000, status='active').order_by('-loyalty_points')[:10], top_hp=User.objects(hunter_id__ne=1000, status='active').order_by('-health')[:10])

@app.route('/friends', methods=['GET'])
@login_required
def friends():
    u = User.objects(id=session['user_id']).first(); sq = request.args.get('search'); sr = None
    if sq: sr = User.objects(hunter_id=int(sq)).first() if sq.isdigit() else User.objects(username__icontains=sq).first()
    return render_template('friends.html', user=u, search_result=sr, friend_requests=User.objects(hunter_id__in=getattr(u, 'friend_requests', [])), friends=User.objects(hunter_id__in=getattr(u, 'friends', [])))

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    u = User.objects(id=session['user_id']).first(); t = User.objects(hunter_id=int(request.form.get('target_id') or 0)).first()
    if getattr(u, 'status', '') != 'active' or not t or getattr(t, 'status', '') != 'active': return redirect(request.referrer or url_for('home'))
    if getattr(t, 'role', '') in ['ghost', 'cursed_ghost']:
        trap = News.objects(puzzle_type='fake_account', puzzle_answer=str(t.hunter_id)).first()
        if getattr(t, 'role', '') == 'cursed_ghost' and trap: u.points -= getattr(trap, 'trap_penalty_points', 0); u.intelligence_points -= 5; u.save(); flash('فخ شبح!', 'error')
        elif trap and str(u.id) not in getattr(trap, 'winners_list', []) and getattr(trap, 'current_winners', 0) < getattr(trap, 'max_winners', 1):
            u.points += getattr(trap, 'reward_points', 0); trap.current_winners += 1; trap.winners_list.append(str(u.id)); u.intelligence_points += 10; u.save(); trap.save(); check_achievements(u); flash('اصطدت شبحاً!', 'success')
        return redirect(request.referrer or url_for('home'))
    if t.hunter_id not in getattr(u, 'friends', []) and u.hunter_id not in getattr(t, 'friend_requests', []):
        t.friend_requests.append(u.hunter_id); t.save(); flash('أُرسل الطلب', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/cancel_friend/<int:target_id>', methods=['POST'])
@login_required
def cancel_friend(target_id):
    u = User.objects(id=session['user_id']).first(); t = User.objects(hunter_id=target_id).first()
    if getattr(u, 'status', '') != 'active' or not t: return redirect(request.referrer or url_for('home'))
    if u.hunter_id in getattr(t, 'friend_requests', []): t.friend_requests.remove(u.hunter_id)
    elif t.hunter_id in getattr(u, 'friends', []): u.friends.remove(t.hunter_id); t.friends.remove(u.hunter_id); u.loyalty_points -= 20
    u.save(); t.save(); flash('تم الإلغاء', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    u = User.objects(id=session['user_id']).first(); f = User.objects(hunter_id=friend_id).first()
    if getattr(u, 'status', '') == 'active' and f and f.status == 'active' and friend_id in getattr(u, 'friend_requests', []):
        u.friend_requests.remove(friend_id); u.friends.append(friend_id); f.friends.append(u.hunter_id); f.save(); u.save(); check_achievements(u); flash('قُبل!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/news')
@login_required
def news():
    try: u = User.objects(id=session['user_id']).first(); u.last_seen_news = datetime.utcnow(); u.save()
    except: u = None
    return render_template('news.html', news_list=get_allowed_news(u))

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    u = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if getattr(u, 'status', '') != 'active': flash('حسابك قيد المراجعة.', 'error'); return redirect(url_for('puzzles'))
        g = request.form.get('guess'); puz = News.objects(id=request.form.get('puzzle_id')).first()
        if puz and g == getattr(puz, 'puzzle_answer', '') and str(u.id) not in getattr(puz, 'winners_list', []):
            if getattr(puz, 'current_winners', 0) < getattr(puz, 'max_winners', 1):
                u.points += getattr(puz, 'reward_points', 0); puz.winners_list.append(str(u.id)); puz.current_winners += 1; u.intelligence_points += 10; u.save(); puz.save(); flash('إجابة صحيحة!', 'success')
            else: flash('نفدت الجوائز!', 'error')
        else: flash('إجابة خاطئة.', 'error')
        return redirect(url_for('puzzles'))
    try: u.last_seen_puzzles = datetime.utcnow(); u.save()
    except: pass
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/delete_puzzle/<puzzle_id>', methods=['POST'])
@admin_required
def delete_puzzle(puzzle_id):
    try: News.objects(id=puzzle_id).delete(); flash('تم الحذف!', 'success')
    except: pass
    return redirect(url_for('puzzles'))

@app.route('/secret_link/<puzzle_id>')
@login_required
def secret_link(puzzle_id):
    u = User.objects(id=session['user_id']).first()
    if getattr(u, 'status', '') != 'active': return redirect(url_for('home'))
    try: puz = News.objects(id=puzzle_id).first()
    except: return redirect(url_for('home'))
    if puz and getattr(puz, 'puzzle_type', '') == 'quicksand_trap':
        u.quicksand_lock_until = datetime.utcnow() + timedelta(minutes=getattr(puz, 'trap_duration_minutes', 5)); u.intelligence_points -= 5; u.save(); flash('فخ رمال!', 'error')
    elif puz and str(u.id) not in getattr(puz, 'winners_list', []) and getattr(puz, 'current_winners', 0) < getattr(puz, 'max_winners', 1):
        u.points += getattr(puz, 'reward_points', 0); puz.current_winners += 1; puz.winners_list.append(str(u.id)); u.intelligence_points += 15; u.save(); puz.save(); flash('جائزة سرية!', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    u = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        if getattr(u, 'status', '') != 'active': flash('حسابك قيد المراجعة.', 'error'); return redirect(url_for('declarations'))
        img = ''; f = request.files.get('image_file')
        if f: img = f"data:{f.content_type};base64,{base64.b64encode(f.read()).decode('utf-8')}"
        News(content=request.form.get('content', '').strip(), image_data=img, category='declaration', author=u.username, status='approved' if getattr(u, 'role', '') == 'admin' else 'pending').save(); flash('تم الإرسال', 'success'); return redirect(url_for('declarations'))
    try: u.last_seen_decs = datetime.utcnow(); u.save()
    except: pass
    appr = News.objects(category='declaration', status='approved').order_by('-created_at'); pend = News.objects(category='declaration', status='pending') if getattr(u, 'role', '') == 'admin' else []; my_pend = News.objects(category='declaration', status='pending', author=u.username).order_by('-created_at')
    avatars = {usr.username: getattr(usr, 'avatar', None) for usr in User.objects(username__in=set([d.author for d in appr] + [d.author for d in pend] + [d.author for d in my_pend])).only('username', 'avatar')}
    return render_template('declarations.html', approved_decs=appr, pending_decs=pend, my_pending_decs=my_pend, current_user=u, avatars=avatars)

@app.route('/delete_declaration/<dec_id>', methods=['POST'])
@login_required
def delete_declaration(dec_id):
    u = User.objects(id=session['user_id']).first(); dec = News.objects(id=dec_id).first()
    if dec and (dec.author == u.username or getattr(u, 'role', '') == 'admin'): dec.delete(); flash('تم الحذف!', 'success')
    return redirect(url_for('declarations'))

@app.route('/store')
@login_required
def store():
    try: u = User.objects(id=session['user_id']).first(); u.last_seen_store = datetime.utcnow(); u.save()
    except: pass
    return render_template('store.html', items=StoreItem.objects())

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    u = User.objects(id=session['user_id']).first()
    if getattr(u, 'status', '') != 'active': return redirect(url_for('store'))
    try: itm = StoreItem.objects(id=item_id).first()
    except: return redirect(url_for('store'))
    if u and itm and u.points >= itm.price:
        u.points -= itm.price
        if getattr(itm, 'is_luck', False): out = random.randint(getattr(itm, 'luck_min', 0), getattr(itm, 'luck_max', 0)); u.points += out; flash(f'النتيجة: {out}', 'success' if out >= 0 else 'error')
        elif getattr(itm, 'is_mirage', False): u.intelligence_points -= 10; flash(getattr(itm, 'mirage_message', 'فخ!'), 'error')
        else: u.inventory.append(itm.name); flash('تم الشراء!', 'success')
        u.save()
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated').order_by('-id'))

@app.route('/choose_gate', methods=['POST'])
@login_required
def choose_gate():
    u = User.objects(id=session['user_id']).first(); s = GlobalSettings.objects(setting_name='main_config').first()
    if getattr(u, 'status', '') != 'active': return redirect(url_for('home'))
    if getattr(s, 'gates_mode_active', False) and not getattr(s, 'gates_selection_locked', False) and getattr(u, 'chosen_gate', 0) == 0:
        u.chosen_gate = int(request.form.get('gate_num') or 0); u.gate_status = 'waiting'; u.save(); flash('تم التسجيل!', 'success')
    return redirect(url_for('home'))

@app.route('/submit_gate_test', methods=['POST'])
@login_required
def submit_gate_test():
    u = User.objects(id=session['user_id']).first()
    if getattr(u, 'gate_status', '') == 'testing': u.gate_test_answer = request.form.get('test_answer', ''); u.save()
    return redirect(url_for('home'))

@app.route('/submit_floor3_votes', methods=['POST'])
@login_required
def submit_floor3_votes():
    u = User.objects(id=session['user_id']).first()
    if getattr(u, 'hunter_id', 0) == 1000 or getattr(u, 'has_voted', False) or getattr(u, 'status', '') != 'active': return redirect(url_for('home'))
    try:
        tids = [int(request.form.get(f'target_{i}')) for i in range(1, 6)]; amts = [int(request.form.get(f'amount_{i}')) for i in range(1, 6)]
        if len(set(tids)) == 5 and sum(amts) == 100 and 1000 not in tids and u.hunter_id not in tids:
            for i, tid in enumerate(tids):
                tu = User.objects(hunter_id=tid).first()
                if tu: tu.survival_votes = getattr(tu, 'survival_votes', 0) + amts[i]; tu.save()
            u.has_voted = True; u.save(); flash('تم التثبيت!', 'success')
        else: flash('خطأ في التوزيع!', 'error')
    except: pass
    return redirect(url_for('home'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    try: s = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    except: s = None
    sd = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d')); logs = ActionLog.objects(log_date=sd).order_by('-created_at')
    
    if request.method == 'POST':
        act = request.form.get('action')
        try:
            if act == 'moderate_dec':
                d = News.objects(id=request.form.get('dec_id')).first()
                if d: (d.save(set__status='approved') if request.form.get('decision') == 'approve' else d.delete())
            elif act == 'add_targeted_news': News(title=request.form.get('title'), content=request.form.get('content'), category='news', target_group=request.form.get('target_group')).save()
            elif act == 'setup_maintenance':
                dur = int(request.form.get('m_duration') or 0); pg = request.form.getlist('m_pages')
                if dur > 0: s.maintenance_mode = True; s.maintenance_until = datetime.utcnow() + timedelta(minutes=dur); s.maintenance_pages = pg
                else: s.maintenance_mode = False; s.maintenance_pages = []
            elif act == 'toggle_war':
                s.war_mode = not getattr(s, 'war_mode', False)
                if not s.war_mode: User.objects(status='active').update(health=100); BattleLog.objects.delete()
            elif act == 'toggle_final_battle': s.final_battle_mode = not getattr(s, 'final_battle_mode', False)
            elif act == 'set_admin_hp': User.objects(hunter_id=1000).update(health=int(request.form.get('admin_hp') or 100))
            elif act == 'add_news': News(title=request.form.get('title'), content=request.form.get('content'), category='puzzle' if request.form.get('puzzle_type') != 'none' else 'news', puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1)).save()
            elif act == 'add_standalone_puzzle':
                News(title="لغز", content="خفي", category='hidden', puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer', ''), reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1), trap_duration_minutes=int(request.form.get('trap_duration') or 0), trap_penalty_points=int(request.form.get('trap_penalty') or 0)).save()
                if request.form.get('puzzle_type') in ['fake_account', 'cursed_ghost']: User(hunter_id=int(request.form.get('puzzle_answer')), username=f"شبح_{request.form.get('puzzle_answer')}", password_hash="dummy", role='ghost' if request.form.get('puzzle_type') == 'fake_account' else 'cursed_ghost', status='active', avatar='👻').save()
            elif act == 'add_store_item':
                im = ''; f = request.files.get('item_image')
                if f: im = f"data:{f.content_type};base64,{base64.b64encode(f.read()).decode('utf-8')}"
                StoreItem(name=request.form.get('item_name'), description=request.form.get('item_desc'), price=int(request.form.get('item_price') or 0), item_type=request.form.get('item_type'), effect_amount=int(request.form.get('effect_amount') or 0), is_mirage=bool(request.form.get('is_mirage')), mirage_message=request.form.get('mirage_message', ''), is_luck=bool(request.form.get('is_luck')), luck_min=int(request.form.get('luck_min') or 0), luck_max=int(request.form.get('luck_max') or 0), image=im).save()
            elif act == 'add_spell': SpellConfig(spell_word=request.form.get('spell_word'), spell_type=request.form.get('spell_type'), effect_value=int(request.form.get('effect_value') or 0), is_percentage=bool(request.form.get('is_percentage')), item_name=request.form.get('item_name', ''), lore_message=request.form.get('lore_message', '[user] ألقى تعويذة')).save()
            elif act == 'bulk_action':
                bt = request.form.get('bulk_type')
                for uid in request.form.getlist('selected_users'):
                    u = User.objects(id=uid).first()
                    if u and getattr(u, 'hunter_id', 0) != 1000:
                        if bt == 'hard_delete': u.delete()
                        elif bt == 'activate': u.status = 'active'; u.health = 100; u.save()
                        elif bt == 'eliminate': u.status = 'eliminated'; u.freeze_reason = request.form.get('bulk_reason', 'بأمر الإدارة'); u.save()
            elif act == 'setup_gates': s.gates_mode_active = True; s.gates_selection_locked = bool(request.form.get('locked')); s.gates_description = request.form.get('desc', ''); s.gate_1_name = request.form.get('g1', ''); s.gate_2_name = request.form.get('g2', ''); s.gate_3_name = request.form.get('g3', ''); s.gates_test_message = request.form.get('test_msg', '')
            elif act == 'close_gates_mode': s.gates_mode_active = False
            elif act == 'judge_gates':
                fs = {1: request.form.get('fate_1'), 2: request.form.get('fate_2'), 3: request.form.get('fate_3')}
                for u in User.objects(gate_status='waiting', status='active'):
                    f = fs.get(str(getattr(u, 'chosen_gate', 0))) 
                    if f == 'pass': u.gate_status = 'passed'
                    elif f == 'kill': u.status = 'eliminated'; u.freeze_reason = 'البوابة التهمته'
                    elif f == 'test': u.gate_status = 'testing'
                    u.save()
            elif act == 'judge_test_user':
                u = User.objects(id=request.form.get('user_id')).first()
                if u: 
                    if request.form.get('decision') == 'pass': u.gate_status = 'passed'
                    else: u.status = 'eliminated'; u.freeze_reason = 'فشل بالاختبار'
                    u.save()
            elif act == 'toggle_floor3': s.floor3_mode_active = not getattr(s, 'floor3_mode_active', False)
            elif act == 'punish_floor3_slackers':
                sl = User.objects(has_voted=False, status='active', role='hunter'); av = User.objects(has_voted=True, status='active', role='hunter')
                if sl.count() > 0 and av.count() > 0:
                    bn = (sl.count() * 100) // av.count()
                    for v in av: v.survival_votes = getattr(v, 'survival_votes', 0) + bn; v.save()
                for x in sl: x.status = 'eliminated'; x.freeze_reason = 'لم يصوت'; x.save()
            elif act == 'update_war_settings': s.bleed_rate_minutes = int(request.form.get('bleed_rate_minutes') or 60); s.bleed_amount = int(request.form.get('bleed_amount') or 1); s.safe_time_minutes = int(request.form.get('safe_time_minutes') or 120); s.war_kill_target = int(request.form.get('war_kill_target') or 15)
            elif act == 'update_nav_names': s.nav_home = request.form.get('nav_home', getattr(s, 'nav_home', '')); s.nav_profile = request.form.get('nav_profile', getattr(s, 'nav_profile', '')); s.nav_friends = request.form.get('nav_friends', getattr(s, 'nav_friends', '')); s.nav_news = request.form.get('nav_news', getattr(s, 'nav_news', '')); s.nav_puzzles = request.form.get('nav_puzzles', getattr(s, 'nav_puzzles', '')); s.nav_decs = request.form.get('nav_decs', getattr(s, 'nav_decs', '')); s.nav_store = request.form.get('nav_store', getattr(s, 'nav_store', '')); s.nav_grave = request.form.get('nav_grave', getattr(s, 'nav_grave', '')); s.maze_name = request.form.get('maze_name', getattr(s, 'maze_name', ''))
            elif act == 'update_home_settings':
                s.home_title = request.form.get('home_title', 'البوابة'); s.home_color = request.form.get('home_color', 'var(--zone-0-black)')
                f = request.files.get('banner_file')
                if f and f.filename != '': s.banner_url = f"data:{f.content_type};base64,{base64.b64encode(f.read()).decode('utf-8')}"
            elif act == 'toggle_global_news': s.global_news_active = not getattr(s, 'global_news_active', False); s.global_news_text = request.form.get('global_news_text', '')
            if s: s.save()
        except: pass
        return redirect(url_for('admin_panel', date=sd))
    
    usrs = User.objects(hunter_id__ne=1000).order_by('hunter_id')
    return render_template('admin.html', users=usrs, settings=s, logs=logs, current_date=sd, test_users=User.objects(gate_status='testing', status='active'), gate_stats={1: User.objects(chosen_gate=1, status='active').count(), 2: User.objects(chosen_gate=2, status='active').count(), 3: User.objects(chosen_gate=3, status='active').count()}, floor3_leaders=User.objects(status='active', role='hunter').order_by('-survival_votes')[:5] if getattr(s, 'floor3_mode_active', False) else [])

@app.route('/download_logs/<log_date>')
@admin_required
def download_logs(log_date):
    out = f"--- سجلات ليوم {log_date} ---\n\n"
    for l in ActionLog.objects(log_date=log_date).order_by('created_at'): out += f"[{l.created_at.strftime('%H:%M:%S')}] ({l.category}): {l.action_text}\n"
    return Response(out, mimetype="text/plain", headers={"Content-disposition": f"attachment; filename=logs_{log_date}.txt"})

if __name__ == '__main__': 
    app.run(debug=True)

