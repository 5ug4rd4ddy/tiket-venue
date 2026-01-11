from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, flash, current_app
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
import uuid
import random
import string
from . import db
from .models import Ticket, Addon, Order, SiteSetting, User, PromoCode, Gate, Partner, SpecialDate, DepositTransaction
import csv
from io import StringIO
from flask import make_response
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from .utils import send_invoice_email, send_eticket_email, generate_random_password, send_reseller_welcome_email, send_expired_email
from .xendit_service import XenditService
import threading
from io import BytesIO
from flask import send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

main = Blueprint('main', __name__)

def send_email_with_context(app, func, order_id, base_url):
    with app.test_request_context(base_url=base_url):
        from .models import Order
        order = Order.query.get(order_id)
        if order:
            func(order)
        else:
            print(f"Order {order_id} not found for email thread")

# --- PROMO CODE ROUTES ---

@main.route('/api/check-promo', methods=['POST'])
def check_promo():
    data = request.json
    code = data.get('code')
    total = data.get('total', 0)
    
    if not code:
        return jsonify({'status': 'error', 'message': 'Kode promo harus diisi'}), 400
        
    promo = PromoCode.query.filter_by(code=code, is_active=True).first()
    
    if not promo:
        return jsonify({'status': 'error', 'message': 'Kode promo tidak valid'}), 404
        
    # Calculate discount
    discount = 0
    if promo.discount_type == 'fixed':
        discount = promo.discount_value
    elif promo.discount_type == 'percent':
        discount = int(total * (promo.discount_value / 100))
        
    # Ensure discount doesn't exceed total
    if discount > total:
        discount = total
        
    return jsonify({
        'status': 'success',
        'code': promo.code,
        'discount_amount': discount,
        'final_total': total - discount
    })

@main.route('/dashboard/promos')
def admin_promos():
    if not session.get('logged_in'): return redirect(url_for('main.login'))
    promos = PromoCode.query.order_by(PromoCode.created_at.desc()).all()
    return render_template('admin/promos.html', promos=promos)

@main.route('/promo/add', methods=['POST'])
def add_promo():
    if not session.get('logged_in'): return redirect(url_for('main.login'))
    code = request.form.get('code')
    discount_type = request.form.get('discount_type')
    discount_value = int(request.form.get('discount_value'))
    is_active = request.form.get('is_active') == 'on'
    
    if PromoCode.query.filter_by(code=code).first():
        flash('Kode promo sudah ada', 'error')
        return redirect(url_for('main.admin_promos'))
        
    new_promo = PromoCode(code=code, discount_type=discount_type, discount_value=discount_value, is_active=is_active)
    db.session.add(new_promo)
    db.session.commit()
    return redirect(url_for('main.admin_promos'))

@main.route('/promo/delete/<int:id>', methods=['POST'])
def delete_promo(id):
    if not session.get('logged_in'): return redirect(url_for('main.login'))
    promo = PromoCode.query.get_or_404(id)
    db.session.delete(promo)
    db.session.commit()
    return redirect(url_for('main.admin_promos'))

@main.route('/dashboard/transactions/export')
def export_transactions():
    if not session.get('logged_in'): return redirect(url_for('main.login'))
    
    query = Order.query
    
    # Filters (same as view)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status = request.args.get('status')
    payment_method = request.args.get('payment_method')
    
    if start_date:
        query = query.filter(func.date(Order.created_at) >= start_date)
    if end_date:
        query = query.filter(func.date(Order.created_at) <= end_date)
    if status and status != 'all':
        query = query.filter(Order.payment_status == status)
    if payment_method and payment_method != 'all':
        query = query.filter(Order.payment_method == payment_method)
        
    orders = query.order_by(Order.created_at.desc()).all()
    
    # Generate CSV
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['No Invoice', 'Tanggal Order', 'Nama Customer', 'Email', 'Telepon', 'Total', 'Status', 'Metode Bayar', 'Kode Promo', 'Diskon'])
    
    for order in orders:
        cw.writerow([
            order.invoice_number,
            order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            order.customer_name,
            order.customer_email,
            order.customer_phone,
            order.total_price,
            order.payment_status,
            order.payment_method,
            order.promo_code or '',
            order.discount_amount or 0
        ])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=transactions.csv"
    output.headers["Content-type"] = "text/csv"
    return output


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- USER ROUTES ---
@main.route('/')
def index():
    tickets = Ticket.query.filter_by(is_active=True).all()
    addons = Addon.query.filter_by(is_active=True).all()
    
    settings = SiteSetting.query.first()
    min_group_order = settings.min_group_order if settings else 10
    
    js_prices = {}
    for t in tickets:
        js_prices[f"{t.slug}_adult"] = t.price_adult
        js_prices[f"{t.slug}_child"] = t.price_child
        js_prices[f"{t.slug}_category"] = t.category or 'personal'
        
    for a in addons:
        js_prices[a.slug] = a.price
        js_prices[f"{a.slug}_category"] = a.category or 'personal'
        
    return render_template('index.html', tickets=tickets, addons=addons, js_prices=js_prices, min_group_order=min_group_order)

def get_date_status(date_obj):
    # 1. Check Special Dates
    special = SpecialDate.query.filter_by(date=date_obj).first()
    if special:
        return special.type
    
    # 2. Check Weekly Closed Days
    settings = SiteSetting.query.first()
    if settings and settings.weekly_closed_days:
        closed_days = [int(d) for d in settings.weekly_closed_days.split(',') if d.strip()]
        if date_obj.weekday() in closed_days:
            return 'closed'
            
    # 3. Check Weekend (if not closed)
    if date_obj.weekday() >= 5: # 5=Sat, 6=Sun
        return 'weekend'
        
    return 'regular'

@main.route('/api/check-date')
def check_date():
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'status': 'error', 'message': 'Date required'}), 400
    
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid date format'}), 400
        
    status = get_date_status(date_obj)
            
    # Get prices
    tickets = Ticket.query.filter_by(is_active=True).all()
    prices = {}
    for t in tickets:
        prices[f"{t.slug}_adult"] = t.get_price(status, 'adult')
        prices[f"{t.slug}_child"] = t.get_price(status, 'child')
        
    return jsonify({
        'status': 'success',
        'date': date_str,
        'type': status,
        'prices': prices
    })

@main.route('/api/order', methods=['POST'])
def create_order():
    try:
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400

        details_parts = []
        
        # Format counts nicely
        counts = data.get('counts', {})
        ticket_details = []
        for slug, qty in counts.items():
            if qty > 0:
                ticket_details.append(f"{slug}: {qty}")
        if ticket_details:
            details_parts.append(f"Tickets: {', '.join(ticket_details)}")

        # Format addons
        addons = data.get('addons', [])
        if addons:
            details_parts.append(f"Addons: {', '.join(addons)}")

        # Group details
        if data.get('group_details'):
            gd = data.get('group_details')
            details_parts.append(f"Group: {gd.get('name')} ({gd.get('size')} pax)")
            
        new_order = Order(
            visit_date=data.get('date'),
            visit_type=data.get('type'),
            total_price=data.get('total'),
            details=" | ".join(details_parts)
        )
        db.session.add(new_order)
        db.session.commit()
        return jsonify({'status': 'success', 'id': new_order.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# --- CHECKOUT FLOW ---

@main.route('/checkout', methods=['POST'])
def checkout():
    order_data_raw = request.form.get('order_data')
    if not order_data_raw:
        return redirect(url_for('main.index'))
    
    try:
        data = json.loads(order_data_raw)
        
        # Re-construct summary with details from DB
        visit_date_str = data.get('date')
        try:
            visit_date = datetime.strptime(visit_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
             flash('Tanggal tidak valid', 'error')
             return redirect(url_for('main.index'))
             
        date_status = get_date_status(visit_date)
        if date_status == 'closed':
            flash('Maaf, wahana tutup pada tanggal tersebut.', 'error')
            return redirect(url_for('main.index'))

        summary = {
            'date': visit_date_str,
            'type': data.get('type'),
            'group_details': data.get('group_details'),
            'order_items': [],
            'addons': [],
            'total': 0
        }
        
        # Process Tickets
        # Use explicit list conversion to avoid any iterable issues
        all_tickets = Ticket.query.all()
        tickets_map = {t.slug: t for t in all_tickets}
        
        counts = data.get('counts', {})
        if not isinstance(counts, dict):
            counts = {}
            
        for key, qty in counts.items():
            if qty > 0:
                # key format: slug_adult or slug_child
                if key.endswith('_adult'):
                    slug = key[:-6]
                    variant = 'adult'
                elif key.endswith('_child'):
                    slug = key[:-6]
                    variant = 'child'
                elif key.endswith('_umum'):
                    slug = key[:-5]
                    variant = 'umum'
                else:
                    continue
                
                ticket = tickets_map.get(slug)
                if ticket:
                    role = session.get('user_role', 'guest')
                    price = ticket.get_price(date_status, variant, role=role)
                    
                    variant_name = 'Dewasa' if variant == 'adult' else ('Anak' if variant == 'child' else 'Umum')
                    name = f"{ticket.name} ({variant_name})"
                    subtotal = price * qty
                    
                    summary['order_items'].append({
                        'name': name,
                        'qty': qty,
                        'price': price,
                        'subtotal': subtotal,
                        'category': ticket.category or 'personal'
                    })
                    summary['total'] += subtotal

        # Process Addons
        all_addons = Addon.query.all()
        addons_map = {a.slug: a for a in all_addons}
        
        selected_addons = data.get('addons', [])
        if not isinstance(selected_addons, list):
            selected_addons = []
            
        role = session.get('user_role', 'guest')
        for slug in selected_addons:
            addon = addons_map.get(slug)
            if addon:
                price = addon.get_price(role=role)
                summary['addons'].append({
                    'name': addon.name,
                    'price': price,
                    'category': addon.category or 'personal'
                })
                summary['total'] += price

        # Store in session for the next step
        session['checkout_summary'] = summary
        
        # Load regions data for autocomplete
        cities_list = []
        try:
            regions_path = os.path.join(current_app.root_path, '..', 'instance', 'regions.json')
            if os.path.exists(regions_path):
                with open(regions_path, 'r', encoding='utf-8') as f:
                    regions = json.load(f)
                    for r in regions:
                        if 'kota' in r and isinstance(r['kota'], list):
                            cities_list.extend(r['kota'])
            cities_list.sort()
        except Exception as e:
            print(f"Error loading regions: {e}")

        user = None
        if session.get('logged_in'):
            user = User.query.get(session.get('user_id'))
            if user:
                session['deposit_balance'] = user.deposit_balance # Keep session synced

        return render_template('checkout.html', summary=summary, cities=cities_list, user=user)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error parsing order data: {e}")
        flash(f'Terjadi kesalahan: {str(e)}', 'error')
        return redirect(url_for('main.index'))

def generate_ticket_code():
    """Generates a ticket code in format TIX-YYYYMMDD-XXXXXX"""
    date_str = datetime.now().strftime('%Y%m%d')
    chars = string.ascii_uppercase + string.digits
    random_str = ''.join(random.choices(chars, k=6))
    return f"TIX-{date_str}-{random_str}"

@main.route('/api/process-payment', methods=['POST'])
def process_payment():
    try:
        summary = session.get('checkout_summary')
        if not summary:
            return jsonify({'status': 'error', 'message': 'Session expired. Silakan ulangi pemesanan.'}), 400
            
        data = request.json
        customer = data.get('customer', {})
        payment_method = data.get('payment_method')
        
        # Promo Code
        promo_code = data.get('promo_code')
        discount_amount = data.get('discount_amount', 0)
        
        # Partner Discount Logic
        customer_phone = customer.get('phone')
        partner_discount = 0
        partner_name = None
        
        if customer_phone:
             partner = Partner.query.filter_by(phone=customer_phone, is_active=True).first()
             if partner:
                 group_subtotal = 0
                 has_group_items = False
                 for item in summary.get('order_items', []):
                     if item.get('category') == 'group':
                         has_group_items = True
                         group_subtotal += item.get('subtotal', 0)
                 
                 for item in summary.get('addons', []):
                     if item.get('category') == 'group':
                         has_group_items = True
                         group_subtotal += item.get('price', 0)

                 if has_group_items and group_subtotal > 0:
                     partner_discount = int(group_subtotal * (partner.fee_percentage / 100))
                     partner_name = partner.name

        total_discount = discount_amount + partner_discount
        final_total = summary['total'] - total_discount
        if final_total < 0: final_total = 0
        
        # Group Details Priority: Request Payload > Session Summary
        group_details = data.get('group_details')
        if not group_details or not group_details.get('name'):
            group_details = summary.get('group_details')

        # Create details JSON
        details_obj = {
            'items': summary['order_items'],
            'addons': summary['addons'],
            'group': group_details,
            'promo': {
                'code': promo_code,
                'discount': discount_amount
            } if promo_code else None,
            'partner': {
                'name': partner_name,
                'discount': partner_discount
            } if partner_discount > 0 else None
        }
        
        # Generate Invoice Number: INV-YYYYMMDD-XXXX
        today_str = datetime.now().strftime('%Y%m%d')
        # Count orders for today to generate sequence
        # We use a pattern matching for the invoice number for today
        pattern = f"INV-{today_str}-%"
        today_count = Order.query.filter(Order.invoice_number.like(pattern)).count()
        sequence = f"{today_count + 1:04d}"
        invoice_number = f"INV-{today_str}-{sequence}"
        
        # Generate Unique Ticket Code (UUID replacement)
        while True:
            ticket_code = generate_ticket_code()
            if not Order.query.filter_by(uuid=ticket_code).first():
                break
        
        # Create Order
        
        # Calculate Expiration Time
        settings = SiteSetting.query.first()
        timeout_minutes = settings.payment_timeout_minutes if settings else 60
        expires_at = datetime.utcnow() + timedelta(minutes=timeout_minutes)

        new_order = Order(
            uuid=ticket_code,
            invoice_number=invoice_number,
            visit_date=summary['date'],
            visit_type=summary['type'],
            total_price=final_total, 
            details=json.dumps(details_obj),
            
            customer_name=customer.get('name'),
            customer_email=customer.get('email'),
            customer_phone=customer.get('phone'),
            customer_domicile=customer.get('domicile'),
            
            payment_method=payment_method,
            payment_status='paid' if payment_method == 'deposit' else 'pending',
            
            promo_code=promo_code,
            discount_amount=total_discount,
            
            expires_at=expires_at,
            user_id=session.get('user_id') if session.get('user_role') == 'reseller' else None
        )
        
        # IF DEPOSIT, REDUCE SALDO
        if payment_method == 'deposit':
            user = User.query.get(session.get('user_id'))
            if not user or user.deposit_balance < final_total:
                 return jsonify({'status': 'error', 'message': 'Saldo deposit tidak mencukupi'}), 400
            
            user.deposit_balance -= final_total
            
            # Record Purchase Transaction
            purchase_tx = DepositTransaction(
                user_id=user.id,
                amount=-final_total,
                transaction_type='purchase',
                description=f"Pembelian Tiket: {invoice_number}",
                status='completed'
            )
            db.session.add(purchase_tx)
            # Update session balance for UI
            session['deposit_balance'] = user.deposit_balance

        db.session.add(new_order)
        db.session.commit()

        # Create Xendit Invoice if not Cash and not Deposit
        xendit_url = None
        if payment_method not in ['cash', 'deposit']:
            try:
                xendit_service = XenditService()
                if xendit_service.secret_key:
                    success_url = f"{request.url_root}payment/{ticket_code}"
                    failure_url = f"{request.url_root}payment/{ticket_code}"
                    
                    # Map local payment method to Xendit payment_methods
                    xendit_methods = None
                    if payment_method == 'qris':
                        xendit_methods = ["QRIS"]
                    elif payment_method in ['va_bca', 'va_mandiri', 'va_bni']:
                        xendit_methods = ["VIRTUAL_ACCOUNT"]
                    elif payment_method in ['ovo', 'shopeepay', 'linkaja']:
                        xendit_methods = ["EWALLET"]
                    elif payment_method == 'card':
                        xendit_methods = ["CREDIT_CARD"]
                    
                    xendit_invoice = xendit_service.create_invoice(new_order, success_url, failure_url, xendit_methods)
                    xendit_url = xendit_invoice.invoice_url
                    new_order.xendit_invoice_id = xendit_invoice.id
                    new_order.xendit_invoice_url = xendit_invoice.invoice_url
                    db.session.commit()
            except Exception as xe:
                print(f"Xendit Error: {xe}")
                # We continue to normal flow as fallback, or the frontend can handle the absence of xendit_url
        
        # Send Email (Async)
        try:
            app = current_app._get_current_object()
            base_url = request.url_root
            if payment_method == 'deposit':
                 # Reseller instant pay - Send E-Ticket directly
                 threading.Thread(target=send_email_with_context, args=(app, send_eticket_email, new_order.id, base_url)).start()
            else:
                 # Regular - Send Invoice
                 threading.Thread(target=send_email_with_context, args=(app, send_invoice_email, new_order.id, base_url)).start()
        except Exception as e:
            print(f"Failed to start email thread: {e}")
        
        # Clear session
        session.pop('checkout_summary', None)
        
        return jsonify({
            'status': 'success', 
            'order_id': new_order.id, 
            'order_uuid': new_order.uuid,
            'xendit_url': xendit_url
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Payment Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main.route('/webhook/xendit', methods=['POST'])
def xendit_webhook():
    # Verify Callback Token
    settings = SiteSetting.query.first()
    expected_token = settings.xendit_webhook_token if settings and settings.xendit_webhook_token else os.getenv('XENDIT_WEBHOOK_TOKEN')
    
    # Xendit sends x-callback-token header
    callback_token = request.headers.get('x-callback-token')
    
    if expected_token and callback_token != expected_token:
        return jsonify({'status': 'error', 'message': 'Invalid callback token'}), 401
        
    data = request.json
    if not data:
        return jsonify({'status': 'error', 'message': 'No data'}), 400
        
    invoice_id = data.get('external_id') # This could be invoice_number (Order) or external_id (DepositTransaction)
    status = data.get('status') # PAID, EXPIRED, SETTLED
    
    # Try finding an Order first
    order = Order.query.filter_by(invoice_number=invoice_id).first()
    if order:
        if status in ['PAID', 'SETTLED']:
            if order.payment_status != 'paid':
                order.payment_status = 'paid'
                db.session.commit()
                
                # Send E-Ticket Email (Async)
                try:
                    app = current_app._get_current_object()
                    base_url = request.url_root
                    threading.Thread(target=send_email_with_context, args=(app, send_eticket_email, order.id, base_url)).start()
                except Exception as e:
                    print(f"Failed to start eticket email thread: {e}")
        elif status == 'EXPIRED':
            order.payment_status = 'expired'
            db.session.commit()
    else:
        # If not order, check for DepositTransaction
        tx = DepositTransaction.query.filter_by(external_id=invoice_id).first()
        if tx:
            if status in ['PAID', 'SETTLED']:
                if tx.status != 'completed':
                    tx.status = 'completed'
                    
                    # Update user balance
                    user = User.query.get(tx.user_id)
                    user.deposit_balance = (user.deposit_balance or 0) + tx.amount
                    
                    # Extend expiration
                    settings = SiteSetting.query.first()
                    duration = settings.reseller_deposit_duration_days if settings else 365
                    user.deposit_expires_at = datetime.utcnow() + timedelta(days=duration)
                    
                    db.session.commit()
            elif status == 'EXPIRED':
                tx.status = 'expired'
                db.session.commit()
        else:
            return jsonify({'status': 'error', 'message': 'Transaction not found'}), 404
        
    return jsonify({'status': 'success'})

@main.route('/api/pay-dummy/<int:order_id>', methods=['POST'])
def pay_dummy(order_id):
    try:
        order = Order.query.get_or_404(order_id)
        order.payment_status = 'paid'
        db.session.commit()
        
        # Send E-Ticket Email (Async)
        try:
            app = current_app._get_current_object()
            base_url = request.url_root
            threading.Thread(target=send_email_with_context, args=(app, send_eticket_email, order.id, base_url)).start()
        except Exception as e:
            print(f"Failed to start eticket email thread: {e}")
            
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main.route('/payment/<uuid>')
def payment_page(uuid):
    order = Order.query.filter_by(uuid=uuid).first_or_404()
    
    # Check for expiration if pending
    is_expired = False
    if order.payment_status == 'pending' and order.expires_at:
        if datetime.utcnow() > order.expires_at:
            order.payment_status = 'expired'
            db.session.commit()
            is_expired = True
            
            # Send Expired Email (Async)
            try:
                app = current_app._get_current_object()
                base_url = request.url_root
                threading.Thread(target=send_email_with_context, args=(app, send_expired_email, order.id, base_url)).start()
            except Exception as e:
                print(f"Failed to start expired email thread: {e}")

    elif order.payment_status == 'expired':
        is_expired = True
    
    # Parse details back to object if needed, or pass raw
    # We might want to pass it as object to template
    try:
        order_details = json.loads(order.details)
    except:
        order_details = {}
        
    return render_template('payment.html', order=order, details=order_details, is_expired=is_expired)

# --- ADMIN AUTH ---
@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Fallback/Init for first run if no users exist
        if User.query.count() == 0:
            if username == 'admin' and password == 'admin':
                # Create default admin
                hashed = generate_password_hash('admin')
                new_user = User(username='admin', password=hashed, name='Administrator', role='admin')
                db.session.add(new_user)
                db.session.commit()
                session['logged_in'] = True
                session['user_id'] = new_user.id
                session['user_name'] = new_user.name
                session['user_role'] = new_user.role
                return redirect(url_for('main.dashboard'))

        user = User.query.filter(or_(
            User.username == username,
            User.email == username,
            User.phone == username
        )).first()
        if user and check_password_hash(user.password, password):
            if not user.is_active:
                flash('Akun dinonaktifkan', 'error')
                return render_template('login.html')
            
            session['logged_in'] = True
            session['user_id'] = user.id
            session['user_name'] = user.name
            session['user_role'] = user.role
            
            if user.role == 'operator':
                return redirect(url_for('main.operator_dashboard'))
            
            if user.role == 'reseller':
                return redirect(url_for('main.reseller_dashboard'))
                
            return redirect(url_for('main.dashboard'))
            
        flash('Username atau password salah', 'error')
    return render_template('login.html')

@main.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('user_role', None)
    return redirect(url_for('main.login'))

@main.route('/reseller/topup', methods=['GET', 'POST'])
def reseller_topup():
    if not session.get('logged_in') or session.get('user_role') != 'reseller':
        return redirect(url_for('main.login'))
    
    user = User.query.get(session.get('user_id'))
    settings = SiteSetting.query.first()
    
    # Check if user has ever had a deposit (renewal vs initial)
    has_existing_deposit = user.deposit_balance is not None and user.deposit_balance > 0
    has_deposit_history = DepositTransaction.query.filter_by(user_id=user.id, transaction_type='topup', status='completed').first() is not None
    
    # Use renewal minimum if user has deposit history, otherwise use initial minimum
    if has_deposit_history or has_existing_deposit:
        min_topup = settings.min_reseller_deposit_renewal if settings and settings.min_reseller_deposit_renewal else 50000000
    else:
        min_topup = settings.min_reseller_deposit if settings else 100000000
    
    if request.method == 'POST':
        amount = int(request.form.get('amount', 0))
        if amount < min_topup:
            flash(f'Minimal top-up adalah Rp {min_topup:,}', 'error')
            return redirect(url_for('main.reseller_topup'))
        
        # Create DepositTransaction record
        external_id = f"TOPUP-{user.id}-{int(datetime.utcnow().timestamp())}"
        new_tx = DepositTransaction(
            user_id=user.id,
            amount=amount,
            transaction_type='topup',
            description=f"Top-up Deposit via Xendit",
            external_id=external_id,
            status='pending'
        )
        db.session.add(new_tx)
        db.session.flush() # Get ID
        
        # Create Xendit Invoice
        try:
            xendit_service = XenditService()
            success_url = url_for('main.reseller_dashboard', _external=True)
            failure_url = url_for('main.reseller_topup', _external=True)
            
            xendit_invoice = xendit_service.create_invoice(new_tx, success_url, failure_url)
            new_tx.xendit_invoice_id = xendit_invoice.id
            new_tx.xendit_invoice_url = xendit_invoice.invoice_url
            db.session.commit()
            
            return redirect(xendit_invoice.invoice_url)
        except Exception as e:
            db.session.rollback()
            flash(f'Gagal membuat invoice pembayaran: {str(e)}', 'error')
            return redirect(url_for('main.reseller_topup'))

    return render_template('reseller/topup.html', user=user, min_topup=min_topup)

@main.route('/reseller/dashboard')
def reseller_dashboard():
    if not session.get('logged_in') or session.get('user_role') != 'reseller':
        return redirect(url_for('main.login'))
        
    user = User.query.get(session.get('user_id'))
    orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
    return render_template('reseller/dashboard.html', orders=orders, current_user=user)

@main.route('/reseller/history')
def reseller_history():
    if not session.get('logged_in') or session.get('user_role') != 'reseller':
        return redirect(url_for('main.login'))
        
    user = User.query.get(session.get('user_id'))
    orders = Order.query.filter_by(user_id=user.id).all()
    deposits = DepositTransaction.query.filter_by(user_id=user.id).all()
    
    # Combine and standardize for display
    transactions = []
    
    for o in orders:
        # Avoid attribute conflict if already set
        o.display_type = 'tiket'
        o.display_date = o.created_at
        o.display_amount = o.total_price
        o.display_status = o.payment_status
        o.display_desc = f"Order #{o.invoice_number}"
        o.display_id = o.uuid # used for link
        transactions.append(o)
        
    for d in deposits:
        d.display_type = 'deposit'
        d.display_date = d.created_at
        d.display_amount = d.amount
        d.display_status = d.status
        d.display_desc = d.description or d.transaction_type.capitalize()
        d.display_id = d.id # not really used for link same way
        transactions.append(d)
        
    # Sort by date desc
    transactions.sort(key=lambda x: x.display_date, reverse=True)
    
    return render_template('reseller/history.html', orders=transactions)

@main.route('/reseller/deposit-history')
def reseller_deposit_history():
    if not session.get('logged_in') or session.get('user_role') != 'reseller':
        return redirect(url_for('main.login'))
        
    user = User.query.get(session.get('user_id'))
    deposits = DepositTransaction.query.filter_by(user_id=user.id).order_by(DepositTransaction.created_at.desc()).all()
    return render_template('reseller/deposit_history.html', deposits=deposits)

@main.route('/reseller/order')
def reseller_order():
    if not session.get('logged_in') or session.get('user_role') != 'reseller':
        return redirect(url_for('main.login'))
    
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('main.login'))
    
    # Check deposit expiration
    now = datetime.utcnow()
    is_expired = user.deposit_expires_at and user.deposit_expires_at < now
    
    if is_expired:
        flash('Masa aktif deposit Anda telah berakhir. Silakan lakukan top-up untuk mengaktifkan kembali.', 'error')
        return redirect(url_for('main.reseller_dashboard'))

    # Filter tickets and addons for resellers
    # Category stores comma-separated strings like "personal,reseller"
    all_tickets = Ticket.query.filter_by(is_active=True).all()
    # Show ticket if it has 'reseller' category OR has any reseller price set
    tickets = [t for t in all_tickets if 'reseller' in (t.category or '').lower().split(',') or t.price_reseller_adult or t.price_reseller_child or t.price_reseller_umum]
    
    all_addons = Addon.query.filter_by(is_active=True).all()
    addons = [a for a in all_addons if 'reseller' in (a.category or '').lower().split(',')]
    
    settings = SiteSetting.query.first()
    
    return render_template('reseller/order.html', 
                          tickets=tickets, 
                          addons=addons, 
                          user=user,
                          settings=settings)

# --- ADMIN DASHBOARD ---
@main.route('/dashboard')
def dashboard():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    # Stats
    total_revenue = db.session.query(func.sum(Order.total_price)).scalar() or 0
    total_tickets_sold = Order.query.count() # Simplification
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()
    
    today = datetime.now().date()
    # Note: created_at is datetime, so we filter by date
    today_orders = Order.query.filter(func.date(Order.created_at) == today).count()
    
    # Recent Check-ins
    recent_checkins = Order.query.filter(
        or_(Order.checkin_at.isnot(None), Order.wristband_at.isnot(None))
    ).order_by(
        func.coalesce(Order.checkin_at, Order.wristband_at).desc()
    ).limit(5).all()
    
    return render_template('admin/dashboard.html', 
                           total_revenue=total_revenue, 
                           total_orders=total_tickets_sold,
                           recent_orders=recent_orders,
                           today_orders=today_orders,
                           recent_checkins=recent_checkins)

@main.route('/dashboard/tickets')
def admin_tickets():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    tickets = Ticket.query.all()
    return render_template('admin/tickets.html', tickets=tickets)

@main.route('/dashboard/addons')
def admin_addons():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    addons = Addon.query.all()
    return render_template('admin/addons.html', addons=addons)

@main.route('/dashboard/transactions')
def admin_transactions():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    # Lazy Cleanup: Check for expired pending orders
    try:
        now = datetime.utcnow()
        expired_orders = Order.query.filter(Order.payment_status == 'pending', Order.expires_at < now).all()
        if expired_orders:
            app = current_app._get_current_object()
            base_url = request.url_root
            for order in expired_orders:
                order.payment_status = 'expired'
                # Send Email
                threading.Thread(target=send_email_with_context, args=(app, send_expired_email, order.id, base_url)).start()
            db.session.commit()
    except Exception as e:
        print(f"Lazy cleanup error: {e}")
    
    # Filters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status = request.args.get('status')
    payment_method = request.args.get('payment_method')
    tx_type = request.args.get('type', 'all')
    
    results = []
    
    # TICKET ORDERS
    if tx_type in ['all', 'personal', 'group']:
        order_query = Order.query
        if start_date:
            order_query = order_query.filter(func.date(Order.created_at) >= start_date)
        if end_date:
            order_query = order_query.filter(func.date(Order.created_at) <= end_date)
        if status and status != 'all':
            order_query = order_query.filter(Order.payment_status == status)
        if payment_method and payment_method != 'all':
            order_query = order_query.filter(Order.payment_method == payment_method)
        if tx_type in ['personal', 'group']:
            order_query = order_query.filter(Order.visit_type == tx_type)
            
        orders = order_query.order_by(Order.created_at.desc()).all()
        for o in orders:
            o.display_type = 'tiket'
            o.display_id = o.invoice_number
            o.display_customer = o.customer_name
            o.display_amount = o.total_price
            o.display_status = o.payment_status
            results.append(o)
            
    # DEPOSIT TRANSACTIONS
    if tx_type == 'deposit':
        # Only show topups and adjustments, not internal purchases (which are already in orders)
        deposit_query = DepositTransaction.query.filter(DepositTransaction.transaction_type != 'purchase')
        if start_date:
            deposit_query = deposit_query.filter(func.date(DepositTransaction.created_at) >= start_date)
        if end_date:
            deposit_query = deposit_query.filter(func.date(DepositTransaction.created_at) <= end_date)
        if status and status != 'all':
            # Map order status to deposit status
            # status can be: pending, paid, expired
            # deposit status: pending, completed, expired, failed
            mapped_status = 'completed' if status == 'paid' else status
            deposit_query = deposit_query.filter(DepositTransaction.status == mapped_status)
            
        deposits = deposit_query.order_by(DepositTransaction.created_at.desc()).all()
        for d in deposits:
            d.display_type = 'reseller'
            d.display_id = d.external_id or f"TX-{d.id}"
            d.display_customer = d.user.name if d.user else "System"
            d.display_amount = d.amount
            d.display_status = 'paid' if d.status == 'completed' else d.status
            results.append(d)
            
    # Combine and sort
    results.sort(key=lambda x: x.created_at, reverse=True)
    return render_template('admin/transactions.html', orders=results)

@main.route('/dashboard/transactions/order/<int:id>')
def admin_transaction_order_detail(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    order = Order.query.get_or_404(id)
    
    # Parse details JSON
    try:
        details = json.loads(order.details)
    except:
        details = {}
        
    # Extract group info if available
    group_info = None
    if order.visit_type == 'group':
        group_info = details.get('group_details') or details.get('group')
        
    return render_template('admin/transaction_detail.html', transaction=order, type='order', details=details, group_info=group_info)

@main.route('/dashboard/transactions/deposit/<int:id>')
def admin_transaction_deposit_detail(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    deposit = DepositTransaction.query.get_or_404(id)
    return render_template('admin/transaction_detail.html', transaction=deposit, type='deposit')

@main.route('/dashboard/transaction/<int:order_id>/update-status', methods=['POST'])
def update_transaction_status(order_id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return jsonify({'error': 'Unauthorized'}), 401
    
    order = Order.query.get_or_404(order_id)
    new_status = request.json.get('status')
    payment_method = request.json.get('payment_method')
    
    if new_status and new_status not in ['pending', 'paid', 'failed', 'expired']:
        return jsonify({'error': 'Invalid status'}), 400
        
    old_status = order.payment_status
    
    # Update Status
    if new_status:
        order.payment_status = new_status
        
    # Update Payment Method
    if payment_method:
        order.payment_method = payment_method
        
    db.session.commit()
    
    # Send E-Ticket if status changed to paid
    if old_status != 'paid' and new_status == 'paid':
        try:
            app = current_app._get_current_object()
            base_url = request.url_root
            threading.Thread(target=send_email_with_context, args=(app, send_eticket_email, order.id, base_url)).start()
        except Exception as e:
            print(f"Failed to start eticket email thread: {e}")
            
    # Send Expired Email if status changed to expired
    if old_status != 'expired' and new_status == 'expired':
        try:
            app = current_app._get_current_object()
            base_url = request.url_root
            threading.Thread(target=send_email_with_context, args=(app, send_expired_email, order.id, base_url)).start()
        except Exception as e:
            print(f"Failed to start expired email thread: {e}")
    
    return jsonify({'status': 'success', 'new_status': new_status})

@main.route('/dashboard/transaction/<int:order_id>/details')
def get_transaction_details(order_id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return jsonify({'error': 'Unauthorized'}), 401
    order = Order.query.get_or_404(order_id)
    try:
        details = json.loads(order.details)
    except:
        details = {}
    
    # Extract group details if present
    group_info = None
    if order.visit_type == 'group':
        group_info = details.get('group_details') or details.get('group')

    return jsonify({
        'invoice': order.invoice_number,
        'visit_date': order.visit_date,
        'visit_type': order.visit_type,
        'details': details,
        'group_info': group_info,
        'customer': {
            'name': order.customer_name,
            'email': order.customer_email,
            'phone': order.customer_phone,
            'domicile': order.customer_domicile
        },
        'payment': {
            'method': order.payment_method,
            'status': order.payment_status,
            'total': order.total_price,
            'discount': order.discount_amount,
            'promo_code': order.promo_code
        },
        'created_at': order.created_at.strftime('%Y-%m-%d %H:%M')
    })

@main.route('/dashboard/transaction/<int:order_id>/invoice')
def admin_download_invoice(order_id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    order = Order.query.get_or_404(order_id)
    if order.payment_status != 'paid':
        return "Invoice hanya tersedia untuk transaksi lunas", 400
        
    try:
        details = json.loads(order.details)
    except:
        details = {}
        
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []
    
    styles = getSampleStyleSheet()
    style_normal = styles["Normal"]
    style_heading = styles["Heading1"]
    style_center = ParagraphStyle(name='Center', parent=styles['Normal'], alignment=TA_CENTER)
    style_right = ParagraphStyle(name='Right', parent=styles['Normal'], alignment=TA_RIGHT)
    
    # Header
    # Try to use logo if available in settings, otherwise text
    settings = SiteSetting.query.first()
    header_text = settings.park_name if settings else "Tiket Wahana"
    
    elements.append(Paragraph(f"<b>{header_text}</b>", style_heading))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("INVOICE / BUKTI PEMBAYARAN", style_heading))
    elements.append(Spacer(1, 24))
    
    # Order Info
    data_info = [
        ["No. Invoice", f": {order.invoice_number}"],
        ["Tanggal", f": {order.created_at.strftime('%d %B %Y %H:%M')}"],
        ["Status", f": {order.payment_status.upper()}"],
        ["Pelanggan", f": {order.customer_name}"],
        ["Email", f": {order.customer_email}"],
        ["Tipe Kunjungan", f": {order.visit_type.title()}"]
    ]
    
    if order.visit_type == 'group':
        group_info = details.get('group_details') or details.get('group')
        # Ensure group_info is a dict
        if isinstance(group_info, dict):
            data_info.append(["Nama Group", f": {group_info.get('name', '-')}"])
            data_info.append(["Jumlah Peserta", f": {group_info.get('size', '-')} Pax"])
    
    t_info = Table(data_info, colWidths=[2*inch, 4*inch])
    t_info.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t_info)
    elements.append(Spacer(1, 24))
    
    # Items Table
    data_items = [["Deskripsi Item", "Qty", "Harga", "Total"]]
    
    # Tickets
    for item in details.get('items', []):
        data_items.append([
            f"Tiket - {item['name']}",
            str(item.get('qty', 0)),
            f"Rp {item.get('price', 0):,}",
            f"Rp {item.get('subtotal', 0):,}"
        ])
        
    # Addons
    for item in details.get('addons', []):
        data_items.append([
            f"Addon - {item['name']}",
            "1", # Addons in checkout summary are usually counted as 1 per list entry
            f"Rp {item.get('price', 0):,}",
            f"Rp {item.get('price', 0):,}"
        ])
        
    # Table Styling
    t_items = Table(data_items, colWidths=[3.5*inch, 1*inch, 1.5*inch, 1.5*inch])
    t_items.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(t_items)
    elements.append(Spacer(1, 12))
    
    # Totals
    data_total = []
    data_total.append(["Subtotal", f"Rp {order.total_price + order.discount_amount:,}"])
    if order.discount_amount > 0:
        data_total.append(["Diskon", f"- Rp {order.discount_amount:,}"])
    data_total.append(["TOTAL", f"Rp {order.total_price:,}"])
    
    t_total = Table(data_total, colWidths=[6*inch, 1.5*inch])
    t_total.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('LINEABOVE', (0,-1), (-1,-1), 1, colors.black),
    ]))
    elements.append(t_total)
    
    elements.append(Spacer(1, 36))
    elements.append(Paragraph("Terima kasih atas kunjungan Anda!", style_center))
    
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"Invoice_{order.invoice_number}.pdf",
        mimetype='application/pdf'
    )

@main.route('/dashboard/users')
def admin_users():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    users = User.query.all()
    return render_template('admin/users.html', users=users)

@main.route('/dashboard/resellers')
def admin_resellers():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    users = User.query.filter_by(role='reseller').all()
    return render_template('admin/users.html', users=users, active_role='reseller')

@main.route('/dashboard/reseller/add', methods=['GET', 'POST'])
def admin_add_reseller():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        agency_name = request.form.get('agency_name')
        phone = request.form.get('phone')
        address = request.form.get('address')
        is_active = request.form.get('is_active') == 'on'
        
        # Check if email or phone is already used
        if User.query.filter(or_(User.email == email, User.phone == phone)).first():
            flash('Email atau No. Telp sudah digunakan', 'error')
            return render_template('admin/reseller_form.html', user=None)
            
        # Generate random password for new reseller
        raw_password = generate_random_password()
        hashed = generate_password_hash(raw_password)
        
        new_reseller = User(
            username=None, 
            email=email,
            password=hashed, 
            name=name, 
            role='reseller', 
            is_active=is_active,
            agency_name=agency_name,
            phone=phone,
            address=address
        )
        db.session.add(new_reseller)
        db.session.commit()
        
        # Send welcome email asynchronously
        try:
            from flask import current_app
            app = current_app._get_current_object()
            url_root = request.url_root
            threading.Thread(target=send_reseller_welcome_email, args=(app, new_reseller.id, raw_password, url_root)).start()
        except Exception as e:
            print(f"Failed to start email thread: {e}")
            
        flash(f'Reseller berhasil ditambahkan. Password telah dikirim ke email {email}', 'success')
        return redirect(url_for('main.admin_resellers'))
        
    return render_template('admin/reseller_form.html', user=None)

@main.route('/dashboard/reseller/edit/<int:id>', methods=['GET', 'POST'])
def admin_edit_reseller(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    user = User.query.get_or_404(id)
    
    if request.method == 'POST':
        user.name = request.form.get('name')
        user.email = request.form.get('email')
        user.agency_name = request.form.get('agency_name')
        user.phone = request.form.get('phone')
        user.address = request.form.get('address')
        user.is_active = request.form.get('is_active') == 'on'
        
        new_pass = request.form.get('password')
        if new_pass:
            user.password = generate_password_hash(new_pass)
            
        db.session.commit()
        flash('Data reseller diperbarui', 'success')
        return redirect(url_for('main.admin_resellers'))
        
    return render_template('admin/reseller_form.html', user=user, now=datetime.utcnow())

@main.route('/dashboard/reseller/deposit/<int:id>', methods=['POST'])
def admin_reseller_deposit(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    user = User.query.get_or_404(id)
    amount = int(request.form.get('amount', 0))
    description = request.form.get('description', 'Top-up Deposit')
    
    settings = SiteSetting.query.first()
    min_deposit = settings.min_reseller_deposit if settings else 100000000
    
    if amount < min_deposit and amount > 0:
        flash(f'Minimal top-up adalah Rp {min_deposit:,}', 'error')
        return redirect(url_for('main.admin_edit_reseller', id=id))

    if amount != 0:
        user.deposit_balance = (user.deposit_balance or 0) + amount
        
        # Update expiration if top-up is positive
        if amount > 0:
            duration = settings.reseller_deposit_duration_days if settings else 365
            user.deposit_expires_at = datetime.utcnow() + timedelta(days=duration)
        
        # Record transaction
        transaction = DepositTransaction(
            user_id=user.id,
            amount=amount,
            transaction_type='topup' if amount > 0 else 'adjustment',
            description=description
        )
        db.session.add(transaction)
        db.session.commit()
        
        flash(f'Saldo deposit senilai Rp {abs(amount):,} berhasil {"ditambahkan" if amount > 0 else "dikurangi"}.', 'success')
        if amount > 0:
            flash(f'Masa aktif deposit diperpanjang hingga {user.deposit_expires_at.strftime("%d %b %Y")}.', 'info')
    
    return redirect(url_for('main.admin_edit_reseller', id=id))

@main.route('/user/add', methods=['POST'])
def add_user():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    username = request.form.get('username')
    password = request.form.get('password')
    name = request.form.get('name')
    role = request.form.get('role')
    is_active = request.form.get('is_active') == 'on'
    
    if User.query.filter_by(username=username).first():
        flash('Username sudah digunakan', 'error')
        return redirect(url_for('main.admin_users'))
        
    hashed = generate_password_hash(password)
    new_user = User(username=username, password=hashed, name=name, role=role, is_active=is_active)
    db.session.add(new_user)
    db.session.commit()
    return redirect(url_for('main.admin_users'))

@main.route('/user/edit/<int:id>', methods=['POST'])
def edit_user(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    user = User.query.get_or_404(id)
    
    user.username = request.form.get('username')
    user.name = request.form.get('name')
    user.role = request.form.get('role')
    user.is_active = request.form.get('is_active') == 'on'
    
    # Only update password if provided
    new_pass = request.form.get('password')
    if new_pass:
        user.password = generate_password_hash(new_pass)
        
    db.session.commit()
    return redirect(url_for('main.admin_users'))

@main.route('/user/delete/<int:id>', methods=['POST'])
def delete_user(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    if id == session.get('user_id'):
        flash('Tidak dapat menghapus akun sendiri', 'error')
        return redirect(url_for('main.admin_users'))
        
    user = User.query.get_or_404(id)
    is_reseller = user.role == 'reseller'
    
    db.session.delete(user)
    db.session.commit()
    
    if is_reseller:
        flash('Reseller berhasil dihapus', 'success')
        return redirect(url_for('main.admin_resellers'))
        
    flash('User berhasil dihapus', 'success')
    return redirect(url_for('main.admin_users'))

# --- PARTNER ROUTES ---

@main.route('/dashboard/partners')
def admin_partners():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    partners = Partner.query.all()
    return render_template('admin/partners.html', partners=partners)

@main.route('/partner/add', methods=['POST'])
def add_partner():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    name = request.form.get('name')
    phone = request.form.get('phone')
    email = request.form.get('email')
    fee_percentage = int(request.form.get('fee_percentage', 0))
    is_active = request.form.get('is_active') == 'on'
    
    if Partner.query.filter_by(phone=phone).first():
        flash('No Telepon sudah terdaftar', 'error')
        return redirect(url_for('main.admin_partners'))
        
    new_partner = Partner(name=name, phone=phone, email=email, fee_percentage=fee_percentage, is_active=is_active)
    db.session.add(new_partner)
    db.session.commit()
    return redirect(url_for('main.admin_partners'))

@main.route('/partner/edit/<int:id>', methods=['POST'])
def edit_partner(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    partner = Partner.query.get_or_404(id)
    
    partner.name = request.form.get('name')
    partner.phone = request.form.get('phone')
    partner.email = request.form.get('email')
    partner.fee_percentage = int(request.form.get('fee_percentage', 0))
    partner.is_active = request.form.get('is_active') == 'on'
    
    db.session.commit()
    return redirect(url_for('main.admin_partners'))

@main.route('/partner/delete/<int:id>', methods=['POST'])
def delete_partner(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    partner = Partner.query.get_or_404(id)
    db.session.delete(partner)
    db.session.commit()
    return redirect(url_for('main.admin_partners'))

@main.route('/dashboard/settings', methods=['GET', 'POST'])
def admin_settings():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    settings = SiteSetting.query.first()
    if not settings:
        settings = SiteSetting(park_name="Wahana Waterpark")
        db.session.add(settings)
        db.session.commit()
        
    if request.method == 'POST':
        settings.park_name = request.form.get('park_name')
        settings.park_info = request.form.get('park_info')
        settings.opening_hours = request.form.get('opening_hours')
        settings.min_group_order = int(request.form.get('min_group_order', 20))
        settings.allow_wristband = 'allow_wristband' in request.form
        settings.allow_gate = 'allow_gate' in request.form
        
        # Operational Days
        closed_days = request.form.getlist('weekly_closed_days') # list of strings "0", "1" etc
        settings.weekly_closed_days = ",".join(closed_days)
        
        # Email Settings
        settings.email_provider = request.form.get('email_provider')
        settings.smtp_host = request.form.get('smtp_host')
        settings.smtp_port = int(request.form.get('smtp_port', 587))
        settings.smtp_user = request.form.get('smtp_user')
        if request.form.get('smtp_password'):
            settings.smtp_password = request.form.get('smtp_password')
        settings.postal_server_key = request.form.get('postal_server_key')
        settings.brevo_api_key = request.form.get('brevo_api_key')
        settings.email_from_address = request.form.get('email_from_address')
        settings.email_from_name = request.form.get('email_from_name')
        
        # Images
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                filename = f"logo_{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                settings.logo_url = filename
                
        if 'hero_image' in request.files:
            file = request.files['hero_image']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
                filename = f"hero_{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                settings.hero_image_url = filename
                
        db.session.commit()
        flash('Pengaturan berhasil disimpan!', 'success')
        return redirect(url_for('main.admin_settings'))
        
    return render_template('admin/settings.html', settings=settings)

@main.route('/dashboard/settings/reseller', methods=['GET', 'POST'])
def admin_reseller_settings():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    settings = SiteSetting.query.first()
    if not settings:
        settings = SiteSetting()
        db.session.add(settings)
        db.session.commit()
        
    if request.method == 'POST':
        settings.min_reseller_deposit = int(request.form.get('min_reseller_deposit', 100000000))
        settings.min_reseller_deposit_renewal = int(request.form.get('min_reseller_deposit_renewal', 50000000))
        settings.reseller_deposit_duration_days = int(request.form.get('reseller_deposit_duration_days', 365))
        
        db.session.commit()
        flash('Pengaturan reseller berhasil disimpan', 'success')
        return redirect(url_for('main.admin_reseller_settings'))
        
    return render_template('admin/reseller_settings.html', settings=settings)

# --- CALENDAR MANAGEMENT ---
@main.route('/dashboard/calendar')
def admin_calendar():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    # Get all future special dates or recent past
    today = datetime.now().date()
    start_filter = today - timedelta(days=30) # Show 1 month back
    
    special_dates = SpecialDate.query.filter(SpecialDate.date >= start_filter)\
                    .order_by(SpecialDate.date.asc()).all()
                    
    return render_template('admin/calendar.html', special_dates=special_dates)

@main.route('/dashboard/calendar/add', methods=['POST'])
def add_special_date():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    date_str = request.form.get('date')
    description = request.form.get('description')
    dtype = request.form.get('type')
    
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Check existing
        existing = SpecialDate.query.filter_by(date=date_obj).first()
        if existing:
            existing.description = description
            existing.type = dtype
            flash('Tanggal khusus diperbarui!', 'success')
        else:
            new_date = SpecialDate(date=date_obj, description=description, type=dtype)
            db.session.add(new_date)
            flash('Tanggal khusus ditambahkan!', 'success')
            
        db.session.commit()
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        
    return redirect(url_for('main.admin_calendar'))

@main.route('/dashboard/calendar/delete/<int:id>')
def delete_special_date(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    sdate = SpecialDate.query.get_or_404(id)
    db.session.delete(sdate)
    db.session.commit()
    flash('Tanggal khusus dihapus.', 'success')
    return redirect(url_for('main.admin_calendar'))

@main.route('/dashboard/settings/email')
def admin_email_settings():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    return render_template('admin/email_settings.html')

@main.route('/settings/email/update', methods=['POST'])
def update_email_settings():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    settings = SiteSetting.query.first()
    if not settings:
        settings = SiteSetting()
        db.session.add(settings)
    
    settings.email_provider = request.form.get('email_provider')
    settings.email_from_address = request.form.get('email_from_address')
    settings.email_from_name = request.form.get('email_from_name')
    
    # SMTP
    settings.smtp_host = request.form.get('smtp_host')
    try:
        settings.smtp_port = int(request.form.get('smtp_port'))
    except (ValueError, TypeError):
        settings.smtp_port = 587
    settings.smtp_user = request.form.get('smtp_user')
    settings.smtp_password = request.form.get('smtp_password')
    
    # Postal
    settings.postal_server_key = request.form.get('postal_server_key')
    
    # Brevo
    settings.brevo_api_key = request.form.get('brevo_api_key')
    
    db.session.commit()
    flash('Pengaturan email berhasil disimpan', 'success')
    return redirect(url_for('main.admin_email_settings'))

@main.route('/settings/payment/update', methods=['POST'])
def update_payment_settings():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    settings = SiteSetting.query.first()
    if not settings:
        settings = SiteSetting()
        db.session.add(settings)
    
    try:
        timeout = int(request.form.get('payment_timeout_minutes', 60))
        if timeout < 1: timeout = 1
        settings.payment_timeout_minutes = timeout
    except ValueError:
        settings.payment_timeout_minutes = 60
    
    # Xendit Settings
    settings.xendit_secret_key = request.form.get('xendit_secret_key')
    settings.xendit_webhook_token = request.form.get('xendit_webhook_token')
        
    db.session.commit()
    flash('Pengaturan batas waktu pembayaran berhasil disimpan', 'success')
    return redirect(url_for('main.admin_payments'))

@main.route('/dashboard/payments')
def admin_payments():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    return render_template('admin/payments.html')

@main.route('/dashboard/gates')
def admin_gates():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    gates = Gate.query.all()
    return render_template('admin/gates.html', gates=gates)

@main.route('/gate/add', methods=['POST'])
def add_gate():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    name = request.form.get('name')
    desc = request.form.get('description')
    is_active = request.form.get('is_active') == 'on'
    
    db.session.add(Gate(name=name, description=desc, is_active=is_active))
    db.session.commit()
    return redirect(url_for('main.admin_gates'))

@main.route('/gate/edit/<int:id>', methods=['POST'])
def edit_gate(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    gate = Gate.query.get_or_404(id)
    
    gate.name = request.form.get('name')
    gate.description = request.form.get('description')
    gate.is_active = request.form.get('is_active') == 'on'
    
    db.session.commit()
    return redirect(url_for('main.admin_gates'))

@main.route('/gate/delete/<int:id>', methods=['POST'])
def delete_gate(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    gate = Gate.query.get_or_404(id)
    db.session.delete(gate)
    db.session.commit()
    return redirect(url_for('main.admin_gates'))

@main.route('/dashboard/checkins')
def admin_checkins():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    # Filters
    date_filter = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    gate_filter = request.args.get('gate')
    
    query = Order.query.filter(Order.checkin_at.isnot(None))
    
    if date_filter:
        query = query.filter(func.date(Order.checkin_at) == date_filter)
        
    if gate_filter:
        query = query.filter(Order.checkin_gate == gate_filter)
        
    checkins = query.order_by(Order.checkin_at.desc()).all()
    gates = Gate.query.all()
    
    return render_template('admin/checkins.html', checkins=checkins, gates=gates, filter_date=date_filter, filter_gate=gate_filter)

@main.route('/dashboard/wristbands')
def admin_wristbands():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    date_filter = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    query = Order.query.filter(Order.wristband_at.isnot(None))
    
    if date_filter:
        query = query.filter(func.date(Order.wristband_at) == date_filter)
        
    wristbands = query.order_by(Order.wristband_at.desc()).all()
    
    return render_template('admin/wristbands.html', wristbands=wristbands, filter_date=date_filter)

@main.route('/dashboard/reports')
def admin_reports():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    # Date Filter Defaults (Current Month)
    today = datetime.now().date()
    default_start = today.replace(day=1)
    # End date is today by default
    
    start_date_str = request.args.get('start_date', default_start.strftime('%Y-%m-%d'))
    end_date_str = request.args.get('end_date', today.strftime('%Y-%m-%d'))
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = default_start
        end_date = today
        
    # Query Paid Orders in Range
    # Adjust end_date to include the whole day
    query = Order.query.filter(
        Order.payment_status == 'paid',
        func.date(Order.created_at) >= start_date,
        func.date(Order.created_at) <= end_date
    ).order_by(Order.created_at.desc())
    
    orders = query.all()
    
    # Process Daily Report
    daily_data = {} # date -> {count: 0, total: 0}
    
    # Process Ticket Report
    ticket_data = {} # name -> {qty: 0, total: 0}
    
    # Process Addon Report (Bonus)
    addon_data = {} # name -> {qty: 0, total: 0}
    
    for order in orders:
        date_key = order.created_at.strftime('%Y-%m-%d')
        if date_key not in daily_data:
            daily_data[date_key] = {'count': 0, 'total': 0}
        
        daily_data[date_key]['count'] += 1
        daily_data[date_key]['total'] += order.total_price
        
        # Parse details
        try:
            details = json.loads(order.details)
            
            # Tickets
            items = details.get('items', []) or details.get('tickets', [])
            for item in items:
                name = item.get('name', 'Unknown')
                qty = item.get('qty', 0) or item.get('quantity', 0)
                subtotal = item.get('subtotal', 0) or item.get('total', 0)
                
                if name not in ticket_data:
                    ticket_data[name] = {'qty': 0, 'total': 0}
                ticket_data[name]['qty'] += qty
                ticket_data[name]['total'] += subtotal
                
            # Addons
            addons = details.get('addons', [])
            for item in addons:
                name = item.get('name', 'Unknown')
                qty = item.get('qty', 0) or item.get('quantity', 0)
                price = item.get('price', 0)
                # Addon items in details usually have price, need to calc total if not present
                # In checkout logic: summary['addons'] has price (unit price). 
                # But wait, checkout summary structure for addons is list of items, so qty is effectively 1 per entry?
                # Let's check checkout logic.
                # In checkout: summary['addons'].append({'name': ..., 'price': ...}) -> list of selected addons.
                # So quantity is always 1 per entry in that list.
                # But wait, if multiple addons are selected?
                # The structure in checkout is a list of objects.
                
                if name not in addon_data:
                    addon_data[name] = {'qty': 0, 'total': 0}
                addon_data[name]['qty'] += 1 # Assuming 1 per entry
                addon_data[name]['total'] += price
                
        except Exception as e:
            print(f"Error parsing order {order.id}: {e}")
            continue
            
    # Convert to Lists for Template
    daily_report = [{'date': k, 'count': v['count'], 'total': v['total']} for k, v in daily_data.items()]
    daily_report.sort(key=lambda x: x['date'], reverse=True)
    
    ticket_report = [{'name': k, 'qty': v['qty'], 'total': v['total']} for k, v in ticket_data.items()]
    ticket_report.sort(key=lambda x: x['qty'], reverse=True)
    
    total_revenue = sum(o.total_price for o in orders)
    total_orders = len(orders)
    
    return render_template('admin/reports.html', 
                           daily_report=daily_report,
                           ticket_report=ticket_report,
                           total_revenue=total_revenue,
                           total_orders=total_orders,
                           start_date=start_date_str,
                           end_date=end_date_str)

# --- ACTIONS ---

@main.route('/dashboard/tickets/add', methods=['GET', 'POST'])
def admin_add_ticket():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        
        # Prices Helper
        def get_int(key):
            val = request.form.get(key)
            return int(val) if val and val.strip() else None

        data = {
            'name': name,
            'description': request.form.get('desc'),
            'price_adult': get_int('price_adult') or 0,
            'price_child': get_int('price_child') or 0,
            'price_umum': get_int('price_umum') or 0,
            'price_reseller_adult': get_int('price_reseller_adult'),
            'price_reseller_child': get_int('price_reseller_child'),
            'price_reseller_umum': get_int('price_reseller_umum'),
            'price_adult_weekend': get_int('price_adult_weekend'),
            'price_child_weekend': get_int('price_child_weekend'),
            'price_umum_weekend': get_int('price_umum_weekend'),
            'price_adult_highseason': get_int('price_adult_highseason'),
            'price_child_highseason': get_int('price_child_highseason'),
            'price_umum_highseason': get_int('price_umum_highseason'),
            'slug': name.lower().replace(' ', '_').replace('/', '_'),
            'is_active': request.form.get('is_active') == 'on',
            'price_reseller_umum': get_int('price_reseller_umum'),
            'price_group_adult': get_int('price_group_adult'),
            'price_group_child': get_int('price_group_child'),
            'price_group_umum': get_int('price_group_umum'),
            'category': 'personal', # Defaulting to personal since checkboxes are removed
        }
        
        db.session.add(Ticket(**data))
        db.session.commit()
        return redirect(url_for('main.admin_tickets'))
        
    return render_template('admin/ticket_form.html', ticket=None)

@main.route('/dashboard/tickets/edit/<int:id>', methods=['GET', 'POST'])
def admin_edit_ticket(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    ticket = Ticket.query.get_or_404(id)
    
    if request.method == 'POST':
        ticket.name = request.form.get('name')
        
        def get_int(key):
            val = request.form.get(key)
            return int(val) if val and val.strip() else None

        ticket.price_adult = get_int('price_adult') or 0
        ticket.price_child = get_int('price_child') or 0
        ticket.price_umum = get_int('price_umum') or 0
        
        ticket.price_reseller_adult = get_int('price_reseller_adult')
        ticket.price_reseller_child = get_int('price_reseller_child')
        ticket.price_reseller_umum = get_int('price_reseller_umum')
        
        ticket.price_group_adult = get_int('price_group_adult')
        ticket.price_group_child = get_int('price_group_child')
        ticket.price_group_umum = get_int('price_group_umum')
        
        ticket.price_adult_weekend = get_int('price_adult_weekend')
        ticket.price_child_weekend = get_int('price_child_weekend')
        ticket.price_umum_weekend = get_int('price_umum_weekend')
        
        ticket.price_adult_highseason = get_int('price_adult_highseason')
        ticket.price_child_highseason = get_int('price_child_highseason')
        ticket.price_umum_highseason = get_int('price_umum_highseason')
        
        ticket.description = request.form.get('desc')
        ticket.is_active = request.form.get('is_active') == 'on'
        # Category kept as is since checkbox is removed
        
        db.session.commit()
        return redirect(url_for('main.admin_tickets'))
        
    return render_template('admin/ticket_form.html', ticket=ticket)
    return redirect(url_for('main.admin_tickets'))

@main.route('/ticket/delete/<int:id>', methods=['POST', 'GET']) # GET for link support if needed, but POST is safer
def delete_ticket(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    ticket = Ticket.query.get_or_404(id)
    db.session.delete(ticket)
    db.session.commit()
    return redirect(url_for('main.admin_tickets'))

@main.route('/addon/add', methods=['POST'])
def add_addon():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    name = request.form.get('name')
    price = int(request.form.get('price'))
    
    pra = request.form.get('price_reseller')
    price_reseller = int(pra) if pra and pra.strip() else None
    
    desc = request.form.get('desc')
    is_active = request.form.get('is_active') == 'on'
    slug = name.lower().replace(' ', '_').replace('/', '_')
    
    # Multiple Categories
    categories = request.form.getlist('categories')
    category_str = ",".join(categories) if categories else "personal"
    
    db.session.add(Addon(
        name=name, 
        description=desc, 
        price=price, 
        price_reseller=price_reseller,
        slug=slug, 
        is_active=is_active,
        category=category_str
    ))
    db.session.commit()
    return redirect(url_for('main.admin_addons'))

@main.route('/addon/edit/<int:id>', methods=['POST'])
def edit_addon(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    addon = Addon.query.get_or_404(id)
    
    addon.name = request.form.get('name')
    addon.price = int(request.form.get('price'))
    
    pra = request.form.get('price_reseller')
    addon.price_reseller = int(pra) if pra and pra.strip() else None
    
    addon.description = request.form.get('desc')
    addon.is_active = request.form.get('is_active') == 'on'
    
    # Multiple Categories
    categories = request.form.getlist('categories')
    addon.category = ",".join(categories) if categories else "personal"
    
    db.session.commit()
    return redirect(url_for('main.admin_addons'))

@main.route('/addon/delete/<int:id>', methods=['POST'])
def delete_addon(id):
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    addon = Addon.query.get_or_404(id)
    db.session.delete(addon)
    db.session.commit()
    return redirect(url_for('main.admin_addons'))



@main.route('/settings/update', methods=['POST'])
def update_settings():
    if not session.get('logged_in') or session.get('user_role') != 'admin': return redirect(url_for('main.login'))
    
    settings = SiteSetting.query.first()
    if not settings:
        settings = SiteSetting()
        db.session.add(settings)
    
    settings.park_name = request.form.get('park_name')
    settings.park_info = request.form.get('park_info')
    settings.opening_hours = request.form.get('opening_hours')
    settings.allow_wristband = request.form.get('allow_wristband') == 'on'
    settings.allow_gate = request.form.get('allow_gate') == 'on'
    
    try:
        settings.min_group_order = int(request.form.get('min_group_order', 10))
    except (ValueError, TypeError):
        settings.min_group_order = 10
    
    # Handle Logo Upload
    if 'logo_file' in request.files:
        file = request.files['logo_file']
        if file and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"logo_{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            settings.logo_url = url_for('static', filename='uploads/' + filename)
            
    # Handle Hero Image Upload
    if 'hero_image_file' in request.files:
        file = request.files['hero_image_file']
        if file and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"hero_{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            settings.hero_image_url = url_for('static', filename='uploads/' + filename)
    
    db.session.commit()
    return redirect(url_for('main.admin_settings'))

# --- OPERATOR DASHBOARD ---

@main.route('/operator/dashboard')
def operator_dashboard():
    if not session.get('logged_in'): return redirect(url_for('main.login'))
    gates = Gate.query.filter_by(is_active=True).all()
    return render_template('operator/dashboard.html', gates=gates)

@main.route('/api/operator/scan', methods=['POST'])
def operator_scan():
    if not session.get('logged_in'): 
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        
    data = request.json
    ticket_uuid = data.get('uuid')
    scan_type = data.get('type') # 'wristband' or 'gate'
    action = data.get('action', 'execute') # 'check' or 'execute'
    gate_name = data.get('gate_name') # For recording which gate
    
    if not ticket_uuid:
        return jsonify({'status': 'error', 'message': 'Kode tiket tidak ditemukan'}), 400
        
    # Try finding by UUID first (QR Scan)
    order = Order.query.filter_by(uuid=ticket_uuid).first()
    
    # If not found, try finding by Invoice Number (Manual Entry)
    if not order:
        order = Order.query.filter_by(invoice_number=ticket_uuid).first()
    
    if not order:
        return jsonify({'status': 'error', 'message': 'Tiket tidak ditemukan'}), 404
        
    # Validation Logic
    today_str = datetime.now().strftime('%Y-%m-%d')
    checks = {
        'is_paid': order.payment_status == 'paid',
        'is_today': order.visit_date == today_str,
        'already_scanned': False,
        'scan_time': None
    }
    
    if scan_type == 'wristband':
        if order.wristband_at:
            checks['already_scanned'] = True
            checks['scan_time'] = order.wristband_at.strftime("%H:%M:%S")
    elif scan_type == 'gate':
        if order.checkin_at:
            checks['already_scanned'] = True
            checks['scan_time'] = order.checkin_at.strftime("%H:%M:%S")
            
    # If Action is CHECK, return details immediately
    if action == 'check':
        return jsonify({
            'status': 'success',
            'order': _serialize_order_simple(order),
            'checks': checks,
            'payment_status': order.payment_status,
            'visit_date': order.visit_date
        })

    # --- EXECUTE ACTION ---

    # Check Payment Status
    if not checks['is_paid']:
        return jsonify({'status': 'error', 'message': f'Tiket belum lunas (Status: {order.payment_status})'}), 400
        
    # Check Visit Date (Warning only? Or Block? Let's allow but warn)
    date_warning = None
    if not checks['is_today']:
        date_warning = f"Tanggal kunjungan tiket ({order.visit_date}) tidak sesuai dengan hari ini ({today_str})."
    
    # Process based on type
    timestamp = datetime.now()
    message = ""
    
    if scan_type == 'wristband':
        if checks['already_scanned']:
             return jsonify({
                'status': 'error', 
                'message': f'Tiket sudah ditukar gelang pada {checks["scan_time"]}',
                'order': _serialize_order_simple(order)
            })
        order.wristband_at = timestamp
        message = "Berhasil tukar gelang"
        
    elif scan_type == 'gate':
        if checks['already_scanned']:
             return jsonify({
                'status': 'error', 
                'message': f'Tiket sudah check-in pada {checks["scan_time"]}',
                'order': _serialize_order_simple(order)
            })
        order.checkin_at = timestamp
        if gate_name:
            order.checkin_gate = gate_name
        message = f"Berhasil Check-in {gate_name or 'Gate'}"
    
    else:
        return jsonify({'status': 'error', 'message': 'Tipe scan tidak valid'}), 400
        
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'message': message,
        'warning': date_warning,
        'order': _serialize_order_simple(order),
        'timestamp': timestamp.strftime('%H:%M:%S')
    })

def _serialize_order_simple(order):
    return {
        'uuid': order.uuid,
        'customer_name': order.customer_name,
        'visit_date': order.visit_date,
        'visit_type': order.visit_type,
        'total_pax': _count_pax(order.details),
        'wristband_at': order.wristband_at.strftime('%Y-%m-%d %H:%M:%S') if order.wristband_at else None,
        'checkin_at': order.checkin_at.strftime('%Y-%m-%d %H:%M:%S') if order.checkin_at else None
    }

def _count_pax(details_json):
    try:
        data = json.loads(details_json)
        items = data.get('items', [])
        count = 0
        for item in items:
            count += item.get('qty', 0)
        return count
    except:
        return 0