import requests
import os

API_URL = "http://localhost:8003/api/v1/orgs/vigias/faces/"
IMAGE_PATH = "/home/logisticos-two/.gemini/antigravity/brain/137506a0-df8c-4304-8984-8b72d7b4608a/uploaded_image_0_1766890315723.png"

def test_face_enrollment():
    if not os.path.exists(IMAGE_PATH):
        print(f"Image not found at {IMAGE_PATH}")
        return

    print(f"Testing Face Enrollment with {IMAGE_PATH}...")
    
    with open(IMAGE_PATH, "rb") as f:
        files = {"file": ("test.png", f, "image/png")}
        data = {
            "name": "Test User",
            "category": "KNOWN",
            "meta_info": '{"test": "true"}'
        }
        
        try:
            response = requests.post(API_URL, files=files, data=data)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code == 201:
                print("✅ Face Registered Successfully!")
            elif response.status_code == 400 and "No face detected" in response.text:
                print("✅ Connection Successful! (Correctly rejected image with no face)")
            elif response.status_code == 500 or response.status_code == 503:
                print("❌ Server Error - Connection Failed")
            else:
                print(f"⚠️ Unexpected Response: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_face_enrollment()
