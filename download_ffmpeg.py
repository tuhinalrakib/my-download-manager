import os
import urllib.request
import zipfile
import shutil

print("==================================================")
print(" Downloading FFmpeg Portable for YouTube Downloader...")
print("==================================================")

url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
zip_path = "ffmpeg_temp.zip"

try:
    print("\n[1/3] Downloading FFmpeg zip package...")
    urllib.request.urlretrieve(url, zip_path)
    print("      Download completed successfully!")

    print("\n[2/3] Extracting ffmpeg.exe...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for file in zip_ref.namelist():
            if file.endswith("ffmpeg.exe"):
                zip_ref.extract(file, ".")
                extracted_path = file
                break
    
    # Move ffmpeg.exe to project root folder
    if os.path.exists("ffmpeg.exe"):
        os.remove("ffmpeg.exe")
    shutil.move(extracted_path, "ffmpeg.exe")

    # Cleanup temp extracted folders & zip
    if os.path.exists("ffmpeg-master-latest-win64-gpl"):
        shutil.rmtree("ffmpeg-master-latest-win64-gpl")
    if os.path.exists(zip_path):
        os.remove(zip_path)

    print("\n==================================================")
    print(" [SUCCESS] ffmpeg.exe is installed in project folder!")
    print(" Now you can download 1080p, 4K & MP3 without errors!")
    print("==================================================")

except Exception as e:
    print(f"\n[ERROR] Failed to auto-download FFmpeg: {e}")
    print("Don't worry! Your app will still download videos in single MP4 format.")
