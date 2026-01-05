import qrcode
import io
import base64
import requests
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import os
from flask import render_template, current_app, url_for
from .models import SiteSetting

def generate_qr_code(data):
    """Generates a QR code and returns it as a base64 encoded string."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"

def generate_qr_file(data, filename):
    """Generates a QR code and saves it to static/qrcodes."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    # Ensure directory exists
    static_folder = os.path.join(current_app.root_path, 'static', 'qrcodes')
    if not os.path.exists(static_folder):
        os.makedirs(static_folder)
        
    file_path = os.path.join(static_folder, filename)
    img.save(file_path, format="PNG")
    
    return filename

def send_email(to_email, subject, html_content):
    """Sends an email using the configured provider in SiteSetting."""
    settings = SiteSetting.query.first()
    if not settings:
        print("No site settings found. Email not sent.")
        return False

    sender_email = settings.email_from_address
    sender_name = settings.email_from_name
    
    try:
        if settings.email_provider == 'smtp':
            return _send_smtp(settings, to_email, subject, html_content, sender_email, sender_name)
        elif settings.email_provider == 'postal':
            return _send_postal(settings, to_email, subject, html_content, sender_email, sender_name)
        elif settings.email_provider == 'brevo':
            return _send_brevo(settings, to_email, subject, html_content, sender_email, sender_name)
        else:
            print(f"Unknown email provider: {settings.email_provider}")
            return False
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def _send_smtp(settings, to_email, subject, html_content, sender_email, sender_name):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{sender_name} <{sender_email}>"
    msg['To'] = to_email

    part = MIMEText(html_content, 'html')
    msg.attach(part)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.set_debuglevel(1)  # Debugging enabled
            server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(sender_email, to_email, msg.as_string())
        print(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"SMTP Error: {e}")
        import traceback
        traceback.print_exc()
        raise e

def _send_postal(settings, to_email, subject, html_content, sender_email, sender_name):
    # Postal API implementation (assuming generic Postal API structure)
    # You might need to adjust endpoint if using a specific Postal instance
    # For now, this is a placeholder or basic implementation
    # Postal usually uses HTTP API
    # TODO: Implement actual Postal API call if documentation available
    # Assuming Postal sends via SMTP is easier, but if API is required:
    pass 

def _send_brevo(settings, to_email, subject, html_content, sender_email, sender_name):
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": settings.brevo_api_key,
        "content-type": "application/json"
    }
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content
    }
    
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code in [200, 201, 202]:
        return True
    else:
        print(f"Brevo Error: {response.text}")
        raise Exception(f"Brevo API Error: {response.status_code}")

def send_invoice_email(order):
    settings = SiteSetting.query.first()
    subject = f"Invoice #{order.invoice_number} - {settings.park_name if settings else 'Tiket Wahana'}"
    
    # Generate QR for Invoice (maybe point to payment page?)
    # invoice_qr = generate_qr_code(order.invoice_number)
    
    html_content = render_template('email/invoice.html', order=order, settings=settings)
    return send_email(order.customer_email, subject, html_content)

def send_eticket_email(order):
    settings = SiteSetting.query.first()
    subject = f"E-Ticket - {settings.park_name if settings else 'Tiket Wahana'}"
    
    # Generate QR for Ticket (UUID)
    filename = f"{order.uuid}.png"
    generate_qr_file(order.uuid, filename)
    qr_url = url_for('static', filename=f'qrcodes/{filename}', _external=True)
    
    try:
        details = json.loads(order.details)
    except:
        details = {}
    
    html_content = render_template('email/eticket.html', order=order, details=details, settings=settings, qr_code=qr_url)
    return send_email(order.customer_email, subject, html_content)
