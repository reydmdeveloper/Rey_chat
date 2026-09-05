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
import json
import mimetypes
import requests

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SCOPES = "https://graph.microsoft.com/.default"


def get_config():
    """Retrieve OneDrive configuration from database (admin_settings) or environment."""
    config = {
        "key": os.environ.get("ONEDRIVE_KEY") or os.environ.get("ONEDRIVE_CLIENT_SECRET", ""),
        "client_id": os.environ.get("ONEDRIVE_CLIENT_ID", ""),
        "client_secret": os.environ.get("ONEDRIVE_CLIENT_SECRET") or os.environ.get("ONEDRIVE_KEY", ""),
        "tenant_id": os.environ.get("ONEDRIVE_TENANT_ID", "common"),
        "folder": os.environ.get("ONEDRIVE_FOLDER", "rey_chat").strip("/") or "rey_chat",
    }

    try:
        from app import get_db
        conn = get_db()
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
                        if v is not None and str(v).strip():
                            config[k] = str(v).strip()
                            if k == "key" and not config.get("client_secret"):
                                config["client_secret"] = str(v).strip()
    except Exception:
        pass

    return config


def is_available():
    """True if OneDrive key/credentials are configured."""
    cfg = get_config()
    key = cfg.get("key") or cfg.get("client_secret")
    return bool(key)


def _get_token(custom_config=None):
    """Obtain Microsoft Graph OAuth2 bearer access token."""
    cfg = custom_config or get_config()
    key = (cfg.get("key") or cfg.get("client_secret") or "").strip()
    client_id = (cfg.get("client_id") or "").strip()
    tenant_id = (cfg.get("tenant_id") or "common").strip()

    if not key:
        raise ValueError("OneDrive API Key / Client Secret is missing. Please configure it in Admin Settings.")

    # Check if the key provided is already a direct access token (JWT or Microsoft token)
    if (key.startswith("eyJ") or key.startswith("Ew") or len(key) > 500) and not client_id:
        return key

    # If client_id is provided, use OAuth2 client_credentials flow
    if client_id:
        url = TOKEN_URL_TPL.format(tenant=tenant_id or "common")
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": key,
            "scope": SCOPES,
        }
        r = requests.post(url, data=data, timeout=30)
        if r.status_code != 200:
            error_data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            error_desc = error_data.get("error_description") or r.text[:250]
            raise ValueError(f"Microsoft OAuth authentication failed ({r.status_code}): {error_desc}")
        return r.json()["access_token"]

    # If only key is provided and client_id is omitted, try using key directly as Bearer token
    return key


def test_connection(custom_config=None):
    """Test OneDrive connectivity and return (success, message)."""
    try:
        token = _get_token(custom_config)
        h = {"Authorization": f"Bearer {token}"}
        
        # Test Graph API with /me/drive or /drive/root
        r = requests.get(f"{GRAPH}/me/drive/root", headers=h, timeout=15)
        if r.status_code == 200:
            drive_data = r.json()
            drive_name = drive_data.get("name", "Root")
            return True, f"Successfully connected to OneDrive! (Drive root: {drive_name})"
        
        # Try alternate tenant root endpoint
        r2 = requests.get(f"{GRAPH}/drive/root", headers=h, timeout=15)
        if r2.status_code == 200:
            return True, "Successfully connected to OneDrive Cloud Storage!"

        return False, f"Connected to Microsoft Auth, but Graph drive check returned status {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"


def _headers(token, content_type=None):
    h = {"Authorization": f"Bearer {token}"}
    if content_type:
        h["Content-Type"] = content_type
    return h


def _ensure_folder_path(token):
    """Resolve (creating if needed) the ROOT_FOLDER path, return its id."""
    parent_id = "root"
    if not ROOT_FOLDER:
        return parent_id
    for name in ROOT_FOLDER.split("/"):
        url = f"{GRAPH}/me/drive/items/{parent_id}/children"
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
    for name in subfolder.strip("/").split("/"):
        url = f"{GRAPH}/me/drive/items/{parent_id}/children"
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
    token = _get_token()
    parent_id = _ensure_folder_path(token)
    parent_id = _descend(token, parent_id, subfolder)

    ct = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    url = (f"{GRAPH}/me/drive/items/{parent_id}:/{filename}:/content"
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
    meta = requests.get(f"{GRAPH}/me/drive/items/{item_id}",
                        headers=_headers(token), timeout=30)
    meta.raise_for_status()
    name = meta.json().get("name", "file")
    ct = meta.json().get("file", {}).get("mimeType", "application/octet-stream")
    dl = requests.get(f"{GRAPH}/me/drive/items/{item_id}/content",
                       headers=_headers(token), timeout=300)
    dl.raise_for_status()
    return dl.content, ct, name


def open_url(ref):
    """Return a temporary view link for inline preview/streaming."""
    item_id = ref[len("od:"):] if ref.startswith("od:") else ref
    token = _get_token()
    r = requests.post(f"{GRAPH}/me/drive/items/{item_id}/createLink",
                      headers=_headers(token, "application/json"),
                      json={"type": "view", "scope": "organization"},
                      timeout=30)
    r.raise_for_status()
    return r.json().get("link", {}).get("webUrl")
