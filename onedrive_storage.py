"""
OneDrive (Microsoft Graph) cloud storage backend.

Used when there is NO central server: every PC runs its own app instance and
they only share the database. Files are stored in a single shared Microsoft
account OneDrive so they are reachable from any instance.

Auth model: Azure AD app (daemon / client-credentials flow) using a
shared service account. Credentials come from environment variables:

    ONEDRIVE_CLIENT_ID     - Azure AD application (client) ID
    ONEDRIVE_CLIENT_SECRET - application client secret
    ONEDRIVE_TENANT_ID     - directory (tenant) ID
    ONEDRIVE_FOLDER        - root folder in OneDrive (default: rey_chat)

If any of these are missing, the module reports itself as unavailable and the
app falls back to local disk storage.
"""

import os
import mimetypes
import requests

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SCOPES = "https://graph.microsoft.com/.default"

CLIENT_ID = os.environ.get("ONEDRIVE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("ONEDRIVE_CLIENT_SECRET")
TENANT_ID = os.environ.get("ONEDRIVE_TENANT_ID")
ROOT_FOLDER = os.environ.get("ONEDRIVE_FOLDER", "rey_chat").strip("/")

_available = None  # lazily cached


def is_available():
    """True if all required OneDrive credentials are configured."""
    global _available
    if _available is None:
        _available = bool(CLIENT_ID and CLIENT_SECRET and TENANT_ID)
    return _available


def _get_token():
    url = TOKEN_URL_TPL.format(tenant=TENANT_ID)
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": SCOPES,
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


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
