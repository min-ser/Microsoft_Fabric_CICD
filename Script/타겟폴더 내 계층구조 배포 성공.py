import argparse, requests, base64, os, time

# ======================
# UTIL
# ======================
def debug(msg):
    print(f"[DEBUG] {msg}")

def api_get(url, headers):
    r = requests.get(url, headers=headers)
    debug(f"GET {url} -> {r.status_code}")
    return r

def api_post(url, headers, payload):
    r = requests.post(url, headers=headers, json=payload)
    debug(f"POST {url} -> {r.status_code}")
    if r.status_code not in [200,201,202]:
        print(r.text)
    return r

# ======================
# FOLDER TREE LOAD
# ======================
def load_all_folders(headers, workspace_id):
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/folders?recursive=true"
    r = api_get(url, headers)
    return r.json().get("value", [])

# ======================
# PATH -> FOLDER ID
# ======================
def get_folder_id_by_path(headers, workspace_id, path):
    folders = load_all_folders(headers, workspace_id)
    parts = path.split("/")
    parent = None

    for part in parts:
        found = None
        for f in folders:
            if f["displayName"] == part and f.get("parentFolderId") == parent:
                found = f
                break
        if not found:
            print(f"❌ Folder not found: {path}")
            return None
        parent = found["id"]

    print(f"✅ Folder Path Resolved: {path} -> {parent}")
    return parent

# ======================
# WAIT ITEM
# ======================
def wait_for_item(headers, workspace_id, name, timeout=120):
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"
    start = time.time()

    while time.time() - start < timeout:
        r = api_get(url, headers)
        items = r.json().get("value", [])
        for i in items:
            if i["displayName"] == name:
                print(f"✅ Item visible: {name} -> {i['id']}")
                return i["id"]

        print(f"⏳ Waiting item visibility: {name}")
        time.sleep(3)

    print(f"❌ Timeout waiting item: {name}")
    return None

# ======================
# DEPLOY
# ======================
def deploy(token, workspace_id, notebook_path, folder_path):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    name = os.path.basename(notebook_path).replace(".ipynb","")

    print(f"\n🚀 Deploy Notebook: {name}")

    with open(notebook_path,"rb") as f:
        content = base64.b64encode(f.read()).decode()

    list_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"

    # Check existing
    items = api_get(list_url, headers).json().get("value", [])
    existing = next((i for i in items if i["displayName"] == name), None)

    # CREATE / UPDATE
    if existing:
        item_id = existing["id"]
        print(f"🔄 Update notebook: {name}")
        url = f"{list_url}/{item_id}/updateDefinition"
        payload = {"definition":{"parts":[{"path":"notebook-content.ipynb","payload":content,"payloadType":"InlineBase64"}]}}
        api_post(url, headers, payload)
    else:
        print(f"✨ Create notebook: {name}")
        payload = {
            "displayName":name,
            "type":"Notebook",
            "definition":{"format":"ipynb","parts":[{"path":"notebook-content.ipynb","payload":content,"payloadType":"InlineBase64"}]}
        }
        api_post(list_url, headers, payload)
        item_id = wait_for_item(headers, workspace_id, name)

    if not item_id:
        print("❌ item_id not found")
        return

    print(f"✅ Deploy OK: {item_id}")

    # MOVE TO TARGET FOLDER
    folder_id = get_folder_id_by_path(headers, workspace_id, folder_path)
    if not folder_id:
        print(f"⚠️ Folder missing: {folder_path}")
        return

    move_url = f"{list_url}/{item_id}/move"
    payload = {"targetFolderId": folder_id}
    api_post(move_url, headers, payload)
    print(f"✅ Move Success -> {folder_path}")

# ======================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()

    deploy(args.token, args.workspace, args.file, args.folder)