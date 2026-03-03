# Fabric CI/CD

## 1. Gitlab 환경변수 등록
변수명 | 설명 | 비고
------|-----|-----
AZURE_SERVICE_PRINCIPAL_ID  | Azure AD 앱 등록의 클라이언트 ID (Application ID) | az login --username에 사용
AZURE_SERVICE_PRINCIPAL_PWD | 앞서 확인하신 클라이언트 암호 (Client Secret)	     | Masked 옵션 권장 (로그 노출 방지)
AZURE_TENANT_ID             | Azure 테넌트 ID (Directory ID)                  |az login --tenant에 사용
FABRIC_WORKSPACE_ID         | 배포 대상이 되는 Fabric 워크스페이스의 GUID        |Fabric URL에서 확인 가능

## 2. gitlab-ci.yml
1. 워크스페이스내에 생성된 폴더를 워크스페이스로 사용하는 방식
```yml
fabric-deployment:
  stage: deploy
  image: <Gitlab runner 이미지>
  tags: [docker]

  variables:
    SOURCE_DIR: "<로컬 워크스페이스 폴더명>"
    TARGET_ROOT: "<Fabric 워크스페이스내 폴더명>"
    DEPLOY_SCRIPT: "Script/deployment.py"

  script:
    - echo "1. Python Dependency Install"
    - pip3 install requests --break-system-packages || true

    - echo "2. Check Deploy Files"
    - |
      COUNT=$(find "$SOURCE_DIR" -name "*.ipynb" | wc -l)
      echo "Notebook Count = $COUNT"
      if [ "$COUNT" -eq 0 ]; then
        echo "❌ No notebooks found"
        exit 1
      fi

    - echo "3. Azure Login"
    - |
      az login --service-principal \
        --username "$AZURE_SERVICE_PRINCIPAL_ID" \
        --password "$AZURE_SERVICE_PRINCIPAL_PWD" \
        --tenant "$AZURE_TENANT_ID" \
        --allow-no-subscriptions

    - echo "4. Get Fabric Token"
    - |
      export FABRIC_TOKEN=$(az account get-access-token \
        --resource https://api.fabric.microsoft.com \
        --query accessToken -o tsv)

      echo "FABRIC_TOKEN length: $(echo $FABRIC_TOKEN | wc -c)"
      echo "WORKSPACE_ID=$FABRIC_WORKSPACE_ID"

    - echo "5. Deploy to Fabric"
    - |
      export IFS=$'\n'
      for file_path in $(find "$SOURCE_DIR" -name "*.ipynb"); do
        
        REL_DIR=$(dirname "$file_path" | sed "s|^$SOURCE_DIR||" | sed 's|^/||')

        if [ -z "$REL_DIR" ]; then
          FINAL_FOLDER="$TARGET_ROOT"
        else
          FINAL_FOLDER="$TARGET_ROOT/$REL_DIR"
        fi

        echo "🚀 Deploying $file_path -> $FINAL_FOLDER"

        python3 "$DEPLOY_SCRIPT" \
          --token "$FABRIC_TOKEN" \
          --workspace "$FABRIC_WORKSPACE_ID" \
          --file "$file_path" \
          --folder "$FINAL_FOLDER"
      done

  allow_failure: false
```

2. 워크스페이스를 최상위로 사용하는 방식
```yml
fabric-deployment:
  stage: deploy
  # 2025년 1월자 Azure CLI 이미지 사용
  image: <Gitlab runner 이미지>
  tags: [docker]

  variables:
    SOURCE_DIR: "<로컬 워크스페이스 폴더명>"
    TARGET_ROOT: ""
    DEPLOY_SCRIPT: "Script/deployment.py"

  script:
    - echo "1. Python Dependency Install"
    - pip3 install requests --break-system-packages || true

    - echo "2. Check Deploy Files"
    - |
      COUNT=$(find "$SOURCE_DIR" -name "*.ipynb" | wc -l)
      echo "Notebook Count = $COUNT"
      if [ "$COUNT" -eq 0 ]; then
        echo "❌ No notebooks found in $SOURCE_DIR"
        exit 1
      fi

    - echo "3. Azure Login"
    - |
      az login --service-principal \
        --username "$AZURE_SERVICE_PRINCIPAL_ID" \
        --password "$AZURE_SERVICE_PRINCIPAL_PWD" \
        --tenant "$AZURE_TENANT_ID" \
        --allow-no-subscriptions

    - echo "4. Get Fabric Token"
    - |
      export FABRIC_TOKEN=$(az account get-access-token \
        --resource https://api.fabric.microsoft.com \
        --query accessToken -o tsv)

      echo "FABRIC_TOKEN length: $(echo $FABRIC_TOKEN | wc -c)"
      echo "TARGET_WORKSPACE_ID=$FABRIC_WORKSPACE_ID"

    - echo "5. Deploy to Fabric (Workspace Root)"
    - |
      export IFS=$'\n'
      # SOURCE_DIR 내부의 모든 .ipynb 파일을 찾아 for문 실행
      for file_path in $(find "$SOURCE_DIR" -name "*.ipynb"); do
        
        # SOURCE_DIR 이후의 상대 경로만 추출
        # 예: DeployFile/SubFolder/test.ipynb -> SubFolder
        REL_DIR=$(dirname "$file_path" | sed "s|^$SOURCE_DIR||" | sed 's|^/||')

        if [ -z "$REL_DIR" ]; then
          FINAL_FOLDER=""
        else
          FINAL_FOLDER="$REL_DIR"
        fi

        echo "🚀 Deploying: $file_path"
        echo "📍 Destination: Workspace Root/${FINAL_FOLDER:- (Root)}"

        python3 "$DEPLOY_SCRIPT" \
          --token "$FABRIC_TOKEN" \
          --workspace "$FABRIC_WORKSPACE_ID" \
          --file "$file_path" \
          --folder "$FINAL_FOLDER"
      done

  allow_failure: false
```

## 폴더 미러전략 파이썬 코드
- deploy.py
```python
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
```

## 사용하지 않음
- get_token.py
```python
from azure.identity import ClientSecretCredential
import os

tenant = os.getenv("AZURE_TENANT_ID")
client = os.getenv("AZURE_CLIENT_ID")
secret = os.getenv("AZURE_CLIENT_SECRET")

cred = ClientSecretCredential(tenant, client, secret)
token = cred.get_token("https://api.fabric.microsoft.com/.default").token

print(f"FABRIC_TOKEN={token}")
with open("fabric.env","w") as f:
    f.write(f"FABRIC_TOKEN={token}")
```