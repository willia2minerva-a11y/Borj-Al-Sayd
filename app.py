from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, News, StoreItem, GlobalSettings, BattleLog
from functools import wraps
from datetime import datetime, timedelta
import os, base64, random, math, json

app = Flask(__name__)
app.config['MONGODB_SETTINGS'] = {'host': os.getenv('MONGO_URI', 'mongodb://localhost:27017/borj_db')}
app.config['SECRET_KEY'] = 'sephar-maze-ultimate-final-v99'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
db.init_app(app)

# 📜 نظام تدوين السجلات الإمبراطوري الشامل
class ActionLog(db.Document):
    meta = {'strict': False}
    action_text = db.StringField()
    category = db.StringField() 
    created_at = db.DateTimeField(default=datetime.utcnow)
    log_date = db.StringField(default=lambda: datetime.utcnow().strftime('%Y-%m-%d'))

def log_action(text, cat):
    try: ActionLog(action_text=text, category=cat).save()
    except: pass

# --- محرك الحماية والأنظمة ---

def check_lazy_death_and_bleed(user, settings):
    try:
        if not user or user.role == 'admin' or user.status != 'active': return
        now = datetime.utcnow()
        last_act = user.last_active or user.created_at or now
        if (now - last_act).total_seconds() / 3600.0 > 72:
            user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'ابتلعته الرمال لغيابه 72 ساعة'
            log_action(f"💀 هلك {user.username} بسبب الغياب", "system"); user.save(); return
        if settings and settings.war_mode:
            last_action = user.last_action_time or now
            safe_until = last_action + timedelta(minutes=settings.safe_time_minutes or 120)
            if now > safe_until:
                start_bleed_time = max(user.last_health_check or safe_until, safe_until)
                minutes_passed = (now - start_bleed_time).total_seconds() / 60.0
                if minutes_passed >= settings.bleed_rate_minutes:
                    cycles = math.floor(minutes_passed / settings.bleed_rate_minutes)
                    user.health -= cycles * settings.bleed_amount
                    user.last_health_check = now
                    if user.health <= 0:
                        user.health = 0; user.status = 'eliminated'; user.freeze_reason = 'نزف حتى الموت'
                        settings.dead_count = (settings.dead_count or 0) + 1; settings.save()
                    user.save()
    except: pass

@app.before_request
def check_locks_and_status():
    if request.endpoint in ['static', 'login', 'logout', 'register']: return
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    user = User.objects(id=session.get('user_id')).first() if 'user_id' in session else None
    if settings.maintenance_mode:
        if settings.maintenance_until and datetime.utcnow() > settings.maintenance_until:
            settings.maintenance_mode = False; settings.maintenance_pages = []; settings.save()
        elif not user or user.role != 'admin':
            if 'all' in settings.maintenance_pages or request.endpoint in settings.maintenance_pages:
                return render_template('locked.html', message='جاري ترميم هذه الصفحة ⏳')
    if user:
        user.last_active = datetime.utcnow(); user.save()
        check_lazy_death_and_bleed(user, settings)
        if user.quicksand_lock_until and datetime.utcnow() < user.quicksand_lock_until:
            return render_template('locked.html', message='مقيّد في الرمال!')
        if getattr(user, 'gate_status', '') == 'testing' and request.endpoint not in ['submit_gate_test', 'logout']:
            return render_template('gate_test.html', message=settings.gates_test_message, user=user)

@app.context_processor
def inject_notifications():
    notifs = {'un_news': 0, 'un_puz': 0, 'un_dec': 0, 'un_store': 0, 'current_user': None, 'war_settings': None, 'battle_logs': []}
    settings = GlobalSettings.objects(setting_name='main_config').first()
    notifs['war_settings'] = settings
    if settings and settings.war_mode: notifs['battle_logs'] = BattleLog.objects().order_by('-created_at')[:3]
    if 'user_id' in session:
        user = User.objects(id=session['user_id']).first()
        if user:
            notifs['current_user'] = user
            notifs['un_news'] = News.objects(category='news', status='approved', created_at__gt=user.last_seen_news).count()
            notifs['un_puz'] = News.objects(category='puzzle', status='approved', created_at__gt=user.last_seen_puzzles).count()
            notifs['un_dec'] = News.objects(category='declaration', status='approved', created_at__gt=user.last_seen_decs).count()
            notifs['un_store'] = StoreItem.objects(created_at__gt=user.last_seen_store).count()
    return notifs

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
        user = User.objects(id=session['user_id']).first()
        if not user or user.role != 'admin': return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

# --- المسارات الرئيسية ---

@app.route('/')
def home():
    settings = GlobalSettings.objects(setting_name='main_config').first()
    user = User.objects(id=session.get('user_id')).first() if 'user_id' in session else None
    news_q = db.Q(category='news', status='approved', target_group='all')
    if user:
        if user.gate_status == 'testing': news_q |= db.Q(target_group='testing')
        if user.status == 'eliminated': news_q |= db.Q(target_group='ghosts')
    latest_news = News.objects(news_q).order_by('-created_at').first()
    latest_dec = News.objects(category='declaration', status='approved').order_by('-created_at').first()
    last_frozen = User.objects(status='eliminated').order_by('-id').first()
    hunters_list = []
    if settings and settings.floor3_mode_active:
        hunters = User.objects(status='active', role='hunter', hunter_id__ne=1000)
        hunters_list = [{'id': h.hunter_id, 'name': h.username} for h in hunters]
    return render_template('index.html', settings=settings, news=latest_news, dec=latest_dec, last_frozen=last_frozen, active_hunters_json=json.dumps(hunters_list))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.objects(username=request.form['username']).first(): flash('الاسم مستخدم.', 'error'); return redirect(url_for('register'))
        existing_ids = [u.hunter_id for u in User.objects().only('hunter_id').order_by('hunter_id')]
        new_id = 1000
        for eid in existing_ids:
            if eid == new_id: new_id += 1
            elif eid > new_id: break
        User(hunter_id=new_id, username=request.form['username'], password_hash=generate_password_hash(request.form['password']), role='admin' if new_id==1000 else 'hunter').save()
        log_action(f"✨ انضمام رحالة: {request.form['username']} (#{new_id})", "system")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.objects(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session.permanent = True; session['user_id'] = str(user.id); session['role'] = user.role; return redirect(url_for('home'))
        flash('بيانات خاطئة.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    user = User.objects(id=session['user_id']).first(); settings = GlobalSettings.objects(setting_name='main_config').first()
    my_items = StoreItem.objects(name__in=user.inventory) if user.inventory else []
    return render_template('profile.html', user=user, banner_url=settings.banner_url if settings else '', my_items=my_items, my_seals=[i for i in my_items if i.item_type == 'seal'])
# --- الجزء الثاني التكميلي لملف app.py ---

@app.route('/settings', methods=['POST'])
@login_required
def update_settings():
    user = User.objects(id=session['user_id']).first(); action = request.form.get('action')
    if action == 'change_avatar':
        file = request.files.get('avatar_file')
        if file and file.filename != '': user.avatar = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"; flash('تم التحديث!', 'success')
    elif action == 'change_name':
        new_name = request.form.get('new_name'); now = datetime.utcnow()
        if user.last_name_change and (now - user.last_name_change).days < 15: flash('كل 15 يوم فقط!', 'error')
        elif User.objects(username=new_name).first(): flash('الاسم مستخدم!', 'error')
        else: user.username = new_name; user.last_name_change = now; flash('تم التغيير!', 'success')
    user.save(); return redirect(url_for('profile'))

@app.route('/hunter/<int:target_id>')
@login_required
def hunter_profile(target_id):
    target_user = User.objects(hunter_id=target_id).first()
    if not target_user or target_user.role in ['ghost', 'cursed_ghost']: return redirect(url_for('home'))
    settings = GlobalSettings.objects(setting_name='main_config').first()
    current_user = User.objects(id=session['user_id']).first()
    my_items = StoreItem.objects(name__in=current_user.inventory) if current_user.inventory else []
    return render_template('hunter_profile.html', target_user=target_user, banner_url=getattr(settings, 'banner_url', ''), 
                           my_weapons=[i for i in my_items if i.item_type=='weapon'], my_heals=[i for i in my_items if i.item_type=='heal'], 
                           my_spies=[i for i in my_items if i.item_type=='spy'], my_steals=[i for i in my_items if i.item_type=='steal'])

@app.route('/use_item/<int:target_id>', methods=['POST'])
@login_required
def use_item(target_id):
    attacker = User.objects(id=session['user_id']).first()
    target = User.objects(hunter_id=target_id).first(); settings = GlobalSettings.objects(setting_name='main_config').first()
    item_name = request.form.get('item_name'); item = StoreItem.objects(name=item_name).first()
    if not item or item_name not in attacker.inventory or target.status != 'active': return redirect(request.referrer)
    now = datetime.utcnow()
    if item.item_type == 'weapon' and settings.war_mode and target.hunter_id != 1000:
        target.health -= item.effect_amount
        log_action(f"⚔️ {attacker.username} طعن {target.username}", "combat")
        if target.health <= 0: 
            target.health = 0; target.status = 'eliminated'; settings.dead_count += 1; settings.save()
        BattleLog(victim_name=target.username, weapon_name=item.name, remaining_hp=target.health).save()
    elif item.item_type == 'heal':
        target.health = target.health + item.effect_amount if target.role == 'admin' else min(100, target.health + item.effect_amount)
    attacker.inventory.remove(item_name); attacker.last_action_time = now; attacker.save(); target.save()
    return redirect(request.referrer)

@app.route('/friends', methods=['GET'])
@login_required
def friends():
    user = User.objects(id=session['user_id']).first(); sq = request.args.get('search')
    sr = User.objects(hunter_id=int(sq)).first() if sq and sq.isdigit() else (User.objects(username__icontains=sq).first() if sq else None)
    return render_template('friends.html', user=user, search_result=sr, friend_requests=User.objects(hunter_id__in=user.friend_requests), friends=User.objects(hunter_id__in=user.friends))

@app.route('/accept_friend/<int:friend_id>')
@login_required
def accept_friend(friend_id):
    user = User.objects(id=session['user_id']).first(); f = User.objects(hunter_id=friend_id).first()
    if f and friend_id in user.friend_requests:
        user.friend_requests.remove(friend_id); user.friends.append(friend_id); f.friends.append(user.hunter_id); f.save(); user.save()
        log_action(f"🤝 تحالف: {user.username} و {f.username}", "social")
    return redirect(request.referrer)

@app.route('/puzzles', methods=['GET', 'POST'])
@login_required
def puzzles():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        guess = request.form.get('guess'); puz = News.objects(id=request.form.get('puzzle_id')).first()
        if puz and guess == puz.puzzle_answer and str(user.id) not in puz.winners_list:
            if puz.current_winners < puz.max_winners:
                user.points += puz.reward_points; puz.winners_list.append(str(user.id)); puz.current_winners += 1; user.save(); puz.save()
                log_action(f"🧩 {user.username} حل {puz.title}", "puzzle")
        return redirect(url_for('puzzles'))
    return render_template('puzzles.html', puzzles_list=News.objects(category='puzzle', status='approved').order_by('-created_at'))

@app.route('/declarations', methods=['GET', 'POST'])
@login_required
def declarations():
    user = User.objects(id=session['user_id']).first()
    if request.method == 'POST':
        img = ''; file = request.files.get('image_file')
        if file: img = f"data:{file.content_type};base64,{base64.b64encode(file.read()).decode('utf-8')}"
        News(content=request.form.get('content'), image_data=img, category='declaration', author=user.username, status='approved' if user.role == 'admin' else 'pending').save()
        log_action(f"📢 تصريح: {user.username}", "social"); return redirect(url_for('declarations'))
    approved = News.objects(category='declaration', status='approved').order_by('-created_at')
    my_pending = News.objects(category='declaration', status='pending', author=user.username)
    pending_all = News.objects(category='declaration', status='pending') if user.role == 'admin' else []
    return render_template('declarations.html', approved_decs=approved, pending_decs=pending_all, my_pending_decs=my_pending, current_user=user)

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_panel():
    settings = GlobalSettings.objects(setting_name='main_config').first() or GlobalSettings(setting_name='main_config').save()
    sel_date = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    logs = ActionLog.objects(log_date=sel_date).order_by('-created_at')
    if request.method == 'POST':
        act = request.form.get('action')
        if act == 'moderate_dec':
            d = News.objects(id=request.form.get('dec_id')).first()
            if d: (d.save(set__status='approved') if request.form.get('decision') == 'approve' else d.delete())
        elif act == 'bulk_action':
            bt = request.form.get('bulk_type')
            for uid in request.form.getlist('selected_users'):
                u = User.objects(id=uid).first()
                if u and u.hunter_id != 1000: (u.delete() if bt == 'hard_delete' else (u.save(set__status='active', set__health=100) if bt == 'activate' else u.save(set__status='eliminated')))
        elif act == 'set_admin_hp': User.objects(hunter_id=1000).update(health=int(request.form.get('admin_hp') or 100))
        elif act == 'add_news': News(title=request.form.get('title'), content=request.form.get('content'), category='puzzle' if request.form.get('puzzle_type') != 'none' else 'news', puzzle_type=request.form.get('puzzle_type'), puzzle_answer=request.form.get('puzzle_answer'), reward_points=int(request.form.get('reward_points') or 0), max_winners=int(request.form.get('max_winners') or 1)).save()
        settings.save(); return redirect(url_for('admin_panel', date=sel_date))
    return render_template('admin.html', users=User.objects(hunter_id__ne=1000).order_by('hunter_id'), settings=settings, logs=logs, current_date=sel_date)

@app.route('/download_logs/<log_date>')
@admin_required
def download_logs(log_date):
    logs = ActionLog.objects(log_date=log_date).order_by('-created_at')
    out = f"سجلات المتاهة - {log_date}\n" + "\n".join([f"[{l.created_at.strftime('%H:%M:%S')}] {l.action_text}" for l in logs])
    return Response(out, mimetype="text/plain", headers={"Content-disposition": f"attachment; filename=logs_{log_date}.txt"})

@app.route('/store')
@login_required
def store():
    user = User.objects(id=session['user_id']).first(); user.last_seen_store = datetime.utcnow(); user.save()
    return render_template('store.html', items=StoreItem.objects())

@app.route('/buy/<item_id>', methods=['POST'])
@login_required
def buy_item(item_id):
    user = User.objects(id=session['user_id']).first(); item = StoreItem.objects(id=item_id).first()
    if user and item and user.points >= item.price:
        user.points -= item.price
        user.inventory.append(item.name); user.save(); flash('تم الشراء!', 'success')
    return redirect(url_for('store'))

@app.route('/graveyard')
def graveyard(): return render_template('graveyard.html', users=User.objects(status='eliminated').order_by('-id'))

if __name__ == '__main__': app.run(debug=True)

