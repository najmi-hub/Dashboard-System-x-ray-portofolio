# Command Center V2 — X-Ray Monitoring & Operational Analytics

Aplikasi web berbasis **Flask** yang dirancang untuk memantau proses pemindaian kontainer X-Ray secara *realtime*, melacak status pengiriman data transaksi (`OK` / `NOK`) ke server pusat, memantau kondisi perangkat keras jaringan, serta mempermudah proses pengecekan ulang (*rescan*), pengiriman ulang (*resend*), dan ekspor laporan operasional.

---

## ✨ Fitur Utama

- **Dashboard Analytics & Realtime Sync (3 Detik)**
  - **Ringkasan Metrik Harian:** Menampilkan total pemindaian hari ini (`OK` vs `NOK`), status koneksi & latensi perangkat keras, sisa kapasitas penyimpanan *shared folder* server, serta persentase *Success Rate*.
  - **Visualisasi Grafik Interaktif:** Grafik garis tren transaksi 30 hari terakhir dan grafik batang bertumpuk (*stacked bar*) volume pemindaian per jam menggunakan **Chart.js**.
  - **Tabel Monitoring Ganda:** Menyandingkan tabel *Data Real Scan Server* dan *Data Realtime Pengiriman (24 Jam)* secara langsung.
  - **Smart Batch Gap Alert:** Deteksi otomatis pada 20 data pemindaian terbaru yang memicu peringatan visual dan indikator suara apabila ditemukan $\ge 10$ data yang belum masuk ke log pengiriman.
- **Data Real Server (Metadata X-Ray)**
  - Menampilkan daftar ID folder pemindaian, waktu pemindaian, nama file *icon*, dan nama file citra X-Ray utama secara ringan tanpa membebani browser dengan rendering gambar berukuran besar.
- **Detail Log Transaksi (OK & NOK)**
  - Pemisahan riwayat log berstatus `OK` dan `NOK` lengkap dengan pencarian kata kunci (ID Scan, nomor kontainer, nomor plat) dan filter rentang tanggal.
  - Dilengkapi modal rincian transaksi untuk membedakan pengiriman pertama yang langsung sukses dengan pengiriman revisi / *resend* ke-2.
- **Rescan Checker (WhatsApp Text Parser)**
  - Mengekstrak nomor kontainer standar ISO (`4 huruf + 7 angka`) secara otomatis dari teks laporan grup WhatsApp dan mengecek ketersediaan datanya di database lokal.
- **Auto Resend & Manual Resend (XML IDR Payload)**
  - **Auto Resend 1-Klik:** Membangun payload XML `<IDR>` dan jalur `ftp_path` secara otomatis dari database untuk dikirim ulang ke API server pusat dengan validasi respon 2 lapis.
  - **Manual Resend:** Formulir khusus melalui modal untuk mengirim ulang data transaksi yang belum tercatat di database lokal (*data ngambang*).
- **Preview & Export Laporan Excel**
  - Pratinjau data sebelum mengunduh laporan ke format `.xlsx` untuk data hasil pengiriman maupun metadata real server.
- **Autentikasi & Tema Adaptif (Dark / Light Mode)**
  - Sistem login terproteksi menggunakan `Flask-Login` dan dukungan peralihan **Mode Malam** serta **Mode Siang**.

---

## 🛠️ Teknologi yang Digunakan

- **Backend:** Python 3, Flask, Flask-Login, Werkzeug
- **Database:** MySQL (`mysql-connector-python`)
- **Integrasi & Utilitas:** `requests` (REST API XML/JSON), `pandas` & `openpyxl` (Ekspor Excel), `pythonping` (Monitoring perangkat), `ctypes` / `shutil` (Monitoring disk jaringan)
- **Frontend:** HTML5, Jinja2, Bootstrap 5, Tailwind CSS, Chart.js, Font Awesome

---

## 📁 Struktur Proyek

```text
├── app.py                      # Aplikasi utama Flask, routing halaman, & endpoint REST API
├── templates/
│   ├── base_v2.html            # Layout utama (Sidebar, Topbar, Theme Switcher, Modal Manual Resend)
│   ├── login_v2.html           # Halaman login pengguna
│   ├── index_v2.html           # Halaman utama Dashboard Analytics & Realtime Monitoring
│   ├── data_real_server.html   # Halaman daftar metadata pemindaian server X-Ray
│   ├── detail_status_v2.html   # Halaman detail log transaksi OK & NOK beserta modal rincian
│   ├── export_v2.html          # Halaman preview data, tombol resend, & ekspor Excel
│   ├── rescan_v2.html          # Halaman pengecekan massal nomor kontainer dari pesan teks
│   └── analytics_v2.html       # Halaman analitik grafik tren transaksi
└── static/
    ├── css/                    # Aset stylesheet lokal (Bootstrap, Font Awesome)
    ├── js/                     # Aset script lokal (Tailwind CSS, Chart.js, Bootstrap Bundle)
    └── logo.png                # Logo instansi/perusahaan
```

---

## 🚀 Cara Instalasi & Menjalankan

1. **Clone repository ini**
   ```bash
   git clone [https://github.com/username-kamu/nama-repository.git](https://github.com/username-kamu/nama-repository.git)
   cd nama-repository
   ```

2. **Buat dan aktifkan virtual environment**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux / macOS
   source venv/bin/activate
   ```

3. **Instal pustaka Python yang dibutuhkan**
   ```bash
   pip install flask flask-login mysql-connector-python pandas openpyxl pythonping requests werkzeug
   ```

4. **Konfigurasi Database & Jaringan**
   Sesuaikan pengaturan koneksi MySQL (`DB_CONFIG`), alamat API pengiriman ulang (`RESEND_API_URL`), dan jalur *shared folder* jaringan di dalam file `app.py`:
   ```python
   DB_CONFIG = {
       "host": "localhost",
       "user": "root",
       "password": "your_database_password",
       "database": "Dashboard",
   }
   ```
   Pastikan database MySQL memiliki tabel `users`, `logs`, `real_scans`, dan `device_status`.

5. **Jalankan aplikasi**
   ```bash
   python app.py
   ```
   Buka browser dan akses alamat `http://localhost:5001`.

---

## 📄 Lisensi

© 2026 PT Mitrabuana Widyasakti. Hak cipta dilindungi undang-undang.
