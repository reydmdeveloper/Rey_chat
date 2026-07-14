import sys
import os
import time
import shutil
import subprocess
import winreg
import socket
import threading
import webbrowser

# Reconfigure stdout and stderr to UTF-8 to prevent emoji print crashes on Windows CP1252
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
except Exception:
    pass

import customtkinter as ctk
from tkinter import messagebox
from PIL import Image
import pystray
import tkwebview2 as tkweb


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
            
        key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
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


class ReydmInstallerDialog(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("REYDM Chat Setup")
        self.geometry("460x280")
        self.resizable(False, False)
        self.choice = None
        
        # Enable dark window title bar
        try:
            import ctypes
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.windll.user32.GetParent(self.winfo_id()),
                20, ctypes.byref(ctypes.c_int(2)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass
            
        self.configure(fg_color="#1a1a24")
        
        title_lbl = ctk.CTkLabel(
            self, text="Install REYDM Secure Chat?",
            text_color="#00adb5", font=("Segoe UI", 20, "bold")
        )
        title_lbl.pack(pady=(20, 10), padx=20, anchor="w")
        
        desc_text = (
            "Would you like to install REYDM Secure Chat on this system?\n\n"
            "This will:\n"
            " • Copy the application to your local programs folder\n"
            " • Create Desktop and Start Menu shortcuts\n"
            " • Allow the app to run in the background for instant notifications"
        )
        desc_lbl = ctk.CTkLabel(
            self, text=desc_text, text_color="#d1d1d6",
            font=("Segoe UI", 12), justify="left", anchor="w"
        )
        desc_lbl.pack(pady=10, padx=20, fill="both")
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(15, 20), padx=20, fill="x")
        
        install_btn = ctk.CTkButton(
            btn_frame, text="Install (Recommended)", fg_color="#00adb5",
            hover_color="#00c2cb", text_color="white", font=("Segoe UI", 12, "bold"),
            command=self.choose_install
        )
        install_btn.pack(side="left", padx=(0, 10))
        
        portable_btn = ctk.CTkButton(
            btn_frame, text="Run Portable", fg_color="#2d2d3a",
            hover_color="#3e3e50", text_color="#d1d1d6", font=("Segoe UI", 12),
            command=self.choose_portable
        )
        portable_btn.pack(side="left", padx=10)
        
        cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancel", fg_color="transparent",
            hover_color="#2d2d3a", text_color="#888899", font=("Segoe UI", 12),
            command=self.choose_cancel
        )
        cancel_btn.pack(side="right")

    def choose_install(self):
        self.choice = 'install'
        self.destroy()
        
    def choose_portable(self):
        self.choice = 'portable'
        self.destroy()
        
    def choose_cancel(self):
        self.choice = 'cancel'
        self.destroy()


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
    dialog.mainloop()
    
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
            
            messagebox.showinfo(
                "Installation Successful",
                "REYDM Secure Chat has been installed successfully!\n\n"
                "Shortcuts have been added to your Desktop and Start Menu.\n"
                "The application will now start."
            )
            
            subprocess.Popen([installed_exe])
            return False
        except Exception as e:
            messagebox.showerror(
                "Installation Error",
                f"An error occurred during installation:\n{e}\n\nRunning in portable mode instead."
            )
            return True
    elif dialog.choice == 'portable':
        return True
    else:
        sys.exit(0)


def load_config():
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    
    config_path = os.path.join(app_dir, "server_config.txt")
    default_config = {
        "port": 5501,
        "start_on_boot": True,
        "minimize_to_tray": True
    }
    
    if not os.path.exists(config_path):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("# REYDM Secure Chat Local Server Configuration\n")
                f.write("port=5501\n")
                f.write("start_on_boot=true\n")
                f.write("minimize_to_tray=true\n")
        except Exception:
            pass
        return default_config
        
    config = default_config.copy()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip().lower()
                val = val.strip().lower()
                if key == "port":
                    try:
                        config["port"] = int(val)
                    except ValueError:
                        pass
                elif key == "start_on_boot":
                    config["start_on_boot"] = (val == "true")
                elif key == "minimize_to_tray":
                    config["minimize_to_tray"] = (val == "true")
    except Exception:
        pass
    return config


def save_config(port, start_on_boot, minimize_to_tray):
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    
    config_path = os.path.join(app_dir, "server_config.txt")
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("# REYDM Secure Chat Local Server Configuration\n")
            f.write(f"port={port}\n")
            f.write(f"start_on_boot={'true' if start_on_boot else 'false'}\n")
            f.write(f"minimize_to_tray={'true' if minimize_to_tray else 'false'}\n")
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Settings")
        self.geometry("340x260")
        self.resizable(False, False)
        self.configure(fg_color="#1a1a24")
        
        # Keep settings window on top
        self.attributes("-topmost", True)
        
        # Enable dark window title bar
        try:
            import ctypes
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.windll.user32.GetParent(self.winfo_id()),
                20, ctypes.byref(ctypes.c_int(2)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass
            
        title_lbl = ctk.CTkLabel(self, text="REYDM Chat Settings", text_color="#00adb5", font=("Segoe UI", 16, "bold"))
        title_lbl.pack(pady=(15, 10))
        
        # Port Settings
        port_frame = ctk.CTkFrame(self, fg_color="transparent")
        port_frame.pack(fill="x", padx=25, pady=5)
        port_lbl = ctk.CTkLabel(port_frame, text="Server Port:", text_color="#d1d1d6", font=("Segoe UI", 11))
        port_lbl.pack(side="left")
        self.port_entry = ctk.CTkEntry(port_frame, width=100, height=28, fg_color="#121218", border_color="#2d2d3a", text_color="#ffffff")
        self.port_entry.pack(side="right")
        self.port_entry.insert(0, str(parent.port))
        
        # Checkboxes
        self.start_on_boot_var = ctk.BooleanVar(value=parent.start_on_boot)
        self.start_on_boot_cb = ctk.CTkCheckBox(
            self, text="Start on Windows Boot", variable=self.start_on_boot_var,
            text_color="#d1d1d6", font=("Segoe UI", 11), checkbox_width=16, checkbox_height=16,
            fg_color="#00adb5", hover_color="#00c2cb"
        )
        self.start_on_boot_cb.pack(anchor="w", padx=25, pady=8)
        
        self.minimize_to_tray_var = ctk.BooleanVar(value=parent.minimize_to_tray)
        self.minimize_to_tray_cb = ctk.CTkCheckBox(
            self, text="Minimize to Tray on Close", variable=self.minimize_to_tray_var,
            text_color="#d1d1d6", font=("Segoe UI", 11), checkbox_width=16, checkbox_height=16,
            fg_color="#00adb5", hover_color="#00c2cb"
        )
        self.minimize_to_tray_cb.pack(anchor="w", padx=25, pady=8)
        
        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=25, pady=(15, 10))
        
        save_btn = ctk.CTkButton(
            btn_frame, text="Save Settings", fg_color="#00adb5", hover_color="#00c2cb",
            text_color="white", font=("Segoe UI", 12, "bold"), height=30,
            command=self.save_settings
        )
        save_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancel", fg_color="#2d2d3a", hover_color="#3e3e50",
            text_color="#d1d1d6", font=("Segoe UI", 12), height=30,
            command=self.destroy
        )
        cancel_btn.pack(side="right", fill="x", expand=True, padx=(5, 0))

    def save_settings(self):
        try:
            new_port = int(self.port_entry.get().strip())
            if not (1024 <= new_port <= 65535):
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid port number between 1024 and 65535.")
            return
            
        start_on_boot = self.start_on_boot_var.get()
        minimize_to_tray = self.minimize_to_tray_var.get()
        
        if save_config(new_port, start_on_boot, minimize_to_tray):
            set_startup(start_on_boot)
            self.parent.start_on_boot = start_on_boot
            self.parent.minimize_to_tray = minimize_to_tray
            messagebox.showinfo("Settings Saved", "Configuration saved successfully!")
            
            if new_port != self.parent.port:
                self.parent.port = new_port
                self.parent.stop_server()
                self.parent.after(2000, self.parent.start_server)
                
            self.destroy()
        else:
            messagebox.showerror("Error", "Could not save configuration.")


class ReydmChatDesktop(ctk.CTk):
    def __init__(self, port, start_on_boot, minimize_to_tray):
        super().__init__()
        self.port = port
        self.start_on_boot = start_on_boot
        self.minimize_to_tray = minimize_to_tray
        
        self.server_process = None
        self.tray_icon = None
        self.really_quit = False
        self.settings_window = None
        
        # Configure Main Window
        self.title("REYDM Secure Chat")
        self.geometry("1280x800")
        self.minsize(800, 600)
        self.configure(fg_color="#121218")
        
        # Enable dark window title bar
        try:
            import ctypes
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.windll.user32.GetParent(self.winfo_id()),
                20, ctypes.byref(ctypes.c_int(2)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass
            
        self.set_app_icon()
        
        # Start local Flask backend server
        self.start_server()
        
        # Embed Web Browser Frame
        self.browser = tkweb.WebView2(self, width=1280, height=800)
        self.browser.pack(fill="both", expand=True)
        
        # Load local server URL once server goes online
        self.load_chat_url()
        
        # Protocol mapping for Close button
        self.protocol("WM_DELETE_WINDOW", self.on_close_window)
        
        # Setup tray icon
        self.setup_tray()

    def set_app_icon(self):
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        icon_path = os.path.join(base_dir, "Images", "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                try:
                    img = Image.open(icon_path)
                    from PIL import ImageTk
                    photo = ImageTk.PhotoImage(img)
                    self.iconphoto(True, photo)
                except Exception as e:
                    print(f"Could not set app icon: {e}")

    def setup_tray(self):
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        icon_path = os.path.join(base_dir, "Images", "icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(base_dir, "Images", "icon.ico")
            
        try:
            image = Image.open(icon_path)
            
            def on_show(icon, item):
                self.after(0, self.restore_from_tray)
                
            def on_open_browser(icon, item):
                self.after(0, self.open_in_external_browser)
                
            def on_settings(icon, item):
                self.after(0, self.show_settings_dialog)
                
            def on_exit(icon, item):
                self.after(0, self.quit_application)
                
            menu = pystray.Menu(
                pystray.MenuItem("Show Chat", on_show, default=True),
                pystray.MenuItem("Open in Default Browser", on_open_browser),
                pystray.MenuItem("Settings", on_settings),
                pystray.Menu.Separator(),
                pystray.MenuItem("Exit", on_exit)
            )
            
            self.tray_icon = pystray.Icon("REYDM Chat", image, "REYDM Chat", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"Error setting up system tray: {e}")

    def show_settings_dialog(self):
        if self.settings_window is None or not self.settings_window.winfo_exists():
            self.settings_window = SettingsDialog(self)
        else:
            self.settings_window.focus()

    def start_server(self):
        if self.server_process is not None:
            return
            
        if getattr(sys, 'frozen', False):
            cmd = [sys.executable, "--server", str(self.port)]
        else:
            cmd = [sys.executable, "desktop_app.py", "--server", str(self.port)]
            
        try:
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
        except Exception as e:
            print(f"Failed to launch server: {e}")
            self.server_process = None

    def stop_server(self):
        if self.server_process is None:
            return
        try:
            self.server_process.terminate()
            time.sleep(0.5)
            if self.server_process.poll() is None:
                self.server_process.kill()
            self.server_process = None
        except Exception:
            pass

    def load_chat_url(self):
        # Asynchronously wait for local Flask port to become ready, then load url
        def wait_for_server():
            retries = 0
            while retries < 30: # Max 3 seconds wait
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.1)
                try:
                    s.connect(("127.0.0.1", self.port))
                    s.close()
                    # Server is live! Load URL on the Tkinter main thread
                    self.after(0, lambda: self.browser.load_url(f"http://127.0.0.1:{self.port}/"))
                    return
                except Exception:
                    pass
                time.sleep(0.1)
                retries += 1
            # Fallback connection load
            self.after(0, lambda: self.browser.load_url(f"http://127.0.0.1:{self.port}/"))
            
        threading.Thread(target=wait_for_server, daemon=True).start()

    def open_in_external_browser(self):
        url = f"http://127.0.0.1:{self.port}/"
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def on_close_window(self):
        if self.minimize_to_tray and self.tray_icon is not None:
            self.withdraw()
        else:
            self.quit_application()

    def restore_from_tray(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_application(self):
        self.really_quit = True
        self.stop_server()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.destroy()
        sys.exit(0)


def check_single_instance(port=49999):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        
        def listen_for_focus():
            while True:
                try:
                    conn, addr = s.accept()
                    data = conn.recv(1024)
                    if data == b"show":
                        if globals().get("client"):
                            globals()["client"].after(0, globals()["client"].restore_from_tray)
                    conn.close()
                except Exception:
                    break
        threading.Thread(target=listen_for_focus, daemon=True).start()
        return True
    except Exception:
        try:
            s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s2.connect(("127.0.0.1", port))
            s2.sendall(b"show")
            s2.close()
        except Exception:
            pass
        return False


if __name__ == "__main__":
    # Server Subprocess Mode
    if "--server" in sys.argv:
        server_port = 5501
        try:
            idx = sys.argv.index("--server")
            if idx + 1 < len(sys.argv):
                server_port = int(sys.argv[idx + 1])
        except ValueError:
            pass
            
        import app as flask_module
        from app import app as flask_app, socketio
        import os
        
        os.environ["PORT"] = str(server_port)
        os.environ["APP_PORT"] = str(server_port)
        
        socketio.run(flask_app, host="0.0.0.0", port=server_port, allow_unsafe_werkzeug=True)
        sys.exit(0)
        
    # Single Instance Check
    if not check_single_instance(49999):
        sys.exit(0)
        
    # Set CustomTkinter visual styling
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    
    # Run installer check
    if not handle_installation():
        sys.exit(0)
        
    # Load configuration
    config = load_config()
    
    # Start main application
    client = ReydmChatDesktop(
        port=config["port"],
        start_on_boot=config["start_on_boot"],
        minimize_to_tray=config["minimize_to_tray"]
    )
    
    if "--background" in sys.argv:
        client.withdraw()
        
    client.mainloop()
