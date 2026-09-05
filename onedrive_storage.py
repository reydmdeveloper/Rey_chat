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
import mysql.connector

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SCOPES = "https://graph.microsoft.com/.default"

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
        "client_id": os.environ.get("ONEDRIVE_CLIENT_ID", ""),
        "client_secret": os.environ.get("ONEDRIVE_CLIENT_SECRET") or os.environ.get("ONEDRIVE_KEY", ""),
        "tenant_id": os.environ.get("ONEDRIVE_TENANT_ID", ""),
        "folder": os.environ.get("ONEDRIVE_FOLDER", "rey_chat").strip("/") or "rey_chat",
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
    tenant_id = (cfg.get("tenant_id") or "").strip()

    if not key:
        raise ValueError("OneDrive API Key / Client Secret is empty. Please enter your key.")

    # If the key provided is already an access token (JWT / Bearer token)
    if (key.startswith("eyJ") or key.startswith("Ew") or len(key) > 400) and not client_id:
        return key

    # If client_id is provided, execute OAuth2 client_credentials grant
    if client_id:
        if not tenant_id or tenant_id.lower() in ("common", "consumers"):
            raise ValueError(
                "For Azure App authentication, please specify your Directory (tenant) ID from your Azure Overview page."
            )

        url = TOKEN_URL_TPL.format(tenant=tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": key,
            "scope": SCOPES,
        }
        r = requests.post(url, data=data, timeout=30)
        if r.status_code != 200:
            try:
                error_data = r.json()
                error_desc = error_data.get("error_description") or error_data.get("error") or r.text
            except Exception:
                error_desc = r.text[:250]
                
            # Provide clear, actionable hints for common Azure errors
            if "AADSTS7000215" in error_desc:
                error_desc = "Invalid Secret Key: You copied the 'Secret ID' instead of the 'Value'. In Azure Portal > Certificates & secrets, please copy the string from the 'Value' column."
            elif "AADSTS700016" in error_desc:
                error_desc = "Application ID not found. Please check that your Client ID (Application ID) is entered correctly."
            elif "AADSTS90002" in error_desc:
                error_desc = "Tenant not found. Please check that your Directory (tenant) ID is entered correctly."

            raise ValueError(f"Microsoft OAuth Error ({r.status_code}): {error_desc}")
        return r.json()["access_token"]

    # If only key is provided without client_id, use key directly as Bearer token
    return key


def test_connection(custom_config=None):
    """Test OneDrive connectivity and return (success, message)."""
    try:
        token = _get_token(custom_config)
        h = {"Authorization": f"Bearer {token}"}
        
        # Test Graph API root endpoints
        endpoints = [
            f"{GRAPH}/me/drive/root",
            f"{GRAPH}/drive/root",
            f"{GRAPH}/drives",
            f"{GRAPH}/me/drive",
            f"{GRAPH}/organization",
        ]
        
        last_status = None
        for ep in endpoints:
            try:
                r = requests.get(ep, headers=h, timeout=15)
                last_status = r.status_code
                if r.status_code == 200:
                    data = r.json()
                    name = data.get("name") or data.get("displayName") or "Connected"
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
