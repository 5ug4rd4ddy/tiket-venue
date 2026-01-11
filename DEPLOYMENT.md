# Dokumentasi Deployment Tiket Wahana

Dokumentasi ini menjelaskan panduan deployment aplikasi **Tiket Wahana** di server Ubuntu menggunakan **Gunicorn**, **Systemd**, dan **Nginx/CloudPanel**.

---

## 1. Persiapan Lingkungan Server

Pastikan server telah terinstall:
- Python 3.10+
- Pip
- Virtualenv
- Nginx (atau CloudPanel)

### Informasi Server (Verified)
- **Domain**: `demo-tiket-venue.tiketku.id`
- **User Aplikasi**: `demo-tiket-venue`
- **Path Project**: `/home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id`
- **Port Aplikasi**: `5004`
- **Service Name**: `demo-tiket-venue-gunicorn`

---

## 2. Struktur Project

Pastikan struktur file di server seperti berikut:

```
/home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id
├── app/
│   └── static/   <-- File CSS/JS/Uploads ada di sini
├── instance/
├── venv/
├── requirements.txt
├── run.py
└── wsgi.py
```

---

## 3. Setup Virtual Environment

Masuk ke direktori project dan setup virtual environment:

```bash
cd /home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id

# Buat virtual environment
python3 -m venv venv

# Aktivasi
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

---

## 4. Membuat File `wsgi.py`

Buat file `wsgi.py` di root project sebagai entry point untuk Gunicorn:

```python
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
```

---

## 5. Konfigurasi Gunicorn Service (Systemd)

Buat file service systemd untuk menjalankan aplikasi di background.

**File:** `/etc/systemd/system/demo-tiket-venue-gunicorn.service`

```ini
[Unit]
Description=Gunicorn Flask demo-tiket-venue.tiketku.id
After=network.target

[Service]
User=demo-tiket-venue
Group=demo-tiket-venue

WorkingDirectory=/home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id

Environment="PATH=/home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id/venv/bin"

ExecStart=/home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id/venv/bin/gunicorn \
    --workers 3 \
    --bind 127.0.0.1:5004 \
    --reload \
    wsgi:app

Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### Aktivasi Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Start dan Enable service
sudo systemctl enable demo-tiket-venue-gunicorn
sudo systemctl start demo-tiket-venue-gunicorn

# Cek status
sudo systemctl status demo-tiket-venue-gunicorn
```

---

## 6. Konfigurasi Nginx / CloudPanel

Aplikasi berjalan di `127.0.0.1:5004`. Setup Nginx sebagai Reverse Proxy.

### 1. Masalah Static Files (CSS/Gambar 404)

Jika file static (CSS, Gambar) tidak muncul, biasanya karena masalah **Permission** pada direktori parent, atau konfigurasi Nginx yang belum benar.

**Langkah A: Fix Permission Folder Utama (CRITICAL)**
Nginx berjalan sebagai user `www-data` (atau `nginx`). Agar bisa membaca file di dalam `/home/demo-tiket-venue/...`, user Nginx harus punya hak akses "execute" (x) di folder Home user tersebut.

```bash
# 1. Buka akses Home Directory (agar Nginx bisa "lewat")
chmod 755 /home/demo-tiket-venue

# 2. Buka akses folder project
chmod 755 /home/demo-tiket-venue/htdocs
chmod 755 /home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id

# 3. Buka akses folder app dan static
cd /home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id
chmod 755 app
find app/static -type d -exec chmod 755 {} \;
find app/static -type f -exec chmod 644 {} \;
```

**Langkah B: Konfigurasi Nginx**
Tambahkan blok `location /static` **SEBELUM** blok `location /`.

```nginx
# Konfigurasi untuk Static Files
location /static {
    alias /home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id/app/static;
    expires 30d;
    access_log off;
    add_header Cache-Control "public";
}

# Konfigurasi Proxy ke Gunicorn
location / {
    proxy_pass http://127.0.0.1:5004;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

---

## 7. Workflow Update Aplikasi

Untuk mengupdate aplikasi tanpa downtime (menggunakan `--reload`):

1. **Login ke server**:
   ```bash
   ssh root@SERVER_IP
   su - demo-tiket-venue
   cd /home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id
   ```

2. **Pull perubahan terbaru**:
   ```bash
   git pull origin main
   ```

3. **Update dependency (jika ada perubahan di requirements.txt)**:
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   # Service akan auto-reload jika menggunakan flag --reload, 
   # namun jika menambah library baru disarankan restart:
   sudo systemctl restart demo-tiket-venue-gunicorn
   ```

---

## 8. Monitoring & Logs

**Cek Log Gunicorn:**
```bash
sudo journalctl -u demo-tiket-venue-gunicorn -f
```

**Cek Port:**
```bash
ss -tulpn | grep 5004
```

---

## 9. Troubleshooting Lanjutan

### Debugging Permission Path
Jika masih 404, jalankan perintah ini untuk melihat di level mana akses diblokir:

```bash
namei -nom /home/demo-tiket-venue/htdocs/demo-tiket-venue.tiketku.id/app/static/css/style.css
```

**Cara Membaca Output:**
Perhatikan kolom paling kiri. Nginx (user `www-data`) masuk dalam kategori **Others** (3 bit terakhir).
- ❌ **SALAH:** `drwxrwx---` (User lain tidak bisa masuk/baca)
- ✅ **BENAR:** `drwxr-xr-x` (User lain bisa read & execute/masuk)

Jika Anda melihat baris seperti ini:
`drwxrwx--- demo-tiket-venue demo-tiket-venue demo-tiket-venue`
Artinya Nginx **DIBLOKIR** di folder home user tersebut. Solusinya wajib jalankan `chmod 755` di folder itu.

### Cek Error Log Nginx
Untuk melihat alasan pasti kenapa Nginx menolak (404 atau 403):
```bash
tail -f /var/log/nginx/error.log
# Atau jika menggunakan CloudPanel (sesuaikan path log user)
tail -f /home/demo-tiket-venue/logs/nginx/error.log
```

### Checklist Verifikasi Permission
Pastikan output `namei -nom ...` atau `ls -la` menunjukkan permission berikut:
- [ ] **Home User** (`/home/demo-tiket-venue`): `drwxr-xr-x` (755)
- [ ] **Project Root**: `drwxr-xr-x` (755)
- [ ] **Static Folder**: `drwxr-xr-x` (755)
- [ ] **Sub-folder** (`static/uploads`, `static/qrcodes`): `drwxr-xr-x` (755)
- [ ] **File** (`style.css`, gambar): `-rw-r--r--` (644)
