# Tiket Wahana System

Aplikasi manajemen tiket wahana berbasis web yang dibangun menggunakan Python (Flask). Sistem ini mencakup pemesanan tiket, manajemen harga dinamis, dashboard admin, dan validasi tiket QR Code.

## 🚀 Fitur Utama

- **Pemesanan Tiket Online**: Antarmuka pengguna untuk memilih tanggal dan jenis tiket (Reguler, Weekend, High Season).
- **Dynamic Pricing**: Harga tiket otomatis menyesuaikan berdasarkan hari (Weekday/Weekend) dan tanggal merah (High Season).
- **Sistem Pembayaran**: Integrasi simulasi pembayaran QRIS/E-Wallet.
- **Tiket QR Code**: Generasi tiket otomatis dengan QR Code unik.
- **Admin Dashboard**:
  - Manajemen Produk & Harga
  - Laporan Penjualan & Check-in
  - Pengaturan Hari Libur & Jam Operasional
  - Validasi Tiket (Gate System)
- **Role-Based Access**: Admin dan Operator.

## 🛠️ Teknologi yang Digunakan

- **Backend**: Python 3, Flask
- **Database**: SQLite (SQLAlchemy ORM)
- **Frontend**: HTML5, Tailwind CSS, Jinja2 Templates
- **Tools**: Gunicorn (Production), ReportLab (PDF Generation)

## 📦 Instalasi (Local Development)

Ikuti langkah berikut untuk menjalankan aplikasi di komputer lokal:

1. **Clone Repository**
   ```bash
   git clone https://github.com/username/tiket-wahana.git
   cd tiket-wahana
   ```

2. **Buat Virtual Environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # MacOS/Linux
   # venv\Scripts\activate   # Windows
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Jalankan Aplikasi**
   ```bash
   python run.py
   ```
   Aplikasi akan berjalan di `http://127.0.0.1:5002`

## 🌐 Deployment

Panduan lengkap untuk men-deploy aplikasi ini ke server produksi (Ubuntu/CloudPanel) dapat dilihat di dokumen:

👉 **[Panduan Deployment (DEPLOYMENT.md)](DEPLOYMENT.md)**

## 📂 Struktur Project

```
tiket-wahana/
├── app/                 # Source code aplikasi utama
│   ├── models.py        # Definisi database
│   ├── routes.py        # Logika routing & controller
│   ├── templates/       # File HTML (Jinja2)
│   └── static/          # Aset statis (CSS, JS, Uploads)
├── instance/            # Database SQLite (wahana.db)
├── tests/               # Unit testing
├── DEPLOYMENT.md        # Panduan deployment
├── requirements.txt     # Daftar library Python
└── run.py               # Script untuk menjalankan aplikasi
```

## 📝 Lisensi

Project ini dibuat untuk keperluan manajemen tiket wahana.
