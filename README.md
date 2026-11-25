# Market Scraper GUI

Aplikasi desktop untuk mengambil dan menyimpan data publik dari Shopee, Tokopedia, Lazada, Google Reviews, Google Research, dan sumber berita Indonesia. Antarmuka utama menggunakan PySide6/QML melalui `main.py`. Gunakan situs sesuai ketentuan masing-masing.

## Instalasi

Gunakan Python 3.11 atau lebih baru dan buat virtual environment baru pada komputer tempat aplikasi dijalankan:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe main.py
```

Jika perintah `py` tidak tersedia, gunakan perintah Python yang terpasang untuk membuat environment. Pada Linux/macOS gunakan `.venv/bin/python`. Shopee memakai Google Chrome terpasang dan menampilkan browser; jika diminta, login atau captcha ditangani pengguna sendiri. Selenium memerlukan browser yang sesuai. Folder `venv` lama tidak dapat diandalkan setelah dipindah komputer; buat ulang, jangan salin.

## Pemakaian

Pilih sumber, mode keyword/URL dan batas hasil, lalu klik Scrape. Google Reviews menerima nama tempat dan lokasi opsional. Aplikasi memeriksa cache dahulu, mengambil data baru bila perlu, dan menyimpan hasil ke `scrape.db`. Gunakan Paksa refresh untuk melewati cache. Stop meminta scraper yang mendukungnya berhenti dan menyimpan hasil parsial yang tersedia.

Tabel hasil mengikuti sumber yang dipilih. Klik judul kolom untuk mengurutkan naik atau turun, lalu geser tabel secara horizontal untuk melihat kolom di sebelah kanan. Filter mencari teks di semua kolom sumber tersebut. Saat berpindah sumber, hasil manual terakhir tiap sumber tetap tersedia selama sesi aplikasi.

**Ekspor CSV / Ekspor JSON** menyimpan baris sesuai filter dan urutan tabel. Nilai seperti harga, rating, dan tanggal ditulis sebagai field terpisah sesuai sumber. CSV memakai UTF-8 dengan BOM untuk spreadsheet dan JSON memakai UTF-8.

**Jadwal otomatis** mulai dalam posisi mati setiap kali aplikasi dibuka. Tugas dan riwayat tetap tersimpan. Buka **Jadwal**, atur sumber, keyword atau URL, limit, dan interval. Google Reviews juga menerima lokasi. Saat sakelar dinyalakan, interval setiap tugas aktif dihitung dari waktu tersebut. Gunakan **Jalankan sekarang** untuk menjalankan tugas pilihan segera.

Satu tugas terjadwal dan satu scrape manual dapat berjalan bersamaan untuk dua sumber berbeda. Jika keduanya membutuhkan sumber yang sama, tugas otomatis menunggu sampai sumber tersedia. Hasil manual tampil di tabel utama dan eksekusi terjadwal tercatat di **Riwayat eksekusi**. Mematikan sakelar menghentikan pemicu berikutnya dan mengizinkan tugas yang sedang berjalan selesai. Shopee tidak termasuk sumber terjadwal.

Jadwal Tokopedia membuka jendela Chromium secara bawaan, seperti scrape manual. Opsi **Tanpa jendela (headless)** di formulir Jadwal dapat disimpan untuk masing-masing tugas Tokopedia.

`app.py` adalah antarmuka Tkinter lama. Kedua antarmuka menggunakan database yang sama, jadi hindari menjalankannya bersamaan.

## Data lokal dan cache

Database lama `scrape.db` tetap dipakai. Saat pertama kali dijalankan dengan versi ini, skema diperbarui otomatis tanpa menghapus item: satu item dapat dikaitkan dengan beberapa keyword atau lokasi. Database lama hanya menyimpan satu keyword per item; hubungan lain yang tidak pernah dicatat sebelumnya baru terbentuk saat scraping ulang. Sebaiknya cadangkan database sebelum pembaruan besar.

File debug baru disimpan di `runtime/`; profil Shopee baru juga dibuat di sana. Jika profil lama `pw_shopee_profile/` ada, aplikasi tetap memakainya agar sesi tidak berubah. File lama tidak dipindahkan atau dihapus otomatis. Jangan membagikan profil browser, cookie (termasuk `google_storage.json`), database, log, atau HTML debug. `.gitignore` membantu mencegah file tersebut ditambahkan ke Git, tetapi tidak menghapus file yang sudah pernah dilacak atau dibagikan.

## Pengujian

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tes ini berjalan offline dan memeriksa penyimpanan, migrasi, cache beberapa pencarian dan penanganan kegagalan. Uji langsung tiap sumber secara terpisah karena struktur halaman dan pembatasan akses dapat berubah.
