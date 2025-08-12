Cara menggunakan 
1. Jalankan file python mass_download.py dengan command
   python mass_download.py -i links.txt -o <Folder destination> --remote gdrive

Pastikan udah ada rclone
1️⃣ Install rclone & masukin ke PATH

  Download rclone untuk Windows:
    🔗 https://rclone.org/downloads/

  Extract file ZIP → akan ada rclone.exe.

  Taruh rclone.exe di folder yang sudah ada di PATH (contoh C:\Windows\System32) atau taruh di folder khusus lalu tambahkan folder itu ke PATH:

        Start Menu → ketik Edit the system environment variables

        Klik Environment Variables

        Edit Path → tambahkan folder tempat rclone.exe.

Buka PowerShell baru (biar PATH ke-refresh) → cek: rclone version
