from . import db
from datetime import datetime, timedelta

class Ticket(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    price_adult = db.Column(db.Integer, nullable=True, default=0)
    price_child = db.Column(db.Integer, nullable=True, default=0)
    price_umum = db.Column(db.Integer, nullable=True, default=0)
    slug = db.Column(db.String(50), unique=True)
    category = db.Column(db.String(20), default='personal') # personal, group
    is_active = db.Column(db.Boolean, default=True)
    allow_wristband = db.Column(db.Boolean, default=False)
    allow_gate = db.Column(db.Boolean, default=False)
    
    # Dynamic Pricing
    # Regular is the base price (price_adult / price_child)
    price_adult_weekend = db.Column(db.Integer, nullable=True)
    price_child_weekend = db.Column(db.Integer, nullable=True)
    price_umum_weekend = db.Column(db.Integer, nullable=True)
    price_adult_highseason = db.Column(db.Integer, nullable=True)
    price_child_highseason = db.Column(db.Integer, nullable=True)
    price_umum_highseason = db.Column(db.Integer, nullable=True)
    # Group Pricing
    price_group_adult = db.Column(db.Integer, nullable=True)
    price_group_child = db.Column(db.Integer, nullable=True)
    price_group_umum = db.Column(db.Integer, nullable=True)
    
    # Reseller Pricing
    price_reseller_adult = db.Column(db.Integer, nullable=True)
    price_reseller_child = db.Column(db.Integer, nullable=True)
    price_reseller_umum = db.Column(db.Integer, nullable=True)

    def get_price(self, date_type, variant, role='admin'):
        """
        Get price based on date_type (regular, weekend, high_season) and variant (adult, child, umum).
        Reseller pricing overrides everything if role is reseller.
        """
        if role == 'reseller':
            if variant == 'adult':
                return self.price_reseller_adult if self.price_reseller_adult is not None else (self.price_adult or 0)
            elif variant == 'child':
                return self.price_reseller_child if self.price_reseller_child is not None else (self.price_child or 0)
            else: # umum
                return self.price_reseller_umum if self.price_reseller_umum is not None else (self.price_umum or 0)

        if variant == 'adult':
            base = self.price_adult or 0
            weekend = self.price_adult_weekend
            high = self.price_adult_highseason
        elif variant == 'child':
            base = self.price_child or 0
            weekend = self.price_child_weekend
            high = self.price_child_highseason
        else: # umum
            base = self.price_umum or 0
            weekend = self.price_umum_weekend
            high = self.price_umum_highseason

        if date_type == 'high_season':
            return high if high is not None else (weekend if weekend is not None else base)
        elif date_type == 'weekend':
            return weekend if weekend is not None else base
        else:
            return base

class Addon(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    price = db.Column(db.Integer, nullable=False)
    price_reseller = db.Column(db.Integer, nullable=True) # Price for resellers
    slug = db.Column(db.String(50), unique=True)
    category = db.Column(db.String(50), default='personal') # comma separated categories
    is_active = db.Column(db.Boolean, default=True)

    def get_price(self, role='admin'):
        if role == 'reseller' and self.price_reseller is not None:
            return self.price_reseller
        return self.price

class SpecialDate(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    description = db.Column(db.String(200))
    # type: 'closed' (tutup total) or 'high_season' (harga tuslah/peak)
    type = db.Column(db.String(20), default='closed') 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Order(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False) # UUID4
    invoice_number = db.Column(db.String(50), unique=True) # INV-YYYYMMDD-XXXX
    visit_date = db.Column(db.String(20))
    visit_type = db.Column(db.String(20))
    total_price = db.Column(db.Integer)
    details = db.Column(db.Text) # Menyimpan JSON string detail item
    
    # Customer Info
    customer_name = db.Column(db.String(100))
    customer_email = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    customer_domicile = db.Column(db.String(100))
    
    # Payment Info
    payment_method = db.Column(db.String(20)) # qris, va_bca, card
    payment_status = db.Column(db.String(20), default='pending') # pending, paid, failed
    xendit_invoice_id = db.Column(db.String(100))
    xendit_invoice_url = db.Column(db.String(255))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    payment_due_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24))
    
    # Promo Info
    promo_code = db.Column(db.String(20))
    discount_amount = db.Column(db.Integer, default=0)

    # Reseller tracking
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', backref=db.backref('orders', lazy=True))

    # Operator Checkin Info
    wristband_at = db.Column(db.DateTime)
    checkin_at = db.Column(db.DateTime)
    checkin_gate = db.Column(db.String(50))

class Gate(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)

class PromoCode(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    discount_type = db.Column(db.String(10), default='fixed') # fixed, percent
    discount_value = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SiteSetting(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    park_name = db.Column(db.String(100), default="Taman Hiburan Ceria")
    park_info = db.Column(db.String(200), default="Jalan Bahagia 123 • +62 812-3456-7890")
    opening_hours = db.Column(db.String(100), default="Buka 09:00 - 18:00")
    logo_url = db.Column(db.String(200), default="https://via.placeholder.com/64")
    hero_image_url = db.Column(db.String(200), default="https://via.placeholder.com/1200x400")
    min_group_order = db.Column(db.Integer, default=10)
    allow_wristband = db.Column(db.Boolean, default=False)
    allow_gate = db.Column(db.Boolean, default=False)
    
    # Email Settings
    email_provider = db.Column(db.String(20), default='smtp') # smtp, postal, brevo
    smtp_host = db.Column(db.String(100))
    smtp_port = db.Column(db.Integer, default=587)
    smtp_user = db.Column(db.String(100))
    smtp_password = db.Column(db.String(100))
    postal_server_key = db.Column(db.String(100))
    brevo_api_key = db.Column(db.String(100))
    email_from_address = db.Column(db.String(100), default='noreply@example.com')
    email_from_name = db.Column(db.String(100), default='Tiket Wahana')
    
    # Payment Settings
    payment_timeout_minutes = db.Column(db.Integer, default=60)
    xendit_secret_key = db.Column(db.String(200))
    xendit_webhook_token = db.Column(db.String(100))
    
    # Operational Settings
    # Comma separated integers: 0=Mon, 1=Tue, ..., 6=Sun
    weekly_closed_days = db.Column(db.String(20), default='') 
    
    # Reseller Settings
    min_reseller_deposit = db.Column(db.Integer, default=100000000)
    min_reseller_deposit_renewal = db.Column(db.Integer, default=50000000)
    reseller_deposit_duration_days = db.Column(db.Integer, default=365)

# class PaymentMethod(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     bank_name = db.Column(db.String(50), nullable=False)
#     account_number = db.Column(db.String(50), nullable=False)
#     account_holder = db.Column(db.String(100), nullable=False)
#     is_active = db.Column(db.Boolean, default=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=True)
    email = db.Column(db.String(100), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100))
    role = db.Column(db.String(20), default='admin')
    is_active = db.Column(db.Boolean, default=True)
    
    # Reseller specific data
    agency_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    deposit_balance = db.Column(db.Integer, default=0)
    deposit_expires_at = db.Column(db.DateTime)

class DepositTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # Positive for top-up, negative for purchase
    transaction_type = db.Column(db.String(20), nullable=False)  # 'topup', 'purchase', 'adjustment'
    description = db.Column(db.String(200))
    
    # Xendit integration for top-ups
    external_id = db.Column(db.String(100), unique=True) # Unique ID for Xendit
    status = db.Column(db.String(20), default='completed') # 'pending', 'completed', 'failed', 'expired'
    xendit_invoice_id = db.Column(db.String(100))
    xendit_invoice_url = db.Column(db.String(255))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('deposit_transactions', lazy=True))

class Partner(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(100))
    fee_percentage = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
