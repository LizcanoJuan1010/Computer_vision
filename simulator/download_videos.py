import os
import yt_dlp

VIDEO_DIR = "/app/videos"

URLS = {
    "fight_sim.mp4": "https://www.youtube.com/watch?v=_4p2GE7Q_HA", # Removed &rco=1
    "falling_sim.mp4": "https://www.youtube.com/watch?v=W2GlSV8lfBU",
    "attributes_sim.mp4": "https://www.youtube.com/shorts/0CaKnwBcD4Y",
    "vehicle_sim.mp4": "https://www.youtube.com/shorts/JvlKMB6qQj8"
}

def download_all():
    if not os.path.exists(VIDEO_DIR):
        os.makedirs(VIDEO_DIR)

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{VIDEO_DIR}/%(filename)s', # Placeholder, we will override output name manually or use default
        'noplaylist': True,
        'quiet': False
    }

    for name, url in URLS.items():
        file_path = os.path.join(VIDEO_DIR, name)
        if os.path.exists(file_path):
            print(f"✅ {name} already exists. Skipping.")
            continue
        
        print(f"⬇️ Downloading {name} from {url}...")
        
        # Customize output template for this specific file
        current_opts = ydl_opts.copy()
        current_opts['outtmpl'] = file_path
        
        try:
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                ydl.download([url])
            print(f"✅ Downloaded {name}")
        except Exception as e:
            print(f"❌ Failed to download {name}: {e}")

if __name__ == "__main__":
    download_all()
