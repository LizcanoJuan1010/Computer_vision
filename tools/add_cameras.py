import json
import os
import re

CAMERAS_JSON = "ingest/cameras.json"
AVAILABLE_TXT = "available_cameras.txt"

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []

def load_txt(path):
    urls = []
    if os.path.exists(path):
        with open(path, 'r') as f:
            for line in f:
                urls.append(line.strip())
    return urls

def extract_channel(url):
    # Extract 101 from .../Channels/101
    m = re.search(r'Channels/(\d+)', url)
    if m:
        return m.group(1)
    return None

def main():
    existing = load_json(CAMERAS_JSON)
    existing_ids = {c["id"] for c in existing}
    
    discovered = load_txt(AVAILABLE_TXT)
    
    added_count = 0
    
    for url in discovered:
        if not url: continue
        channel = extract_channel(url)
        if not channel: continue
        
        cam_id = f"cam_{channel}"
        
        if cam_id in existing_ids:
            print(f"Skipping {cam_id} (already exists)")
            continue
            
        print(f"Adding {cam_id}...")
        
        new_entry = {
            "id": cam_id,
            "url": f"rtsp://{{USER}}:{{PASS}}@{{IP}}:{{PORT_RTSP}}/Streaming/Channels/{channel}",
            "name": f"Camera {channel}",
            "services": ["security"],
            "features": ["intrusion", "line_crossing", "face"],
            "zones": {
                "line_crossing": {
                    "points": [],
                    "trigger": "in_out"
                },
                "intrusion": {
                    "points": [],
                    "trigger": "enter"
                }
            }
        }
        
        existing.append(new_entry)
        added_count += 1
        
    # Sort by ID for neatness
    existing.sort(key=lambda x: int(x["id"].split("_")[1]) if "_" in x["id"] and x["id"].split("_")[1].isdigit() else 99999)
    
    with open(CAMERAS_JSON, "w") as f:
        json.dump(existing, f, indent=4)
        
    print(f"\nDone. Added {added_count} new cameras. Total cameras: {len(existing)}")

if __name__ == "__main__":
    main()
