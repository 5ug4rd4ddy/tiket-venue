import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Inisialisasi DB di global scope
db = SQLAlchemy()

def create_app(test_config=None):
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'dev_key_rahasia'
    
    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    if test_config is None:
        # Use absolute path for database in instance folder
        db_path = os.path.join(app.instance_path, 'wahana.db')
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    else:
        app.config.update(test_config)

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Konfigurasi Upload Folder
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static/uploads')
    
    # Pastikan folder upload ada
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    db.init_app(app)

    # Import routes setelah app dibuat untuk menghindari circular import
    from .routes import main
    app.register_blueprint(main)

    # Context Processor untuk Site Settings
    from .models import SiteSetting
    from datetime import datetime, timedelta

    @app.template_filter('wib_format')
    def wib_format_filter(dt):
        if not dt: return ""
        # Assume dt is naive UTC
        wib_time = dt + timedelta(hours=7)
        return wib_time.strftime('%d %b %Y, %H:%M') + " WIB"

    @app.template_filter('date_with_day')
    def date_with_day_filter(date_str):
        if not date_str: return ""
        try:
            # Parse 'YYYY-MM-DD'
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            # Indonesian day names
            days = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
            months = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember']
            day_name = days[dt.weekday()]
            month_name = months[dt.month - 1]
            return f"{day_name}, {dt.day} {month_name} {dt.year}"
        except ValueError:
            return date_str

    @app.context_processor
    def inject_site_settings():
        settings = SiteSetting.query.first()
        if not settings:
            # Create default if not exists
            settings = SiteSetting()
            # We don't commit here to avoid side effects in context processor,
            # but usually it's better to ensure it exists on app startup.
            # For simplicity, we just return the default object (not saved to DB yet)
            # or we can handle creation in a separate function.
        return dict(site=settings)

    with app.app_context():
        db.create_all() # Buat tabel jika belum ada
        
        # Ensure default settings exist
        if not SiteSetting.query.first():
            db.session.add(SiteSetting())
            db.session.commit()

    return app
