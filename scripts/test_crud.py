import requests
import uuid
import json

BASE_URL = "http://localhost:8003"

def test_crud():
    print("=== Testing User Management CRUD ===")
    
    # 1. System Summary
    print("\n[GET] /system/summary")
    r = requests.get(f"{BASE_URL}/system/summary")
    print(f"Status: {r.status_code}")
    print(f"Response: {r.json()}")
    assert r.status_code == 200
    
    # 2. Create Permission
    print("\n[POST] /permissions")
    perm_slug = f"test:perm:{uuid.uuid4().hex[:8]}"
    payload = {"slug": perm_slug, "description": "Test Permission"}
    r = requests.post(f"{BASE_URL}/permissions", json=payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.json()}")
    assert r.status_code == 200
    perm_id = r.json()["id"]
    
    # 3. Create Role
    print("\n[POST] /roles")
    role_code = f"test_role_{uuid.uuid4().hex[:8]}"
    payload = {
        "code": role_code,
        "name": "Test Role",
        "description": "Test Role Desc",
        "permission_ids": [perm_id]
    }
    r = requests.post(f"{BASE_URL}/roles", json=payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.json()}")
    assert r.status_code == 200
    role_id = r.json()["id"]
    
    # 4. Create User
    print("\n[POST] /users")
    username = f"user_{uuid.uuid4().hex[:8]}"
    payload = {
        "username": username,
        "email": f"{username}@example.com",
        "password": "password123",
        "full_name": "Test User",
        "role_id": role_id
    }
    r = requests.post(f"{BASE_URL}/users", json=payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.json()}")
    assert r.status_code == 200
    user_id = r.json()["id"]
    
    # 5. Verify Relationships
    print("\n[GET] /users/{id}")
    r = requests.get(f"{BASE_URL}/users/{user_id}")
    data = r.json()
    print(f"User Role: {data.get('role', {}).get('code')}")
    assert data['role']['id'] == role_id
    assert data['role']['permissions'][0]['id'] == perm_id
    
    # 6. Cleanup
    print("\n[DELETE] Cleanup")
    requests.delete(f"{BASE_URL}/users/{user_id}")
    requests.delete(f"{BASE_URL}/roles/{role_id}")
    requests.delete(f"{BASE_URL}/permissions/{perm_id}")
    print("Cleanup complete.")
    
    print("\n✅ All CRUD tests passed!")

if __name__ == "__main__":
    try:
        test_crud()
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        exit(1)
