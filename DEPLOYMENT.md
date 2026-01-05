# Dokumentasi Deployment Tiket Wahana

Dokumentasi ini menjelaskan panduan deployment aplikasi **Tiket Wahana** di server Ubuntu menggunakan **Gunicorn**, **Systemd**, dan **Nginx/CloudPanel**.

---

## 1. Persiapan Lingkungan Server

Pastikan server telah terinstall:
- Python 3.10+
- Pip
- Virtualenv
- Nginx (atau CloudPanel)

### Informasi Umum (Contoh)
- **Domain**: `tiket.wahana.com`
- **User Aplikasi**: `tiket-wahana`
- **Path Project**: `/home/tiket-wahana/htdocs/tiket.wahana.com`
- **Port Aplikasi**: `5000`

---

## 2. Struktur Project

Pastikan struktur file di server seperti berikut:

```
/home/tiket-wahana/htdocs/tiket.wahana.com
├── app/
├── instance/
├── venv/
├── requirements.txt
├── run.py
└── wsgi.py  <-- File entry point untuk Gunicorn
```

---

## 3. Setup Virtual Environment

Masuk ke direktori project dan setup virtual environment:

```bash
cd /home/tiket-wahana/htdocs/tiket.wahana.com

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

**File:** `/etc/systemd/system/tiket-wahana.service`

```ini
[Unit]
Description=Gunicorn instance to serve Tiket Wahana
After=network.target

[Service]
# Sesuaikan user dan group
User=tiket-wahana
Group=tiket-wahana

# Path ke direktori project
WorkingDirectory=/home/tiket-wahana/htdocs/tiket.wahana.com

# Environment path (venv)
Environment="PATH=/home/tiket-wahana/htdocs/tiket.wahana.com/venv/bin"

# Perintah menjalankan Gunicorn
# Sesuaikan jumlah workers (2 * CPU + 1)
ExecStart=/home/tiket-wahana/htdocs/tiket.wahana.com/venv/bin/gunicorn \
    --workers 3 \
    --bind 127.0.0.1:5000 \
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
sudo systemctl start tiket-wahana
sudo systemctl enable tiket-wahana

# Cek status
sudo systemctl status tiket-wahana
```

---

## 6. Konfigurasi Nginx / CloudPanel

Aplikasi berjalan di `127.0.0.1:5000`. Setup Nginx sebagai Reverse Proxy.

### Jika menggunakan CloudPanel:
1. Masuk ke dashboard CloudPanel.
2. Pilih Domain > **VHost**.
3. Edit konfigurasi Nginx/VHost untuk mem-proxy request ke port 5000.
4. Atau pada tab **Settings**, set **Port** ke `5000` jika menggunakan tipe aplikasi Python/Nodejs Generic.

### Jika menggunakan Nginx Manual:
Tambahkan blok lokasi di konfigurasi server block:

```nginx
location / {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

---

## 7. Workflow Update Aplikasi

Untuk mengupdate aplikasi tanpa downtime (jika menggunakan `--reload` di Gunicorn):

1. **Login ke server**:
   ```bash
   ssh tiket-wahana@SERVER_IP
   cd /home/tiket-wahana/htdocs/tiket.wahana.com
   ```

2. **Pull perubahan terbaru**:
   ```bash
   git pull origin main
   ```

3. **Update dependency (jika ada perubahan di requirements.txt)**:
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   sudo systemctl restart tiket-wahana
   ```

4. **Update Database (jika ada migrasi)**:
   Pastikan menjalankan script migrasi jika struktur database berubah.

---

## 8. Monitoring & Logs

**Cek Log Gunicorn:**
```bash
sudo journalctl -u tiket-wahana -f
```

**Cek Port:**
```bash
ss -tulpn | grep 5000
```
