import javafx.application.Application;
import javafx.application.Platform;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Scene;
import javafx.scene.control.Button;
import javafx.scene.control.CheckBox;
import javafx.scene.control.Label;
import javafx.scene.control.TextField;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import javafx.scene.web.WebEngine;
import javafx.scene.web.WebView;
import javafx.stage.Modality;
import javafx.stage.Stage;

import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.event.ActionListener;
import java.io.*;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.Map;
import java.util.Properties;

public class DesktopApp extends Application {
    private static DesktopApp instance;
    private static Stage primaryStage;
    private static TrayIcon trayIcon;
    private static ServerSocket instanceSocket;

    private int port = 5501;
    private boolean startOnBoot = true;
    private boolean minimizeToTray = true;
    private Process serverProcess;

    public DesktopApp() {
        instance = this;
    }

    public static DesktopApp getInstance() {
        return instance;
    }

    @Override
    public void start(Stage stage) {
        primaryStage = stage;
        loadConfig();

        // ─── SINGLE INSTANCE CHECK ───────────────────────────────────────
        if (!checkSingleInstance()) {
            System.exit(0);
        }

        // Start Flask Server
        startServer();

        // Configure JavaFX platform exit policy
        Platform.setImplicitExit(false);

        // WebView Layout
        WebView webView = new WebView();
        WebEngine webEngine = webView.getEngine();

        // Warmup checker thread
        waitAndLoadUrl(webEngine);

        Scene scene = new Scene(webView, 1280, 800);
        stage.setTitle("REYDM Secure Chat");
        stage.setScene(scene);

        // Close request protocol
        stage.setOnCloseRequest(event -> {
            if (minimizeToTray && SystemTray.isSupported()) {
                event.consume();
                stage.hide();
            } else {
                exitApplication();
            }
        });

        // Load Icon
        try {
            stage.getIcons().add(new javafx.scene.image.Image(new FileInputStream("Images/icon.png")));
        } catch (Exception e) {
            System.out.println("Could not load JavaFX app icon: " + e.getMessage());
        }

        // AWT System Tray Integration
        setupSystemTray();

        // Show window if not running in background
        boolean runInBackground = false;
        for (String arg : getParameters().getRaw()) {
            if ("--background".equals(arg)) {
                runInBackground = true;
                break;
            }
        }

        if (!runInBackground) {
            stage.show();
        }
    }

    private void waitAndLoadUrl(WebEngine webEngine) {
        new Thread(() -> {
            int retries = 0;
            while (retries < 30) {
                try (Socket s = new Socket("127.0.0.1", port)) {
                    // Connected successfully! Load webpage on FX Thread
                    Platform.runLater(() -> webEngine.load("http://127.0.0.1:" + port));
                    return;
                } catch (IOException e) {
                    try {
                        Thread.sleep(100);
                    } catch (InterruptedException ie) {
                        break;
                    }
                }
                retries++;
            }
            // Fallback load
            Platform.runLater(() -> webEngine.load("http://127.0.0.1:" + port));
        }).start();
    }

    private void startServer() {
        if (serverProcess != null) {
            return;
        }
        try {
            ProcessBuilder pb = new ProcessBuilder("python", "app.py");
            Map<String, String> env = pb.environment();
            env.put("PORT", String.valueOf(port));
            env.put("APP_PORT", String.valueOf(port));
            
            // Redirect stream output in background threads to avoid buffer deadlock
            serverProcess = pb.start();
            new Thread(() -> consumeStream(serverProcess.getInputStream())).start();
            new Thread(() -> consumeStream(serverProcess.getErrorStream())).start();
            
            System.out.println("Started local Flask server on port " + port);
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    private void consumeStream(InputStream is) {
        try (BufferedReader br = new BufferedReader(new InputStreamReader(is))) {
            String line;
            while ((line = br.readLine()) != null) {
                // We can print or discard logs. Discarding keeps console clean.
            }
        } catch (IOException e) {
            // Process terminated
        }
    }

    public void stopServer() {
        if (serverProcess != null) {
            try {
                serverProcess.destroy();
                Thread.sleep(300);
                if (serverProcess.isAlive()) {
                    serverProcess.destroyForcibly();
                }
                serverProcess = null;
                System.out.println("Stopped local Flask server.");
            } catch (Exception e) {
                e.printStackTrace();
            }
        }
    }

    private void setupSystemTray() {
        if (!SystemTray.isSupported()) {
            return;
        }
        SystemTray tray = SystemTray.getSystemTray();
        try {
            java.awt.Image image = ImageIO.read(new File("Images/icon.png"));
            
            PopupMenu popup = new PopupMenu();
            MenuItem showItem = new MenuItem("Show Chat");
            MenuItem browserItem = new MenuItem("Open in Default Browser");
            MenuItem settingsItem = new MenuItem("Settings");
            MenuItem exitItem = new MenuItem("Exit");

            showItem.addActionListener(e -> Platform.runLater(() -> {
                primaryStage.show();
                primaryStage.setIconified(false);
                primaryStage.toFront();
            }));

            browserItem.addActionListener(e -> {
                try {
                    Desktop.getDesktop().browse(new java.net.URI("http://127.0.0.1:" + port));
                } catch (Exception ex) {
                    ex.printStackTrace();
                }
            });

            settingsItem.addActionListener(e -> Platform.runLater(this::showSettingsDialog));

            exitItem.addActionListener(e -> exitApplication());

            popup.add(showItem);
            popup.add(browserItem);
            popup.add(settingsItem);
            popup.addSeparator();
            popup.add(exitItem);

            trayIcon = new TrayIcon(image, "REYDM Chat", popup);
            trayIcon.setImageAutoSize(true);
            
            // Double click tray icon to restore window
            trayIcon.addActionListener(e -> Platform.runLater(() -> {
                primaryStage.show();
                primaryStage.setIconified(false);
                primaryStage.toFront();
            }));

            tray.add(trayIcon);
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void showSettingsDialog() {
        Stage dialog = new Stage();
        dialog.initModality(Modality.APPLICATION_MODAL);
        dialog.initOwner(primaryStage);
        dialog.setTitle("Settings");
        dialog.setResizable(false);

        // Styling (Teal & Dark-grey palette matching original CustomTkinter dashboard)
        VBox root = new VBox(15);
        root.setPadding(new Insets(20));
        root.setStyle("-fx-background-color: #1a1a24;");

        Label title = new Label("REYDM Chat Settings");
        title.setStyle("-fx-text-fill: #00adb5; -fx-font-size: 16px; -fx-font-weight: bold;");
        title.setAlignment(Pos.CENTER);

        GridPane grid = new GridPane();
        grid.setHgap(10);
        grid.setVgap(12);

        Label portLabel = new Label("Server Port:");
        portLabel.setStyle("-fx-text-fill: #d1d1d6; -fx-font-size: 11px;");
        TextField portField = new TextField(String.valueOf(port));
        portField.setStyle("-fx-background-color: #121218; -fx-text-fill: #ffffff; -fx-border-color: #2d2d3a; -fx-border-radius: 4;");
        portField.setPrefWidth(120);

        CheckBox bootCb = new CheckBox("Start on Windows Boot");
        bootCb.setSelected(startOnBoot);
        bootCb.setStyle("-fx-text-fill: #d1d1d6; -fx-font-size: 11px;");

        CheckBox trayCb = new CheckBox("Minimize to Tray on Close");
        trayCb.setSelected(minimizeToTray);
        trayCb.setStyle("-fx-text-fill: #d1d1d6; -fx-font-size: 11px;");

        grid.add(portLabel, 0, 0);
        grid.add(portField, 1, 0);
        grid.add(bootCb, 0, 1, 2, 1);
        grid.add(trayCb, 0, 2, 2, 1);

        HBox btnBox = new HBox(10);
        btnBox.setAlignment(Pos.CENTER_RIGHT);

        Button saveBtn = new Button("Save Settings");
        saveBtn.setStyle("-fx-background-color: #00adb5; -fx-text-fill: #ffffff; -fx-font-weight: bold;");
        saveBtn.setOnAction(e -> {
            try {
                int newPort = Integer.parseInt(portField.getText().trim());
                if (newPort < 1024 || newPort > 65535) {
                    throw new NumberFormatException();
                }
                
                boolean newBoot = bootCb.isSelected();
                boolean newTray = trayCb.isSelected();
                
                if (saveConfig(newPort, newBoot, newTray)) {
                    setStartup(newBoot);
                    this.startOnBoot = newBoot;
                    this.minimizeToTray = newTray;
                    
                    if (newPort != port) {
                        this.port = newPort;
                        stopServer();
                        startServer();
                    }
                    dialog.close();
                }
            } catch (NumberFormatException ex) {
                // Show basic alert dialog
                Platform.runLater(() -> {
                    Stage alert = new Stage();
                    alert.initModality(Modality.APPLICATION_MODAL);
                    VBox alertBox = new VBox(10);
                    alertBox.setPadding(new Insets(15));
                    alertBox.setStyle("-fx-background-color: #1a1a24;");
                    Label alertMsg = new Label("Please enter a valid port number between 1024 and 65535.");
                    alertMsg.setStyle("-fx-text-fill: #ea5455;");
                    Button okBtn = new Button("OK");
                    okBtn.setOnAction(evt -> alert.close());
                    alertBox.getChildren().addAll(alertMsg, okBtn);
                    alert.setScene(new Scene(alertBox));
                    alert.showAndWait();
                });
            }
        });

        Button cancelBtn = new Button("Cancel");
        cancelBtn.setStyle("-fx-background-color: #2d2d3a; -fx-text-fill: #d1d1d6;");
        cancelBtn.setOnAction(e -> dialog.close());

        btnBox.getChildren().addAll(saveBtn, cancelBtn);

        root.getChildren().addAll(title, grid, btnBox);
        dialog.setScene(new Scene(root, 340, 240));
        dialog.showAndWait();
    }

    private void loadConfig() {
        Properties prop = new Properties();
        File configFile = new File("server_config.txt");
        if (!configFile.exists()) {
            try (PrintWriter pw = new PrintWriter(new FileWriter(configFile))) {
                pw.println("# REYDM Secure Chat Local Server Configuration");
                pw.println("port=5501");
                pw.println("start_on_boot=true");
                pw.println("minimize_to_tray=true");
            } catch (IOException e) {
                e.printStackTrace();
            }
        }

        try (FileInputStream fis = new FileInputStream(configFile)) {
            prop.load(fis);
            port = Integer.parseInt(prop.getProperty("port", "5501"));
            startOnBoot = Boolean.parseBoolean(prop.getProperty("start_on_boot", "true"));
            minimizeToTray = Boolean.parseBoolean(prop.getProperty("minimize_to_tray", "true"));
        } catch (Exception e) {
            // Default fallbacks
        }
    }

    private boolean saveConfig(int newPort, boolean newBoot, boolean newTray) {
        try (PrintWriter pw = new PrintWriter(new FileWriter("server_config.txt"))) {
            pw.println("# REYDM Secure Chat Local Server Configuration");
            pw.println("port=" + newPort);
            pw.println("start_on_boot=" + (newBoot ? "true" : "false"));
            pw.println("minimize_to_tray=" + (newTray ? "true" : "false"));
            return true;
        } catch (IOException e) {
            e.printStackTrace();
            return false;
        }
    }

    private static void setStartup(boolean enabled) {
        try {
            String path;
            String classPath = System.getProperty("java.class.path");
            if (classPath.endsWith(".jar")) {
                path = "java -jar " + new File(classPath).getAbsolutePath();
            } else {
                path = "java -cp " + new File(classPath).getAbsolutePath() + " DesktopApp";
            }
            
            if (enabled) {
                new ProcessBuilder("reg", "add", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run", "/v", "REYDM_Chat", "/t", "REG_SZ", "/d", "\"" + path + "\" --background", "/f").start();
            } else {
                new ProcessBuilder("reg", "delete", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run", "/v", "REYDM_Chat", "/f").start();
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private boolean checkSingleInstance() {
        try {
            instanceSocket = new ServerSocket(49999);
            new Thread(() -> {
                while (!instanceSocket.isClosed()) {
                    try (Socket socket = instanceSocket.accept();
                         BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream()))) {
                        String line = in.readLine();
                        if ("show".equals(line)) {
                            Platform.runLater(() -> {
                                if (primaryStage != null) {
                                    primaryStage.show();
                                    primaryStage.setIconified(false);
                                    primaryStage.toFront();
                                }
                            });
                        }
                    } catch (IOException e) {
                        break;
                    }
                }
            }).start();
            return true;
        } catch (IOException e) {
            // Already running! Connect and send show request
            try (Socket socket = new Socket("127.0.0.1", 49999);
                 PrintWriter out = new PrintWriter(socket.getOutputStream(), true)) {
                out.println("show");
            } catch (IOException ex) {
                // Connection failed
            }
            return false;
        }
    }

    public void exitApplication() {
        stopServer();
        if (trayIcon != null && SystemTray.isSupported()) {
            SystemTray.getSystemTray().remove(trayIcon);
        }
        if (instanceSocket != null) {
            try {
                instanceSocket.close();
            } catch (IOException e) {
                e.printStackTrace();
            }
        }
        Platform.exit();
        System.exit(0);
    }

    public static void main(String[] args) {
        launch(args);
    }
}
