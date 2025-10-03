# app.py - الكود النهائي المضمون لبيئة Termux (الحل الجذري للـ TZ)

# **********************************************
# 1. الاستيرادات
# **********************************************
from datetime import datetime
import qrcode
import os
from pytz import timezone # فقط لاستخدامه داخل دالة الجدولة للمقارنة

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, current_user, UserMixin, login_required
from apscheduler.schedulers.background import BackgroundScheduler 
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore # لتخزين الوظائف

# **********************************************
# 2. إعدادات التطبيق وقاعدة البيانات
# **********************************************

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_strong_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# **********************************************
# 3. تهيئة المجدول (Scheduler) - الحل الجذري
# **********************************************

# إعدادات APScheduler لتعيين المنطقة الزمنية وتخزين الوظائف
jobstores = {
    'default': SQLAlchemyJobStore(url=app.config['SQLALCHEMY_DATABASE_URI'])
}

executors = {
    'default': {'type': 'threadpool', 'max_workers': 20}
}

# 🛑🛑 الحل النهائي: تمرير المنطقة الزمنية كسلسلة نصية بسيطة فقط 🛑🛑
# هذا يتجاوز مشاكل zoneinfo/pytz المعقدة في Termux
scheduler = BackgroundScheduler(
    jobstores=jobstores,
    executors=executors,
    timezone='Asia/Jerusalem' # <=== سلسلة نصية بسيطة
)

# **********************************************
# 4. النماذج (Database Models)
# **********************************************

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False) 

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    qr_code_path = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(50), default='Confirmed')

# **********************************************
# 5. وظائف المجدول (Scheduler Jobs)
# **********************************************

def check_reservations_status():
    """وظيفة مجدولة لتحديث حالة الحجوزات المنتهية."""
    print("Running scheduled job to check expired reservations...")
    
    # يجب استخدام pytz هنا للمقارنة الآمنة في الكود
    tz = timezone('Asia/Jerusalem')
    now = datetime.now(tz)
    
    with app.app_context():
        # المقارنة في SQL (بدون معلومات المنطقة الزمنية)
        reservations_to_expire = Reservation.query.filter(
            Reservation.end_time < now.replace(tzinfo=None), 
            Reservation.status == 'Confirmed'
        ).all()

        for res in reservations_to_expire:
            res.status = 'Expired'
            print(f"Reservation ID {res.id} expired.")
        
        db.session.commit()

# **********************************************
# 6. تهيئة قاعدة البيانات وإضافة الوظيفة المجدولة
# **********************************************

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def init_db_and_scheduler():
    with app.app_context():
        # إنشاء قاعدة البيانات والجداول
        db.create_all()
        print("Database created/checked.")

        # إضافة مستخدم مشرف افتراضي
        if User.query.filter_by(username='admin').first() is None:
            admin_user = User(username='admin', password='123', role='admin')
            db.session.add(admin_user)
            db.session.commit()
            print("Default admin user created (Username: admin, Password: 123).")

        # إضافة الوظيفة المجدولة
        if not scheduler.get_job('status_check'):
             scheduler.add_job(
                 id='status_check', 
                 func=check_reservations_status, 
                 trigger='interval', 
                 seconds=60, 
                 replace_existing=True
             )
             print("Job 'status_check' added.")
        
        # بدء المجدول
        if not scheduler.running:
             scheduler.start()
             print("Scheduler started successfully.")

init_db_and_scheduler()

# **********************************************
# 7. المسارات (Routes)
# **********************************************

@app.route('/')
def index():
    if current_user.is_authenticated:
        # إذا كان index.html في مجلد static
        return app.send_static_file('index.html') 
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.password == password: 
            login_user(user)
            return jsonify({'success': True, 'redirect_url': url_for('index')})
        else:
            return jsonify({'success': False, 'message': 'اسم المستخدم أو كلمة المرور غير صحيحة.'})
    
    return app.send_static_file('index.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/reserve', methods=['POST'])
@login_required
def reserve():
    if current_user.role != 'student':
        return jsonify({'success': False, 'message': 'غير مصرح لك بالحجز.'}), 403

    data = request.get_json()
    try:
        start_time_str = data.get('start_time')
        end_time_str = data.get('end_time')

        time_format = "%Y-%m-%dT%H:%M:%S"
        start_time = datetime.strptime(start_time_str, time_format)
        end_time = datetime.strptime(end_time_str, time_format)

        with app.app_context():
            new_reservation = Reservation(
                user_id=current_user.id,
                start_time=start_time,
                end_time=end_time
            )
            db.session.add(new_reservation)
            db.session.commit()

            qr_data = f"Reservation ID: {new_reservation.id}, User: {current_user.username}, Time: {start_time}"
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill='black', back_color='white')
            
            qr_dir = os.path.join(BASE_DIR, 'static', 'qr_codes')
            os.makedirs(qr_dir, exist_ok=True)
            
            qr_filename = f'qr_{new_reservation.id}.png'
            qr_path = os.path.join(qr_dir, qr_filename)
            img.save(qr_path)

            new_reservation.qr_code_path = os.path.join('static', 'qr_codes', qr_filename)
            db.session.commit()

            return jsonify({'success': True, 'message': 'تم الحجز بنجاح!'})

    except Exception as e:
        print(f"Error during reservation: {e}")
        with app.app_context():
            db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ أثناء الحجز: {str(e)}'}), 500


@app.route('/reservations', methods=['GET'])
@login_required
def get_reservations():
    with app.app_context():
        if current_user.role == 'admin':
            reservations = Reservation.query.all()
        else:
            reservations = Reservation.query.filter_by(user_id=current_user.id).all()
            
        output = []
        for res in reservations:
            user = User.query.get(res.user_id)
            output.append({
                'id': res.id,
                'username': user.username,
                'start_time': res.start_time.isoformat(),
                'end_time': res.end_time.isoformat(),
                'status': res.status,
                'qr_code_url': url_for('static', filename=os.path.join('qr_codes', f'qr_{res.id}.png')) if res.qr_code_path else None
            })
        return jsonify(output)


if __name__ == '__main__':
    pass
