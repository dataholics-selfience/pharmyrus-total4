from datetime import datetime
import json
import os

FILE = "/tmp/serpapi_pool.json"

KEYS = [
    {"key": "11e7b23032aae12b0f75c06af0ad60a861e9f7ea6d53fc7ca039aed18b5e3573", "name": "daniel", "used": 250},
    {"key": "3f22448f4d43ce8259fa2f7f6385222323a67c4ce4e72fcc774b43d23812889d", "name": "innova2", "used": 0},
    {"key": "871b533d956978e967e7621c871d53fb448bc36e90af6389eda2aca3420236e1", "name": "innova3", "used": 0},
    {"key": "81a36621f3efc12ca9bdd1c0dbcc30d3ab2f2dea5f9e42af3508ff04ee8ed527", "name": "keith", "used": 0},
    {"key": "bc20bca64032a7ac59abf330bbdeca80aa79cd72bb208059056b10fb6e33e4bc", "name": "lg", "used": 250},
    {"key": "5e7943e3a4832058ab4f430b46e29c7e2cf3522b50e7aba2f19bea45c480c790", "name": "clinica", "used": 0},
    {"key": "67ea379386129b7f25f2af88e78aa6a195800b2b7750038b9062743623304769", "name": "deny", "used": 0},
    {"key": "3b7a505775aefec905ce2d7172ad54bba2f7fd8f40ee2aabae153e187c0c9407", "name": "jojo", "used": 0},
    {"key": "b2131edaf44437a4a424af07de23bfe5186c1d5897231f54d388c64ac3d33670", "name": "nova", "used": 0}
]

def load():
    if os.path.exists(FILE):
        with open(FILE) as f:
            return json.load(f)
    return {"keys": KEYS, "month": datetime.now().strftime("%Y-%m")}

def save(data):
    with open(FILE, 'w') as f:
        json.dump(data, f)

def reset_month(data):
    current = datetime.now().strftime("%Y-%m")
    if data.get("month") != current:
        for k in data["keys"]:
            if k["used"] == 250:
                k["used"] = 0
        data["month"] = current
        save(data)
    return data

def get_key():
    data = load()
    data = reset_month(data)
    
    for k in data["keys"]:
        if k["used"] < 250:
            k["used"] += 1
            save(data)
            print(f"✓ {k['name']}: {k['used']}/250")
            return k["key"]
    
    print("✗ All exhausted")
    return data["keys"][0]["key"]

def status():
    data = load()
    data = reset_month(data)
    return {
        "keys": data["keys"],
        "available": sum(1 for k in data["keys"] if k["used"] < 250),
        "used_total": sum(k["used"] for k in data["keys"]),
        "capacity": len(data["keys"]) * 250
    }
