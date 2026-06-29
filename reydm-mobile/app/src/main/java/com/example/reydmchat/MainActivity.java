package com.example.reydmchat;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    private SharedPreferences prefs;
    private WebView webView;
    private LinearLayout configLayout;
    private EditText urlInput;
    private View settingsButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("ReydmChatPrefs", Context.MODE_PRIVATE);

        // Root FrameLayout
        FrameLayout rootLayout = new FrameLayout(this);
        rootLayout.setLayoutParams(new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));
        rootLayout.setBackgroundColor(Color.parseColor("#121218"));

        // 1. Create WebView
        webView = new WebView(this);
        FrameLayout.LayoutParams webParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        );
        webView.setLayoutParams(webParams);
        
        WebSettings webSettings = webView.getSettings();
        webSettings.setJavaScriptEnabled(true);
        webSettings.setDomStorageEnabled(true);
        webSettings.setDatabaseEnabled(true);
        webSettings.setAllowFileAccess(true);
        webSettings.setAllowContentAccess(true);
        webView.setWebViewClient(new WebViewClient());
        webView.setVisibility(View.GONE);

        // 2. Create Programmatic Configuration Screen (Teal/Dark-grey theme)
        configLayout = new LinearLayout(this);
        configLayout.setOrientation(LinearLayout.VERTICAL);
        FrameLayout.LayoutParams configParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        );
        configLayout.setLayoutParams(configParams);
        configLayout.setGravity(Gravity.CENTER);
        configLayout.setBackgroundColor(Color.parseColor("#121218"));
        configLayout.setPadding(60, 60, 60, 60);

        // Title
        TextView titleText = new TextView(this);
        titleText.setText("REYDM SECURE CHAT");
        titleText.setTextColor(Color.parseColor("#00adb5"));
        titleText.setTextSize(24);
        titleText.setTypeface(null, Typeface.BOLD);
        titleText.setGravity(Gravity.CENTER);
        
        LinearLayout.LayoutParams titleParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        titleParams.setMargins(0, 0, 0, 10);
        titleText.setLayoutParams(titleParams);

        // Subtitle
        TextView descText = new TextView(this);
        descText.setText("Enter the Chat Server IP/URL to connect:");
        descText.setTextColor(Color.parseColor("#888899"));
        descText.setTextSize(14);
        descText.setGravity(Gravity.CENTER);
        
        LinearLayout.LayoutParams descParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        descParams.setMargins(0, 0, 0, 30);
        descText.setLayoutParams(descParams);

        // URL EditText
        urlInput = new EditText(this);
        urlInput.setHint("e.g. http://192.168.1.10:5000");
        urlInput.setHintTextColor(Color.parseColor("#444455"));
        urlInput.setTextColor(Color.WHITE);
        urlInput.setTextSize(16);
        urlInput.setSingleLine(true);
        urlInput.setPadding(20, 20, 20, 20);
        
        // Custom background programmatically using drawable isn't easy in pure Java, 
        // so we'll just set background color and a thin border color
        urlInput.setBackgroundColor(Color.parseColor("#1a1a24"));
        
        LinearLayout.LayoutParams inputParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        inputParams.setMargins(0, 0, 0, 20);
        urlInput.setLayoutParams(inputParams);

        // Connect Button
        Button connectBtn = new Button(this);
        connectBtn.setText("Connect");
        connectBtn.setBackgroundColor(Color.parseColor("#00adb5"));
        connectBtn.setTextColor(Color.WHITE);
        connectBtn.setTextSize(16);
        connectBtn.setTypeface(null, Typeface.BOLD);
        
        LinearLayout.LayoutParams btnParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        connectBtn.setLayoutParams(btnParams);

        connectBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String url = urlInput.getText().toString().trim();
                if (!url.isEmpty()) {
                    if (!url.startsWith("http://") && !url.startsWith("https://")) {
                        url = "http://" + url;
                    }
                    prefs.edit().putString("server_url", url).apply();
                    loadUrl(url);
                }
            }
        });

        configLayout.addView(titleText);
        configLayout.addView(descText);
        configLayout.addView(urlInput);
        configLayout.addView(connectBtn);

        // 3. Floating Settings Gear Button (to change URL on the fly)
        Button floatBtn = new Button(this);
        floatBtn.setText("⚙");
        floatBtn.setTextSize(20);
        floatBtn.setTextColor(Color.parseColor("#00adb5"));
        floatBtn.setBackgroundColor(Color.TRANSPARENT);
        
        FrameLayout.LayoutParams floatParams = new FrameLayout.LayoutParams(
                120, 120,
                Gravity.TOP | Gravity.RIGHT
        );
        floatParams.setMargins(0, 20, 20, 0);
        floatBtn.setLayoutParams(floatParams);
        floatBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showConfigScreen();
            }
        });
        settingsButton = floatBtn;

        // Assemble root view
        rootLayout.addView(webView);
        rootLayout.addView(configLayout);
        rootLayout.addView(settingsButton);
        setContentView(rootLayout);

        // 4. Initial Load Check
        String savedUrl = prefs.getString("server_url", "");
        if (!savedUrl.isEmpty()) {
            loadUrl(savedUrl);
        } else {
            showConfigScreen();
        }
    }

    private void loadUrl(String url) {
        configLayout.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        settingsButton.setVisibility(View.VISIBLE);
        webView.loadUrl(url);
    }

    private void showConfigScreen() {
        webView.setVisibility(View.GONE);
        configLayout.setVisibility(View.VISIBLE);
        settingsButton.setVisibility(View.GONE);
        String savedUrl = prefs.getString("server_url", "");
        urlInput.setText(savedUrl);
    }

    @Override
    public void onBackPressed() {
        if (webView.getVisibility() == View.VISIBLE && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
