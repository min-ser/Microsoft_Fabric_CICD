import argparse, requests, base64, os, time

# ================= DEBUG =================
def debug(msg):
    print(f"[DEBUG] {msg}")

# ================= HTTP =================
def api_get(url, headers):
    r = requests.get(url, headers=headers)
    debug(f"GET {url} -> {r.status_code}")
    if r.status_code != 200:
        print(r.text)
    return r

def api_post(url, headers, payload):
    r = requests.post(url, headers=headers, json=payload)
    debug(f"POST {url} -> {r.status_code}")
    if r.status_code not in [200,201,202]:
        print(r.text)
    return r

# ================= ITEM POLLING =================
def wait_for_item(headers, workspace_id, name, timeout=120):
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"
    start = time.time()

    while time.time() - start < timeout:
        items = api_get(url, headers).json().get("value", [])
        for i in items:
            if i["displayName"] == name:
                print(f"✅ Item visible: {name} -> {i['id']}")
                return i["id"]

        print(f"⏳ Waiting item visibility: {name}")
        time.sleep(3)

    print(f"❌ Timeout waiting item: {name}")
    return None

# ================= FOLDER APIs =================
def get_all_folders(headers, workspace_id):
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/folders?recursive=true"
    r = api_get(url, headers)
    return r.json().get("value", [])

def create_folder(headers, workspace_id, name, parent_id=None):
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/folders"
    payload = {"displayName": name}
    if parent_id:
        payload["parentFolderId"] = parent_id

    r = api_post(url, headers, payload)
    if r.status_code in [200,201,202]:
        fid = r.json()["id"]
        print(f"📁 Folder Created: {name} -> {fid}")
        return fid
    return None

def ensure_folder_path(headers, workspace_id, path):
    """
    Ensure nested folder path exists (TEST_TARGET/test/sub)
    """
    folders = get_all_folders(headers, workspace_id)
    parts = path.split("/")
    parent = None

    for p in parts:
        found = None
        for f in folders:
            if f["displayName"] == p and f.get("parentFolderId") == parent:
                found = f
                break

        if not found:
            print(f"⚠️ Folder missing, creating: {p}")
            fid = create_folder(headers, workspace_id, p, parent)
            found = {"id": fid, "displayName": p, "parentFolderId": parent}
            folders.append(found)

        parent = found["id"]

    print(f"✅ Folder Path Resolved: {path} -> {parent}")
    return parent

# ================= DEPLOY =================
def deploy(token, workspace_id, notebook_path, folder_path):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    name = os.path.basename(notebook_path).replace(".ipynb","")

    print(f"\n🚀 Deploy Notebook: {name}")

    with open(notebook_path,"rb") as f:
        content = base64.b64encode(f.read()).decode()

    list_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"

    items = api_get(list_url, headers).json().get("value", [])
    existing = next((i for i in items if i["displayName"] == name), None)

    # CREATE OR UPDATE
    if existing:
        item_id = existing["id"]
        print(f"🔄 Update notebook: {name}")
        url = f"{list_url}/{item_id}/updateDefinition"
        payload = {"definition":{"parts":[{"path":"notebook-content.ipynb","payload":content,"payloadType":"InlineBase64"}]}}
        api_post(url, headers, payload)
    else:
        print(f"✨ Create notebook: {name}")
        payload = {
            "displayName": name,
            "type": "Notebook",
            "definition": {"format":"ipynb","parts":[{"path":"notebook-content.ipynb","payload":content,"payloadType":"InlineBase64"}]}
        }
        api_post(list_url, headers, payload)
        item_id = wait_for_item(headers, workspace_id, name)

    if not item_id:
        print("❌ item_id missing")
        return

    print(f"✅ Deploy OK: {item_id}")

    # ENSURE FOLDER TREE
    folder_id = ensure_folder_path(headers, workspace_id, folder_path)

    # MOVE
    move_url = f"{list_url}/{item_id}/move"
    payload = {"targetFolderId": folder_id}
    api_post(move_url, headers, payload)
    print(f"✅ Move Success -> {folder_path}")

# ================= MAIN =================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()

    debug(f"Token length={len(args.token)}")
    debug(f"Workspace={args.workspace}")
    debug(f"File={args.file}")
    debug(f"Folder={args.folder}")

    deploy(args.token, args.workspace, args.file, args.folder)