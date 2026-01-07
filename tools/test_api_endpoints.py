import requests
import json
import os
import sys

BASE_URL = "http://localhost:8003/api/v1"
ORG_SLUG = "vigias"
ZONE_SLUG = "planta"

def test_endpoints():
    print("=== Testing API Endpoints ===")
    
    # 1. List Cameras
    url = f"{BASE_URL}/orgs/{ORG_SLUG}/zones/{ZONE_SLUG}/cameras"
    print(f"GET {url}")
    try:
        resp = requests.get(url)
        if resp.status_code != 200:
            print(f"FAILED to list cameras: {resp.status_code} {resp.text}")
            return
        cameras = resp.json()
        print(f"Found {len(cameras)} cameras.")
        if not cameras:
            print("No cameras to test with.")
            return
        
        test_cam = cameras[0]
        cam_id = test_cam['id']
        print(f"Testing with Camera: {test_cam['name']} ({cam_id})")
        
    except Exception as e:
        print(f"Error connecting to API: {e}")
        return

    # 2. Get AI Zones for Camera
    url = f"{BASE_URL}/orgs/{ORG_SLUG}/zones/{ZONE_SLUG}/cameras/{cam_id}/zones"
    print(f"GET {url}")
    resp = requests.get(url)
    if resp.status_code != 200:
         print(f"FAILED to get AI zones: {resp.status_code} {resp.text}")
         return
    
    zones = resp.json()
    print(f"Found {len(zones)} AI zones configured.")
    
    # 3. Create/Update a Test Zone (Intrusion)
    # We will try to update an existing one or create one
    target_zone = None
    for z in zones:
        if z['event_type'] == 'intrusion':
            target_zone = z
            break
            
    if target_zone:
        print(f"Updating existing intrusion zone: {target_zone['id']}")
        update_url = f"{url}/{target_zone['id']}"
        # Change confidence slightly to verify update
        new_conf = 0.85
        payload = {"confidence_threshold": new_conf}
        print(f"PUT {update_url} with {payload}")
        resp = requests.put(update_url, json=payload)
        
        if resp.status_code == 200:
            print("Update SUCCESS.")
            updated_zone = resp.json()
            if updated_zone['confidence_threshold'] == new_conf:
                print("Verification: Confidence threshold updated correctly in response.")
            else:
                print(f"Verification FAILED: Expected {new_conf}, got {updated_zone['confidence_threshold']}")
        else:
            print(f"Update FAILED: {resp.status_code} {resp.text}")
            
    else:
        print("Creating new intrusion zone...")
        payload = {
            "event_type": "intrusion",
            "confidence_threshold": 0.85,
            "default_severity": "HIGH",
            "roi_polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
            "debounce_seconds": 30
        }
        print(f"POST {url} with payload")
        resp = requests.post(url, json=payload)
        if resp.status_code == 201:
            print("Create SUCCESS.")
        else:
             print(f"Create FAILED: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    test_endpoints()
