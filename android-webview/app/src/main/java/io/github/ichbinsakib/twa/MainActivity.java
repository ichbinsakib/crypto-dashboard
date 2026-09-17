package io.github.ichbinsakib.twa;

import android.app.Activity;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.content.Intent;

public class MainActivity extends Activity {

    private static final String HOST = "ichbinsakib.github.io";
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        webView.setBackgroundColor(0xFF0A0E14); // matches the dashboard's dark theme, so the
                                                  // padded-out system-bar area isn't a flash of
                                                  // white/transparent before the page paints
        setContentView(webView);

        // Android 15+ (API 35, our compile/targetSdk) enforces edge-to-edge and does NOT let
        // an app fully opt out via Window.setDecorFitsSystemWindows(true) -- that call alone
        // isn't reliable there, which is why the status bar was drawing right over the app's
        // own header. Padding the WebView directly by the real system bar insets works
        // regardless of that restriction, since it doesn't depend on opting out at all.
        webView.setOnApplyWindowInsetsListener((v, insets) -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            } else {
                v.setPadding(
                        insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                        insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            }
            return insets;
        });

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                Uri uri = Uri.parse(url);
                if (HOST.equals(uri.getHost())) {
                    return false; // load in-app
                }
                // Any other host (e.g. an outbound link) opens in the system browser.
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
                return true;
            }
        });

        webView.loadUrl(getString(R.string.start_url));
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        webView.destroy();
        super.onDestroy();
    }
}
