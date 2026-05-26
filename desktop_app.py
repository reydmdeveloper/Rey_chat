import sys

# Reconfigure stdout and stderr to UTF-8 to prevent emoji print crashes on Windows CP1252
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
except Exception:
    pass

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEngineProfile, QWebEnginePage

import os
import time

def load_config():
    """Load configuration from server_config.txt in the executable's folder."""
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    
    config_path = os.path.join(app_dir, "server_config.txt")
    
    # Default settings (defaults to empty so the custom Setup Screen triggers on first run)
    default_config = {
        "server_url": "https://YOUR-ONLINE-SERVER.onrender.com",
        "run_local_server": "false"
    }
    
    if not os.path.exists(config_path):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("# REYDM Secure Chat Configuration\n")
                f.write("# To connect to a public online server (Render, PythonAnywhere, etc.), set run_local_server to false\n")
                f.write("run_local_server=false\n")
                f.write("# Replace the URL below with your online hosted server URL\n")
                f.write("server_url=https://YOUR-ONLINE-SERVER.onrender.com\n")
        except Exception:
            pass
        return default_config
        
    config = {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                config[key.strip().lower()] = val.strip()
    except Exception:
        return default_config
        
    return {
        "server_url": config.get("server_url", "https://YOUR-ONLINE-SERVER.onrender.com"),
        "run_local_server": config.get("run_local_server", "false")
    }

class ReydmChatPage(QWebEnginePage):
    """Custom page to intercept /api/chat/open/ URLs and download+open locally."""
    def __init__(self, profile, parent, server_url):
        super().__init__(profile, parent)
        self.server_url = server_url.rstrip('/')

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        url_str = url.toString()
        if '/api/chat/open/' in url_str:
            # Instead of server-side os.startfile, download and open locally
            import tempfile
            import urllib.request
            try:
                filename = url_str.split('/api/chat/open/')[-1]
                download_url = url_str.replace('/api/chat/open/', '/api/chat/download/')
                tmp_dir = os.path.join(tempfile.gettempdir(), 'rey_chat_preview')
                os.makedirs(tmp_dir, exist_ok=True)
                local_path = os.path.join(tmp_dir, os.path.basename(filename))
                urllib.request.urlretrieve(download_url, local_path)
                os.startfile(local_path)
            except Exception as e:
                print(f"Error opening file: {e}")
            return False  # Don't navigate
            
        # Intercept external links to open in default browser (Chrome)
        if url.scheme() in ['http', 'https']:
            # If the link is not part of the active chat server, open in external browser
            if not url_str.startswith(self.server_url) and "YOUR-ONLINE-SERVER" not in self.server_url:
                import webbrowser
                try:
                    webbrowser.open(url_str)
                except Exception as e:
                    print(f"Error opening link: {e}")
                return False  # Intercept and don't load in app webview
                
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

class ReydmChatDesktop(QMainWindow):
    def __init__(self, target_url="https://YOUR-ONLINE-SERVER.onrender.com"):
        super().__init__()
        self.target_url = target_url
        self.setWindowTitle("REYDM Secure Chat")
        self.resize(1280, 800)
        
        # Set window icon if it exists
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        icon_path = os.path.join(base_dir, "Images", "icon.ico")
        if os.path.exists(icon_path):
            from PyQt6.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.browser = QWebEngineView()
        self.profile = QWebEngineProfile.defaultProfile()
        
        # Enable Hardware Acceleration and High FPS WebGL
        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        
        # Use custom page for URL interception
        custom_page = ReydmChatPage(self.profile, self.browser, target_url)
        self.browser.setPage(custom_page)
        
        # Connect load finished signal to check for connection failures
        self.browser.loadFinished.connect(self.handle_load_finished)
        
        # Load the server URL
        if "YOUR-ONLINE-SERVER" in target_url:
            self.show_config_error()
        else:
            self.browser.setUrl(QUrl(target_url))
            
        layout.addWidget(self.browser)
        
        # Connect download handler
        self.profile.downloadRequested.connect(self.handle_download_requested)
        
    def handle_load_finished(self, success):
        """If the connection to the online server fails, show a beautiful user-friendly setup guide."""
        if not success:
            self.show_config_error()
            
    def show_config_error(self):
        """Displays a beautiful, dark-themed connection configuration page inside the app window."""
        error_html = f"""
        <html>
        <head>
            <style>
                body {{
                    background: #121212;
                    color: #ffffff;
                    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    margin: 0;
                    text-align: center;
                }}
                .container {{
                    background: #1e1e1e;
                    border: 1px solid #2d2d2d;
                    border-radius: 16px;
                    padding: 40px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.6);
                    max-width: 550px;
                }}
                .logo-container {{
                    margin-bottom: 25px;
                }}
                h1 {{
                    color: #00adb5;
                    margin-bottom: 15px;
                    font-size: 28px;
                    font-weight: 600;
                    letter-spacing: 0.5px;
                }}
                p {{
                    color: #aaaaaa;
                    font-size: 15px;
                    line-height: 1.6;
                    margin-bottom: 20px;
                }}
                .steps {{
                    text-align: left;
                    background: #252525;
                    padding: 20px;
                    border-radius: 8px;
                    border-left: 4px solid #00adb5;
                    margin: 20px 0;
                }}
                .steps ol {{
                    margin: 0;
                    padding-left: 20px;
                    color: #cccccc;
                }}
                .steps li {{
                    margin-bottom: 10px;
                    font-size: 14.5px;
                }}
                .code-box {{
                    background: #121212;
                    color: #393e46;
                    padding: 12px;
                    border-radius: 6px;
                    font-family: 'Courier New', Courier, monospace;
                    margin: 15px 0;
                    font-size: 14px;
                    border: 1px solid #2d2d2d;
                    color: #00adb5;
                    font-weight: bold;
                    letter-spacing: 0.5px;
                    user-select: all;
                }}
                .btn {{
                    background: #00adb5;
                    color: #ffffff;
                    border: none;
                    padding: 12px 28px;
                    border-radius: 8px;
                    font-size: 15px;
                    cursor: pointer;
                    font-weight: bold;
                    transition: background 0.2s ease, transform 0.1s ease;
                    margin-top: 10px;
                }}
                .btn:hover {{
                    background: #00c2cb;
                }}
                .btn:active {{
                    transform: scale(0.98);
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="logo-container">
                    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM13 17H11V15H13V17ZM13 13H11V7H13V13Z" fill="#00adb5"/>
                    </svg>
                </div>
                <h1>REYDM Secure Chat</h1>
                <p>Unable to connect to the online server. This is normal if you haven't configured your custom online deployment yet.</p>
                
                <div class="steps">
                    <div style="font-weight: bold; color: #ffffff; margin-bottom: 8px;">To connect your executable:</div>
                    <ol>
                        <li>Open the folder where this <strong>REYDM_Chat.exe</strong> is located.</li>
                        <li>Open the file named <strong>server_config.txt</strong>.</li>
                        <li>Change <strong>server_url</strong> to your free online server address, like:</li>
                        <div class="code-box">server_url=https://your-app.onrender.com</div>
                        <li>Save the file and click <strong>Reload Server Connection</strong> below.</li>
                    </ol>
                </div>
                <button class="btn" onclick="window.location.href='{self.target_url}'">Reload Server Connection</button>
            </div>
        </body>
        </html>
        """
        self.browser.setHtml(error_html)
        
    def handle_download_requested(self, download):
        from PyQt6.QtWidgets import QFileDialog
        
        suggested_filename = download.suggestedFileName()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save File As",
            suggested_filename
        )
        
        if file_path:
            download.setDownloadDirectory(os.path.dirname(file_path))
            download.setDownloadFileName(os.path.basename(file_path))
            download.accept()
        else:
            download.cancel()

if __name__ == "__main__":
    # Load configuration
    config = load_config()
    target_url = config["server_url"]
    run_local = config["run_local_server"].lower() == "true"
    
    if run_local:
        import threading
        import app as flask_module
        from app import app as flask_app, socketio
        
        # Run local server binding to 0.0.0.0 so other network machines can connect
        def run_server():
            import os
            run_port = int(os.environ.get("PORT", os.environ.get("APP_PORT", 5000)))
            socketio.run(flask_app, host="0.0.0.0", port=run_port, allow_unsafe_werkzeug=True)

        backend_thread = threading.Thread(target=run_server, daemon=True)
        backend_thread.start()
        
        # Give the backend server a moment to initialize and start listening
        time.sleep(2.0)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    client = ReydmChatDesktop(target_url)
    client.show()
    
    # Run the desktop app (exiting will terminate the process instantly)
    sys.exit(app.exec())