"""
OneDrive (Microsoft Graph) cloud storage backend.

Files are stored in a Microsoft OneDrive account via Microsoft Graph API
so they are reachable from any client instance.

Configuration is dynamically loaded from the MySQL database (admin_settings table)
with fallback to environment variables:
    ONEDRIVE_KEY / ONEDRIVE_CLIENT_SECRET - OneDrive API Key / Client Secret
    ONEDRIVE_CLIENT_ID                   - Azure AD application (client) ID
    ONEDRIVE_TENANT_ID                   - Directory (tenant) ID (default: common)
    ONEDRIVE_FOLDER                      - Root folder in OneDrive (default: rey_chat)
"""

import os
import time
import json
import mimetypes
import requests
import mysql.connector

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
DEVICE_CODE_URL_TPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"
DEFAULT_CLIENT_ID = "a2373e8f-a275-4247-b4ee-9750866b72d7"
DEFAULT_SCOPES = "offline_access Files.ReadWrite Files.ReadWrite.All User.Read"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "mysql-21f1e29c-reydmdeveloper-2e13.i.aivencloud.com"),
    "port": int(os.environ.get("DB_PORT", 17090)),
    "user": os.environ.get("DB_USER", "avnadmin"),
    "password": os.environ.get("DB_PASSWORD", "AVNS_l-v67tdYKfQUCJZmrp9"),
    "database": os.environ.get("DB_NAME", "reydm_db"),
}


def _get_db():
    try:
        return mysql.connector.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            connection_timeout=5,
        )
    except Exception:
        return None


def get_config():
    """Retrieve OneDrive configuration from database (admin_settings) or environment."""
    config = {
        "key": os.environ.get("ONEDRIVE_KEY") or os.environ.get("ONEDRIVE_CLIENT_SECRET", ""),
        "client_id": os.environ.get("ONEDRIVE_CLIENT_ID", DEFAULT_CLIENT_ID),
        "client_secret": os.environ.get("ONEDRIVE_CLIENT_SECRET") or os.environ.get("ONEDRIVE_KEY", ""),
        "tenant_id": os.environ.get("ONEDRIVE_TENANT_ID", "common"),
        "folder": os.environ.get("ONEDRIVE_FOLDER", "rey_chat").strip("/") or "rey_chat",
        "refresh_token": "",
        "access_token": "",
        "token_expires_at": 0,
        "account_name": "",
        "drive_id": "",
    }

    try:
        conn = _get_db()
        if conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'onedrive_config'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row and row.get("setting_value"):
                db_cfg = json.loads(row["setting_value"])
                if isinstance(db_cfg, dict):
                    for k, v in db_cfg.items():
                        if v is not None:
                            config[k] = v
                            if k == "key" and not config.get("client_secret"):
                                config["client_secret"] = str(v).strip()
    except Exception:
        pass

    if not config.get("client_id"):
        config["client_id"] = DEFAULT_CLIENT_ID
    if not config.get("tenant_id"):
        config["tenant_id"] = "common"
    if not config.get("folder"):
        config["folder"] = "rey_chat"

    return config


def save_config(new_config):
    """Save or update OneDrive config in admin_settings table."""
    conn = _get_db()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO admin_settings (setting_key, setting_value, updated_at)
            VALUES ('onedrive_config', %s, NOW())
            ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), updated_at = NOW()
        """, (json.dumps(new_config),))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception:
        if conn:
            conn.close()
        return False


def is_available():
    """True if OneDrive key/credentials or OAuth tokens are configured."""
    cfg = get_config()
    return bool(cfg.get("refresh_token") or cfg.get("access_token") or cfg.get("key") or cfg.get("client_secret"))


def start_device_code(client_id=None, tenant_id=None):
    """Start Microsoft Device Code authorization flow."""
    cfg = get_config()
    cid = (client_id or cfg.get("client_id") or DEFAULT_CLIENT_ID).strip()
    tid = (tenant_id or cfg.get("tenant_id") or "common").strip()
    
    url = DEVICE_CODE_URL_TPL.format(tenant=tid)
    data = {
        "client_id": cid,
        "scope": DEFAULT_SCOPES,
    }
    r = requests.post(url, data=data, timeout=20)
    if r.status_code != 200:
        raise ValueError(f"Failed to start device flow ({r.status_code}): {r.text}")
    return r.json()


def poll_device_code(device_code, client_id=None, tenant_id=None):
    """Poll Microsoft OAuth token endpoint for Device Code completion."""
    cfg = get_config()
    cid = (client_id or cfg.get("client_id") or DEFAULT_CLIENT_ID).strip()
    tid = (tenant_id or cfg.get("tenant_id") or "common").strip()

    url = TOKEN_URL_TPL.format(tenant=tid)
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "client_id": cid,
        "device_code": device_code,
    }
    r = requests.post(url, data=data, timeout=20)
    res = r.json()

    if r.status_code == 200:
        access_token = res.get("access_token", "")
        refresh_token = res.get("refresh_token", "")
        expires_in = int(res.get("expires_in", 3600))
        expires_at = time.time() + expires_in - 60

        account_name = ""
        try:
            h = {"Authorization": f"Bearer {access_token}"}
            user_r = requests.get(f"{GRAPH}/me", headers=h, timeout=10)
            if user_r.status_code == 200:
                user_data = user_r.json()
                account_name = user_data.get("displayName") or user_data.get("userPrincipalName") or user_data.get("mail") or ""
        except Exception:
            pass

        cfg["access_token"] = access_token
        cfg["refresh_token"] = refresh_token
        cfg["token_expires_at"] = expires_at
        cfg["account_name"] = account_name
        cfg["client_id"] = cid
        cfg["tenant_id"] = tid
        save_config(cfg)

        return {
            "status": "success",
            "account_name": account_name,
            "message": f"Connected to Microsoft Account: {account_name or 'OneDrive User'}"
        }

    err = res.get("error", "")
    if err == "authorization_pending":
        return {"status": "pending", "message": "Waiting for user to enter code at microsoft.com/device..."}
    elif err == "authorization_declined":
        return {"status": "declined", "message": "Authorization was declined by the user."}
    elif err == "expired_token":
        return {"status": "expired", "message": "The login code expired. Please start over."}
    else:
        return {"status": "error", "message": res.get("error_description", r.text)}


def _get_token(custom_config=None):
    """Obtain valid Microsoft Graph OAuth2 bearer access token."""
    cfg = custom_config or get_config()
    refresh_token = (cfg.get("refresh_token") or "").strip()
    access_token = (cfg.get("access_token") or "").strip()
    expires_at = float(cfg.get("token_expires_at") or 0)
    key = (cfg.get("key") or cfg.get("client_secret") or "").strip()
    client_id = (cfg.get("client_id") or DEFAULT_CLIENT_ID).strip()
    tenant_id = (cfg.get("tenant_id") or "common").strip()

    if access_token and time.time() < expires_at:
        return access_token

    if refresh_token:
        url = TOKEN_URL_TPL.format(tenant=tenant_id)
        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "scope": DEFAULT_SCOPES,
        }
        r = requests.post(url, data=data, timeout=30)
        if r.status_code == 200:
            res = r.json()
            new_acc = res.get("access_token")
            new_ref = res.get("refresh_token") or refresh_token
            new_exp = time.time() + int(res.get("expires_in", 3600)) - 60
            
            cfg["access_token"] = new_acc
            cfg["refresh_token"] = new_ref
            cfg["token_expires_at"] = new_exp
            if not custom_config:
                save_config(cfg)
            return new_acc

    if (key.startswith("eyJ") or key.startswith("Ew") or len(key) > 400) and not (client_id and tenant_id and tenant_id not in ("common", "consumers")):
        return key

    if key and client_id:
        if not tenant_id or tenant_id.lower() in ("common", "consumers"):
            return key

        url = TOKEN_URL_TPL.format(tenant=tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": key,
            "scope": "https://graph.microsoft.com/.default",
        }
        r = requests.post(url, data=data, timeout=30)
        if r.status_code != 200:
            try:
                error_data = r.json()
                error_desc = error_data.get("error_description") or error_data.get("error") or r.text
            except Exception:
                error_desc = r.text[:250]
                
            if "AADSTS7000215" in error_desc:
                error_desc = "Invalid Secret: You copied the 'Secret ID' instead of 'Value'. In Azure Portal > Certificates & secrets, copy from the 'Value' column."
            elif "AADSTS700016" in error_desc:
                error_desc = "Application ID not found. Please check Client ID."
            elif "AADSTS90002" in error_desc:
                error_desc = "Tenant not found. Please check Directory (tenant) ID."

            raise ValueError(f"Microsoft OAuth Error ({r.status_code}): {error_desc}")
        return r.json()["access_token"]

    if key:
        return key

    raise ValueError("OneDrive is not configured. Please link your Microsoft Account or enter your API Key.")


def _get_drive_base_url(token, cfg=None):
    """Detect appropriate drive base URL for either personal/delegated or application tokens."""
    h = {"Authorization": f"Bearer {token}"}
    
    try:
        r = requests.get(f"{GRAPH}/me/drive", headers=h, timeout=10)
        if r.status_code == 200:
            return f"{GRAPH}/me/drive"
    except Exception:
        pass

    config = cfg or get_config()
    drive_id = config.get("drive_id")
    if drive_id:
        return f"{GRAPH}/drives/{drive_id}"

    try:
        r = requests.get(f"{GRAPH}/drives", headers=h, timeout=10)
        if r.status_code == 200:
            drives = r.json().get("value", [])
            if drives:
                return f"{GRAPH}/drives/{drives[0]['id']}"
    except Exception:
        pass

    return f"{GRAPH}/me/drive"


def test_connection(custom_config=None):
    """Test OneDrive connectivity and return (success, message)."""
    try:
        cfg = custom_config or get_config()
        token = _get_token(custom_config)
        h = {"Authorization": f"Bearer {token}"}
        
        endpoints = [
            f"{GRAPH}/me/drive/root",
            f"{GRAPH}/me/drive",
            f"{GRAPH}/me",
            f"{GRAPH}/drives",
            f"{GRAPH}/drive/root",
            f"{GRAPH}/organization",
        ]
        
        account_name = cfg.get("account_name") or ""
        for ep in endpoints:
            try:
                r = requests.get(ep, headers=h, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    name = data.get("displayName") or data.get("name") or data.get("userPrincipalName") or account_name or "Connected"
                    return True, f"Successfully authenticated with Microsoft Graph & OneDrive! ({name})"
            except Exception:
                pass

        return True, "Successfully authenticated with Microsoft OAuth token!"
    except Exception as e:
        return False, f"{str(e)}"


def _headers(token, content_type=None):
    h = {"Authorization": f"Bearer {token}"}
    if content_type:
        h["Content-Type"] = content_type
    return h


def _ensure_folder_path(token, root_folder="rey_chat"):
    """Resolve (creating if needed) the root_folder path, return its id."""
    drive_url = _get_drive_base_url(token)
    parent_id = "root"
    if not root_folder:
        return parent_id
    for name in root_folder.strip("/").split("/"):
        if not name:
            continue
        url = f"{drive_url}/items/{parent_id}/children"
        r = requests.get(url, headers=_headers(token), timeout=30)
        r.raise_for_status()
        existing = next((i for i in r.json().get("value", [])
                         if i.get("name") == name and "folder" in i), None)
        if existing:
            parent_id = existing["id"]
        else:
            body = {
                "name": name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename",
            }
            r = requests.post(url, headers=_headers(token, "application/json"),
                              json=body, timeout=30)
            r.raise_for_status()
            parent_id = r.json()["id"]
    return parent_id


def _descend(token, parent_id, subfolder):
    """Descend into subfolder segments under parent_id, creating as needed."""
    if not subfolder:
        return parent_id
    drive_url = _get_drive_base_url(token)
    for name in subfolder.strip("/").split("/"):
        if not name:
            continue
        url = f"{drive_url}/items/{parent_id}/children"
        r = requests.get(url, headers=_headers(token), timeout=30)
        r.raise_for_status()
        existing = next((i for i in r.json().get("value", [])
                         if i.get("name") == name and "folder" in i), None)
        if existing:
            parent_id = existing["id"]
        else:
            r = requests.post(url, headers=_headers(token, "application/json"),
                              json={"name": name, "folder": {},
                                    "@microsoft.graph.conflictBehavior": "rename"},
                              timeout=30)
            r.raise_for_status()
            parent_id = r.json()["id"]
    return parent_id


def upload_file(filename, data, subfolder=""):
    """Upload bytes `data` as `filename` under ROOT_FOLDER/[subfolder].
    Returns a storage reference string like 'od:<itemId>'."""
    cfg = get_config()
    root_folder = cfg.get("folder", "rey_chat")
    token = _get_token()
    drive_url = _get_drive_base_url(token, cfg)
    
    parent_id = _ensure_folder_path(token, root_folder)
    parent_id = _descend(token, parent_id, subfolder)

    ct = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    url = (f"{drive_url}/items/{parent_id}:/{filename}:/content"
           f"?@microsoft.graph.conflictBehavior=rename")
    r = requests.put(url, headers=_headers(token, ct),
                      data=data, timeout=300)
    r.raise_for_status()
    item = r.json()
    return "od:" + item["id"]


def download_file(ref):
    """Given 'od:<itemId>', return (bytes, content_type, filename)."""
    item_id = ref[len("od:"):] if ref.startswith("od:") else ref
    token = _get_token()
    drive_url = _get_drive_base_url(token)
    
    meta = requests.get(f"{drive_url}/items/{item_id}",
                        headers=_headers(token), timeout=30)
    meta.raise_for_status()
    name = meta.json().get("name", "file")
    ct = meta.json().get("file", {}).get("mimeType", "application/octet-stream")
    dl = requests.get(f"{drive_url}/items/{item_id}/content",
                       headers=_headers(token), timeout=300)
    dl.raise_for_status()
    return dl.content, ct, name


def open_url(ref):
    """Return a temporary view link or download link for inline preview/streaming."""
    item_id = ref[len("od:"):] if ref.startswith("od:") else ref
    token = _get_token()
    drive_url = _get_drive_base_url(token)
    
    try:
        r = requests.get(f"{drive_url}/items/{item_id}", headers=_headers(token), timeout=15)
        if r.status_code == 200:
            dl_url = r.json().get("@microsoft.graph.downloadUrl")
            if dl_url:
                return dl_url
            web_url = r.json().get("webUrl")
            if web_url:
                return web_url
    except Exception:
        pass

    try:
        r = requests.post(f"{drive_url}/items/{item_id}/createLink",
                          headers=_headers(token, "application/json"),
                          json={"type": "view", "scope": "anonymous"},
                          timeout=30)
        if r.status_code in (200, 201):
            return r.json().get("link", {}).get("webUrl")
    except Exception:
        pass

    return f"/api/chat/download/{ref}"
