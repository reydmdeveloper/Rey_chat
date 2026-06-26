import sys

# Reconfigure stdout and stderr to UTF-8 to prevent emoji print crashes on Windows CP1252
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
except Exception:
    pass

from PyQt6.QtCore import QUrl, Qt, QTimer, QPropertyAnimation, QPoint, QEasingCurve
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QDialog,
    QLabel, QLineEdit, QPushButton, QGraphicsDropShadowEffect, QMessageBox,
    QInputDialog, QSystemTrayIcon, QMenu, QStyle
)
from PyQt6.QtGui import QIcon, QFont, QColor, QAction
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEngineProfile, QWebEnginePage

import os
import time
import shutil
import subprocess
import winreg


def get_install_dir():
    appdata = os.getenv("LOCALAPPDATA")
    if not appdata:
        appdata = os.path.expanduser("~\\AppData\\Local")
    return os.path.join(appdata, "Programs", "ReydmChat")

def create_shortcut(target_path, shortcut_path, description="REYDM Secure Chat"):
    powershell_cmd = (
        f'$WshShell = New-Object -ComObject WScript.Shell; '
        f'$Shortcut = $WshShell.CreateShortcut("{shortcut_path}"); '
        f'$Shortcut.TargetPath = "{target_path}"; '
        f'$Shortcut.Description = "{description}"; '
        f'$Shortcut.WorkingDirectory = "{os.path.dirname(target_path)}"; '
        f'$Shortcut.Save()'
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", powershell_cmd],
            capture_output=True, text=True, check=True
        )
        return True
    except Exception as e:
        print(f"Error creating shortcut: {e}")
        return False

def set_startup(enabled=True):
    try:
        if getattr(sys, 'frozen', False):
            path = sys.executable
        else:
            path = os.path.abspath(sys.argv[0])
            
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, "REYDM_Chat", 0, winreg.REG_SZ, f'"{path}" --background')
        else:
            try:
                winreg.DeleteValue(key, "REYDM_Chat")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Error updating startup registry: {e}")

class ReydmInstallerDialog(QDialog):
    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("REYDM Chat Setup")
        self.setWindowFlags(
            Qt.WindowType.Window | 
            Qt.WindowType.CustomizeWindowHint | 
            Qt.WindowType.WindowTitleHint | 
            Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(450, 250)
        self.choice = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        title = QLabel("Install REYDM Secure Chat?")
        title.setStyleSheet("color: #00adb5; font-size: 20px; font-weight: bold;")
        
        desc = QLabel(
            "Would you like to install REYDM Secure Chat on this system?\n\n"
            "This will:\n"
            " • Copy the application to your local programs folder\n"
            " • Create Desktop and Start Menu shortcuts\n"
            " • Allow the app to run in the background for instant notifications"
        )
        desc.setStyleSheet("color: #d1d1d6; font-size: 13px; line-height: 1.4;")
        desc.setWordWrap(True)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        install_btn = QPushButton("Install (Recommended)")
        install_btn.setStyleSheet("""
            background-color: #00adb5;
            color: white;
            font-weight: bold;
            padding: 10px 15px;
            border-radius: 6px;
            font-size: 13px;
        """)
        install_btn.clicked.connect(self.choose_install)
        
        portable_btn = QPushButton("Run Portable")
        portable_btn.setStyleSheet("""
            background-color: #2d2d3a;
            color: #d1d1d6;
            padding: 10px 15px;
            border-radius: 6px;
            font-size: 13px;
        """)
        portable_btn.clicked.connect(self.choose_portable)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            background-color: transparent;
            color: #888899;
            padding: 10px 15px;
            border-radius: 6px;
            font-size: 13px;
        """)
        cancel_btn.clicked.connect(self.choose_cancel)
        
        btn_layout.addWidget(install_btn)
        btn_layout.addWidget(portable_btn)
        btn_layout.addWidget(cancel_btn)
        
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a24;
                border: 1px solid #2d2d3a;
            }
            QLabel {
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)
        
    def choose_install(self):
        self.choice = 'install'
        self.accept()
        
    def choose_portable(self):
        self.choice = 'portable'
        self.accept()
        
    def choose_cancel(self):
        self.choice = 'cancel'
        self.reject()

def handle_installation():
    if not getattr(sys, 'frozen', False):
        return True
        
    install_dir = get_install_dir()
    current_exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    
    if "--portable" in sys.argv:
        return True
        
    if os.path.abspath(current_exe_dir).lower() == os.path.abspath(install_dir).lower():
        set_startup(True)
        return True
        
    dialog = ReydmInstallerDialog()
    dialog.exec()
    
    if dialog.choice == 'install':
        try:
            os.makedirs(install_dir, exist_ok=True)
            installed_exe = os.path.join(install_dir, "REYDM_Chat.exe")
            shutil.copy2(sys.executable, installed_exe)
            
            config_name = "server_config.txt"
            current_config = os.path.join(current_exe_dir, config_name)
            if os.path.exists(current_config):
                shutil.copy2(current_config, os.path.join(install_dir, config_name))
                
            desktop_lnk = os.path.join(os.path.expanduser("~\\Desktop"), "REYDM Chat.lnk")
            start_menu_dir = os.path.join(os.getenv("APPDATA"), "Microsoft\\Windows\\Start Menu\\Programs")
            start_menu_lnk = os.path.join(start_menu_dir, "REYDM Chat.lnk")
            
            create_shortcut(installed_exe, desktop_lnk)
            create_shortcut(installed_exe, start_menu_lnk)
            
            set_startup(True)
            
            QMessageBox.information(
                None,
                "Installation Successful",
                "REYDM Secure Chat has been installed successfully!\n\n"
                "Shortcuts have been added to your Desktop and Start Menu.\n"
                "The application will now start.",
                QMessageBox.StandardButton.Ok
            )
            
            subprocess.Popen([installed_exe])
            return False
        except Exception as e:
            QMessageBox.critical(
                None,
                "Installation Error",
                f"An error occurred during installation:\n{e}\n\nRunning in portable mode instead.",
                QMessageBox.StandardButton.Ok
            )
            return True
    elif dialog.choice == 'portable':
        return True
    else:
        sys.exit(0)

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
        "run_local_server": "false",
        "disable_gpu": "true"
    }
    
    if not os.path.exists(config_path):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("# REYDM Secure Chat Configuration\n")
                f.write("# To connect to a public online server (Render, PythonAnywhere, etc.), set run_local_server to false\n")
                f.write("run_local_server=false\n")
                f.write("# Disable hardware acceleration to prevent blinking/flickering on older or integrated GPUs\n")
                f.write("disable_gpu=true\n")
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
        "run_local_server": config.get("run_local_server", "false"),
        "disable_gpu": config.get("disable_gpu", "true")
    }

class ReydmOSNotification(QDialog):
    def __init__(self, parent_window, sender_name, message_text, conversation_id):
        super().__init__(None) # Pass None as parent to keep the notification window independent when main window is minimized
        self.parent_window = parent_window
        self.sender_name = sender_name
        self.message_text = message_text
        self.conversation_id = conversation_id
        
        # Set flags: frameless, stay on top, no taskbar entry
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        # Outer layout
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        
        # Container widget for styling
        container = QWidget()
        container.setObjectName("container")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(12, 10, 12, 12)
        container_layout.setSpacing(6)
        
        # Apply drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 3)
        container.setGraphicsEffect(shadow)
        
        # Header layout (logo indicator, title, stretch, close button)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)
        
        icon_label = QLabel()
        icon_label.setFixedSize(12, 12)
        icon_label.setStyleSheet("background-color: #00adb5; border-radius: 6px;")
        
        title_label = QLabel("REYDM Chat")
        title_label.setObjectName("title_label")
        
        close_btn = QPushButton("×")
        close_btn.setObjectName("close_btn")
        close_btn.setFixedSize(16, 16)
        close_btn.clicked.connect(self.animate_exit)
        
        header_layout.addWidget(icon_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(close_btn)
        
        # Sender Label
        sender_lbl = QLabel(sender_name)
        sender_lbl.setObjectName("sender_label")
        
        # Message text
        msg_lbl = QLabel(message_text)
        msg_lbl.setObjectName("msg_label")
        msg_lbl.setWordWrap(True)
        if len(message_text) > 85:
            msg_lbl.setText(message_text[:82] + "...")
            
        # Reply area (Input + Send button)
        reply_layout = QHBoxLayout()
        reply_layout.setSpacing(6)
        
        self.reply_input = QLineEdit()
        self.reply_input.setObjectName("reply_input")
        self.reply_input.setPlaceholderText("Type a reply...")
        self.reply_input.returnPressed.connect(self.handle_send_reply)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.handle_send_reply)
        
        reply_layout.addWidget(self.reply_input)
        reply_layout.addWidget(self.send_btn)
        
        # Assemble
        container_layout.addLayout(header_layout)
        container_layout.addWidget(sender_lbl)
        container_layout.addWidget(msg_lbl)
        container_layout.addLayout(reply_layout)
        
        outer_layout.addWidget(container)
        
        # Apply Styling (premium dark-slate/teal theme matching the app design system)
        self.setStyleSheet("""
            QWidget#container {
                background-color: #1a1a24;
                border: 1px solid rgba(0, 173, 181, 0.4);
                border-radius: 12px;
            }
            QLabel#title_label {
                color: #888899;
                font-size: 10px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            QLabel#sender_label {
                color: #00adb5;
                font-size: 13px;
                font-weight: bold;
            }
            QLabel#msg_label {
                color: #d1d1d6;
                font-size: 12px;
            }
            QLineEdit#reply_input {
                background-color: #121218;
                color: #ffffff;
                border: 1px solid #2d2d3a;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
            }
            QLineEdit#reply_input:focus {
                border: 1px solid #00adb5;
            }
            QPushButton {
                background-color: #00adb5;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00c2cb;
            }
            QPushButton#close_btn {
                background-color: transparent;
                color: #888899;
                font-size: 14px;
                font-weight: bold;
                padding: 0px;
                border: none;
                cursor: pointer;
            }
            QPushButton#close_btn:hover {
                color: #ffffff;
            }
        """)
        
        # Set geometry & start animation
        self.resize(360, 150)
        available_geom = QApplication.primaryScreen().availableGeometry()
        
        width = 360
        height = 150
        final_x = available_geom.right() - width - 20
        final_y = available_geom.bottom() - height - 20
        start_x = final_x
        start_y = available_geom.bottom() + 10
        
        self.setGeometry(start_x, start_y, width, height)
        
        # Slide up animation
        self.anim = QPropertyAnimation(self, b"pos")
        self.anim.setDuration(400)
        self.anim.setStartValue(QPoint(start_x, start_y))
        self.anim.setEndValue(QPoint(final_x, final_y))
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.start()
        
        # 8-second auto close timer
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.animate_exit)
        self.close_timer.start(8000)
        
    def enterEvent(self, event):
        self.close_timer.stop()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        if not self.reply_input.hasFocus():
            self.close_timer.start(8000)
        super().leaveEvent(event)
        
    def mousePressEvent(self, event):
        # Check what widget was clicked
        child = self.childAt(event.position().toPoint())
        if child not in [self.reply_input, self.send_btn, self.close_btn] and not isinstance(child, QPushButton):
            self.parent_window.show()
            self.parent_window.raise_()
            self.parent_window.activateWindow()
            
            # Switch room JS
            escaped_conv = self.conversation_id.replace("'", "\\'")
            js_code = f"if (window.navigateToRoomFromSystem) {{ window.navigateToRoomFromSystem('{escaped_conv}'); }}"
            self.parent_window.browser.page().runJavaScript(js_code)
            self.animate_exit()
        super().mousePressEvent(event)
        
    def handle_send_reply(self):
        text = self.reply_input.text().strip()
        if text:
            self.parent_window.send_reply_from_notification(self.conversation_id, text)
        self.animate_exit()
        
    def animate_exit(self):
        if hasattr(self, "_exiting") and self._exiting:
            return
        self._exiting = True
        
        available_geom = QApplication.primaryScreen().availableGeometry()
        current_pos = self.pos()
        end_pos = QPoint(current_pos.x(), available_geom.bottom() + 10)
        
        self.exit_anim = QPropertyAnimation(self, b"pos")
        self.exit_anim.setDuration(300)
        self.exit_anim.setStartValue(current_pos)
        self.exit_anim.setEndValue(end_pos)
        self.exit_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        
        self.exit_anim.finished.connect(self.close)
        self.exit_anim.start()

class ReydmChatPage(QWebEnginePage):
    """Custom page to intercept /api/chat/open/ URLs and download+open locally."""
    def __init__(self, profile, parent, main_window, server_url):
        super().__init__(profile, parent)
        self.main_window = main_window
        self.server_url = server_url.rstrip('/')
        
        # Connect permission request signal to automatically grant it
        self.featurePermissionRequested.connect(self.handle_feature_permission_requested)

    def javaScriptAlert(self, securityOrigin, msg):
        QMessageBox.warning(self.main_window, "REYDM Chat", msg)

    def javaScriptConfirm(self, securityOrigin, msg):
        result = QMessageBox.question(
            self.main_window, 
            "REYDM Chat", 
            msg, 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )
        return result == QMessageBox.StandardButton.Yes

    def javaScriptPrompt(self, securityOrigin, msg, defaultVal):
        val, ok = QInputDialog.getText(self.main_window, "REYDM Chat", msg, QLineEdit.EchoMode.Normal, defaultVal)
        return ok, val

    def handle_feature_permission_requested(self, securityOrigin, feature):
        # Automatically grant permission (Notifications, Geolocation, etc.)
        self.setFeaturePermission(securityOrigin, feature, QWebEnginePage.PermissionPolicy.PermissionGrantedByUser)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message.startswith("TRIGGER_OS_NOTIFICATION:"):
            try:
                parts = message.replace("TRIGGER_OS_NOTIFICATION:", "", 1).split("|", 2)
                if len(parts) == 3:
                    sender_name, text, conv_id = parts
                    self.main_window.show_system_notification(sender_name, text, conv_id)
            except Exception as e:
                print(f"Error handling system notification trigger: {e}")
        elif message.startswith("ACTIVE_ROOM_CHANGED:"):
            self.main_window.current_room = message.replace("ACTIVE_ROOM_CHANGED:", "", 1).strip()
            
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        url_str = url.toString()
        if '/api/chat/open/' in url_str:
            import tempfile
            import urllib.request
            import urllib.parse
            try:
                # Decoded filename path (e.g., "username/conversation_id/file.txt")
                filename_path = url_str.split('/api/chat/open/')[-1]
                filename_path = urllib.parse.unquote(filename_path)
                
                # Check local filesystem first (if running with a local server)
                local_options = [
                    os.path.join(r"C:\rey_chat", filename_path),
                    os.path.join(os.getcwd(), "rey_chat", filename_path)
                ]
                opened_locally = False
                for path in local_options:
                    if os.path.exists(path):
                        os.startfile(path)
                        opened_locally = True
                        break
                
                if not opened_locally:
                    # Download the file using authenticated session cookies
                    download_url = url_str.replace('/api/chat/open/', '/api/chat/download/')
                    tmp_dir = os.path.join(tempfile.gettempdir(), 'rey_chat_preview')
                    os.makedirs(tmp_dir, exist_ok=True)
                    local_path = os.path.join(tmp_dir, os.path.basename(filename_path))
                    
                    # Create authenticated urllib request
                    req = urllib.request.Request(download_url)
                    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
                    
                    # Collect session cookies from the main window
                    cookies = getattr(self.main_window, 'cookies', {})
                    if cookies:
                        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
                        req.add_header('Cookie', cookie_str)
                    
                    # Perform download
                    with urllib.request.urlopen(req) as response:
                        with open(local_path, 'wb') as out_file:
                            out_file.write(response.read())
                            
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
    def __init__(self, target_url="https://rey-chat.onrender.com/"):
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
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        
        # Track cookies for authenticating file downloads
        self.cookies = {}
        self.profile.cookieStore().cookieAdded.connect(self.handle_cookie_added)
        
        # Load config to determine GPU state
        config = load_config()
        disable_gpu = config.get("disable_gpu", "true").lower() == "true"

        # Enable Hardware Acceleration and WebGL only if GPU is NOT disabled
        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, not disable_gpu)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, not disable_gpu)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        
        self.active_notifications = []
        self.load_attempts = 0
        
        # Use custom page for URL interception and notification bridge
        custom_page = ReydmChatPage(self.profile, self.browser, self, target_url)
        self.browser.setPage(custom_page)
        
        # Set dark background color to prevent white flashes during loading
        custom_page.setBackgroundColor(QColor(18, 18, 18))
        
        # Connect load finished signal to check for connection failures
        self.browser.loadFinished.connect(self.handle_load_finished)
        
        # Load the server URL asynchronously to allow the window frame to show up instantly
        if "YOUR-ONLINE-SERVER" in target_url:
            QTimer.singleShot(0, self.show_config_error)
        else:
            QTimer.singleShot(0, lambda: self.browser.setUrl(QUrl(target_url)))
            
        layout.addWidget(self.browser)

        # Setup System Tray Icon
        self.really_quit = False
        self.tray_icon = QSystemTrayIcon(self)
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
            
        tray_menu = QMenu()
        show_action = QAction("Show REYDM Chat", self)
        show_action.triggered.connect(self.show_normal)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.quit_application)
        
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        self.tray_icon.show()
        
        # Connect download handler
        self.profile.downloadRequested.connect(self.handle_download_requested)
        
    def handle_cookie_added(self, cookie):
        name = cookie.name().data().decode('utf-8')
        value = cookie.value().data().decode('utf-8')
        self.cookies[name] = value
        
    def handle_load_finished(self, success):
        """If the connection to the server fails, retry connection. For local server, we do rapid checks (500ms) up to 12 times."""
        if success:
            self.load_attempts = 0
        else:
            self.load_attempts += 1
            run_local = load_config()["run_local_server"].lower() == "true"
            max_attempts = 12 if run_local else 3
            retry_delay = 500 if run_local else 5000
            
            if self.load_attempts < max_attempts:
                print(f"Server load failed. Retrying connection (Attempt {self.load_attempts + 1} of {max_attempts}) in {retry_delay}ms...")
                QTimer.singleShot(retry_delay, lambda: self.browser.setUrl(QUrl(self.target_url)))
            else:
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

    def show_system_notification(self, sender_name, text, conv_id):
        is_minimized = self.isMinimized()
        is_inactive = not self.isActiveWindow()
        is_different_room = (getattr(self, "current_room", "") != conv_id)
        
        if is_minimized or is_inactive or is_different_room:
            # Close any existing active notifications
            for notif in list(self.active_notifications):
                try:
                    notif.close()
                except Exception:
                    pass
            self.active_notifications.clear()
            
            notif = ReydmOSNotification(self, sender_name, text, conv_id)
            self.active_notifications.append(notif)
            notif.show()

    def send_reply_from_notification(self, conversation_id, text):
        escaped_text = text.replace('\\', '\\\\').replace("'", "\\'")
        js_code = f"if (window.sendReplyFromSystem) {{ window.sendReplyFromSystem('{conversation_id}', '{escaped_text}'); }}"
        self.browser.page().runJavaScript(js_code)

    def show_normal(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_application(self):
        self.really_quit = True
        QApplication.quit()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_normal()

    def closeEvent(self, event):
        if not self.really_quit:
            event.ignore()
            self.hide()
        else:
            super().closeEvent(event)

if __name__ == "__main__":
    # Load configuration first to check for GPU disable option
    config = load_config()
    disable_gpu = config.get("disable_gpu", "true").lower() == "true"
    
    # Configure Chromium/QtWebEngine flags
    flags = ["--ignore-gpu-blocklist", "--no-sandbox"]
    if disable_gpu:
        flags.append("--disable-gpu")
        flags.append("--disable-gpu-compositing")
        flags.append("--disable-gpu-rasterization")
        flags.append("--disable-accelerated-2d-canvas")
        flags.append("--disable-accelerated-video-decode")
        flags.append("--disable-gpu-sandbox")
        flags.append("--disable-webgl")
        flags.append("--disable-3d-apis")
        flags.append("--disable-direct-composition")
        flags.append("--use-gl=swiftshader")
        flags.append("--use-angle=warp")
        os.environ["QT_OPENGL"] = "software"
        os.environ["QT_QUICK_BACKEND"] = "software"
        os.environ["QTWEBENGINE_DISABLE_GPU"] = "1"
        os.environ["QT_ANGLE_PLATFORM"] = "warp"
    else:
        flags.append("--enable-gpu-rasterization")
        
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)
    
    # Use Round policy instead of PassThrough to prevent layout/resize feedback loops (flickering/blinking)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.Round
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # ─── SINGLE INSTANCE CHECK ───────────────────────────────────────
    socket_name = "reydm_chat_single_instance_socket"
    socket = QLocalSocket()
    socket.connectToServer(socket_name)
    if socket.waitForConnected(500):
        # Already running! Send command to restore window
        socket.write(b"show")
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        sys.exit(0)
        
    # Start local server to listen for future launch attempts
    local_server = QLocalServer()
    local_server.removeServer(socket_name) # Clean up dead sockets from crashes
    
    def handle_new_instance():
        client_socket = local_server.nextPendingConnection()
        if client_socket:
            client_socket.readyRead.connect(lambda: handle_instance_message(client_socket))
            
    def handle_instance_message(client_socket):
        data = client_socket.readAll().data()
        if data == b"show":
            active_client = globals().get('client')
            if active_client:
                active_client.show_normal()
        client_socket.disconnectFromServer()
        
    local_server.newConnection.connect(handle_new_instance)
    if not local_server.listen(socket_name):
        print("Warning: Could not start single instance local server listener.")
    # ─────────────────────────────────────────────────────────────────

    # Run installer check
    if not handle_installation():
        sys.exit(0)
        
    # Load configuration
    config = load_config()
    target_url = config["server_url"]
    run_local = config["run_local_server"].lower() == "true"
    
    if run_local:
        import threading
        import app as flask_module
        from app import app as flask_app, socketio
        
        import os
        run_port = int(os.environ.get("PORT", os.environ.get("APP_PORT", 5000)))
        
        # Override target_url to load the local Flask server in QWebEngineView!
        target_url = f"http://127.0.0.1:{run_port}/"
        
        # Run local server binding to 0.0.0.0 so other network machines can connect
        def run_server():
            socketio.run(flask_app, host="0.0.0.0", port=run_port, allow_unsafe_werkzeug=True)

        backend_thread = threading.Thread(target=run_server, daemon=True)
        backend_thread.start()
        
        # Give the backend server a tiny moment to initialize without blocking GUI startup
        time.sleep(0.1)

    client = ReydmChatDesktop(target_url)
    
    # If starting in background (e.g., automatically on Windows startup), do not show window
    if "--background" not in sys.argv:
        client.show()
    
    # Run the desktop app
    sys.exit(app.exec())