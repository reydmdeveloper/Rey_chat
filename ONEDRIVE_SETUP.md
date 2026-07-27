# OneDrive Storage Setup (Rey Chat)

Rey Chat has no central server: each PC runs its own instance and they share
only the database. To make uploaded files downloadable from any PC, files
are stored in a **single shared Microsoft OneDrive account** via the
Microsoft Graph API (client-credentials / daemon flow).

## 1. Register an Azure AD app

1. Go to https://entra.microsoft.com > **App registrations** > **New registration**.
2. Name it e.g. `ReyChatStorage`. Supported account types: **Single tenant**.
3. After creation, copy the **Application (client) ID** and **Directory (tenant) ID**.
4. Go to **Certificates & secrets** > **New client secret**. Copy the value (show it once).
5. Go to **API permissions** > **Add a permission** > **Microsoft Graph** >
   **Application permissions** > `Files.ReadWrite.All`. Then **Grant admin consent**.

## 2. Set environment variables on every PC that runs the app

```
ONEDRIVE_CLIENT_ID=your-client-id
ONEDRIVE_CLIENT_SECRET=your-client-secret
ONEDRIVE_TENANT_ID=your-tenant-id
ONEDRIVE_FOLDER=rey_chat
```

For the shared OneDrive account, sign into that account in the Azure tenant
used above (the app must belong to that tenant, and the account must be
in it, or use a service/resource account in the same tenant).

## 3. How it works

- When OneDrive creds are present, uploads go to
  `OneDrive:/rey_chat/<user_id>/<conversation_id>/<file>` and the DB
  stores a reference like `od:<driveItemId>` (under 255 chars).
- Downloads/open requests resolve that reference from OneDrive at request
  time, so any instance (any PC) can fetch the file.
- When creds are **missing**, it transparently falls back to local disk
  under the UPLOAD_FOLDER (OneDrive-synced folder when available).

## 4. PHP Extra Storage Server (alternative)

If you don't want to use OneDrive, you can run a lightweight **PHP storage server**
that acts as an extra file backend. All app instances send/receive files through it.

```
# Start the PHP storage server (keep this terminal open):
php -S 0.0.0.0:8089 storage_server.php
```

Then set the environment variable:
```
PHP_STORAGE_URL=http://<your-server-ip>:8089
```

In the app Settings panel, switch **Storage Mode** to **"PHP Extra Server"**,
enter the server URL, and click **Test Connection**.

All uploaded files will be stored on the PHP server and accessible from any
device that can reach it.

## 5. How to choose a storage mode

| Mode | Best for |
|------|----------|
| 💻 Local Storage | Single PC, no sharing needed |
| ☁️ OneDrive Cloud | Multiple PCs, same Microsoft account |
| 🌐 PHP Extra Server | Multiple PCs, custom server, no Azure setup needed |

## 6. Migrating old local files

Files uploaded before a cloud/PHP storage mode was configured remain on local disk under
`UPLOAD_FOLDER`. The download resolver also searches that folder as a
legacy fallback, so old links keep working until you move them.
