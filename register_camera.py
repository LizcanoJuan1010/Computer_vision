import requests
import json
import sys

BASE_URL = "http://localhost:8003/api/v1"
ORG_SLUG = "vigias"
ZONE_SLUG = "planta"

def register_camera():
    print("------------------------------------------------")
    print("🚀 Registering Camera 101 (Vehicle/LPR)")
    print("------------------------------------------------")

    # 1. Create Camera
    url = f"{BASE_URL}/orgs/{ORG_SLUG}/zones/{ZONE_SLUG}/cameras/"
    payload = {
        "name": "Camera 101 LPR",
        "rtsp_url": "rtsp://{USER}:{PASS}@{IP}:{PORT_RTSP}/Streaming/Channels/101",
        "location_name": "Planta Principal",
        "meta_info": {"type": "vehicle_lpr"}
    }
    
    print(f"📡 POST {url}")
    print(json.dumps(payload, indent=2))
    
    try:
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        cam = resp.json()
        print(f"✅ Camera Created! ID: {cam['id']}")
        cam_id = cam['id']
    except Exception as e:
        print(f"❌ Failed to create camera: {e}")
        if hasattr(e, 'response') and e.response:
            print(e.response.text)
        return

    # 2. Add LPR Config
    url_config = f"{url}{cam_id}/zones"
    payload_config = {
        "event_type": "lpr",
        "confidence_threshold": 0.4,
        "default_severity": "INFO",
        "debounce_seconds": 5,
        "roi_polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]] # Full frame
    }

    print(f"⚙️ Configuring LPR: POST {url_config}")
    
    try:
        resp = requests.post(url_config, json=payload_config)
        resp.raise_for_status()
        print(f"✅ LPR Configuration Added!")
        print(json.dumps(resp.json(), indent=2))
        
        print(f"\n🎉 SUCCESS! Camera registered and configured.")
        print(f"Use this ID for debugging: {cam_id}")
        
    except Exception as e:
        print(f"❌ Failed to configure LPR: {e}")
        if hasattr(e, 'response') and e.response:
            print(e.response.text)

if __name__ == "__main__":
    register_camera()
