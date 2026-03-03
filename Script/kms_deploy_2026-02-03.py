#!/usr/bin/env python3
import sys
import argparse
import requests
import base64
import os
import time
import json

DEBUG = True

def log(msg):
    print(msg, flush=True)

def print_error_details(response, context):
    if response is None:
        log(f"❌ {context}: Network Error (response=None)")
        return
    log(f"❌ {context} 실패 (HTTP {response.status_code})")
    try:
        err = response.json()
        log(f"   - errorCode: {err.get('errorCode')}")
        log(f"   - message: {err.get('message')}")
        log(f"   - requestId: {err.get('requestId')}")
    except:
        log(f"   - raw: {response.text}")

# --------------------------------------
# 🔎 LIST ALL ITEMS WITH PAGINATION
# --------------------------------------
def list_all_items(headers, workspace_id):
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"
    all_items = []
    page = 0

    while url:
        page += 1
        log(f"📡 Fetching items page {page}: {url}")
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print_error_details(resp, "List Items")
            return []

        data = resp.json()
        items = data.get("value", [])
        all_items.extend(items)

        token = data.get("continuationToken")
        url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items?continuationToken={token}" if token else None

    log(f"✅ Total items fetched: {len(all_items)}")
    return all_items

# --------------------------------------
# 🔎 FIND FOLDER ID
# --------------------------------------
def get_folder_id(headers, workspace_id, folder_name):
    items = list_all_items(headers, workspace_id)

    log("📂 DEBUG: Workspace Folder List")
    for i in items:
        if i.get("type") == "Folder":
            log(f"   - {i['displayName']} (ID={i['id']})")

    for i in items:
        if i.get("type") == "Folder" and i.get("displayName", "").strip() == folder_name.strip():
            log(f"🎯 Folder FOUND: {folder_name} -> {i['id']}")
            return i["id"]

    log(f"❌ Folder '{folder_name}' NOT FOUND")
    return None

# --------------------------------------
# 🚚 MOVE ITEM
# --------------------------------------
def move_item(headers, workspace_id, item_id, folder_id):
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items/{item_id}/move"
    payload = {"targetFolderId": folder_id}

    time.sleep(5)  # Fabric eventual consistency

    log(f"📦 Moving item {item_id} -> folder {folder_id}")
    resp = requests.post(url, headers=headers, json=payload)

    if resp.status_code == 200:
        log("✅ Move Success")
    else:
        print_error_details(resp, "Move Item API")

# --------------------------------------
# 🚀 DEPLOY NOTEBOOK
# --------------------------------------
def deploy(token, workspace_id, notebook_path, folder_name):
    notebook_name = os.path.basename(notebook_path).replace(".ipynb", "")
    log(f"\n🚀 Deploy Notebook: {notebook_name}")

    with open(notebook_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    base_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items"

    # 1️⃣ Find Folder ID
    folder_id = get_folder_id(headers, workspace_id, folder_name)

    # 2️⃣ Check Existing Item
    items = list_all_items(headers, workspace_id)
    existing = next((i for i in items if i.get("displayName") == notebook_name), None)

    item_id = None
    res = None

    # 3️⃣ Update or Create
    if existing:
        log(f"🔄 Updating existing notebook: {notebook_name}")
        url = f"{base_url}/{existing['id']}/updateDefinition"
        payload = {
            "definition": {
                "parts": [{"path": "notebook-content.ipynb", "payload": content, "payloadType": "InlineBase64"}]
            }
        }
        res = requests.post(url, headers=headers, json=payload)
        item_id = existing["id"]
    else:
        log(f"✨ Creating new notebook: {notebook_name}")
        payload = {
            "displayName": notebook_name,
            "type": "Notebook",
            "definition": {
                "format": "ipynb",
                "parts": [{"path": "notebook-content.ipynb", "payload": content, "payloadType": "InlineBase64"}]
            }
        }
        res = requests.post(base_url, headers=headers, json=payload)
        if res.status_code in [200, 201, 202]:
            item_id = res.json().get("id")

    # 4️⃣ Deploy Result Check
    if res is None or res.status_code not in [200, 201, 202]:
        print_error_details(res, "Deploy Notebook")
        return

    log(f"✅ Deploy Success: item_id={item_id}")

    # 5️⃣ Move if folder exists
    if folder_id:
        move_item(headers, workspace_id, item_id, folder_id)
    else:
        log("⚠️ Folder NOT FOUND → Move SKIPPED (Root artifact created)")

    log(f"🏁 Done: {notebook_name}\n")

# --------------------------------------
# MAIN
# --------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()

    deploy(args.token, args.workspace, args.file, args.folder)
