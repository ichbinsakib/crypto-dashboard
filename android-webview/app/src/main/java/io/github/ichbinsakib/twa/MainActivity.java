package io.github.ichbinsakib.twa;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.ViewTreeObserver;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.content.Intent;

import androidx.core.app.ActivityCompat;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import java.util.concurrent.TimeUnit;

public class MainActivity extends Activity {

    private static final String HOST = "ichbinsakib.github.io";
    /** Set by NotificationWorker on the Intent it opens when a notification is tapped -- the same
     * portion_key the dashboard already stamps on every notification event server-side. */
    public static final String EXTRA_GOTO_PORTION = "goto_portion";
    private WebView webView;
    private boolean pageLoaded = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        webView.setBackgroundColor(0xFFEEF3FB); // matches the dashboard's light theme, so the
                                                  // padded-out system-bar area isn't a flash of
                                                  // white/transparent before the page paints
        setContentView(webView);

        // The page is laid out by the system BELOW the status bar and ABOVE the navigation bar. This app targets Android 14
        // (API 34) on purpose: Android 15+ only forces apps to draw edge-to-edge when they target API 35 or newer, and on some
        // phones (Xiaomi HyperOS in particular) the window-inset callbacks that edge-to-edge relies on never fire, which left
        // the status bar drawn on top of the header. Without that enforcement no inset handling is needed at all.

        // The dashboard page passes its per-user notification token here after sign-in.
        webView.addJavascriptInterface(new KairoBridge(this), "KairoAndroid");

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

            @Override
            public void onPageFinished(WebView view, String url) {
                pageLoaded = true;
            }
        });

        webView.loadUrl(urlFor(getIntent()));

        requestNotificationPermissionIfNeeded();
        scheduleNotificationChecks();
    }

    /** start_url, with #goto=<portion> appended if this intent came from tapping a notification
     * (see NotificationWorker) -- the page itself reads that hash once it finishes rendering and
     * navigates to the matching tab (app.js: applyPendingDeepLink). */
    private String urlFor(Intent intent) {
        String base = getString(R.string.start_url);
        String portion = intent != null ? intent.getStringExtra(EXTRA_GOTO_PORTION) : null;
        return (portion == null || portion.isEmpty()) ? base : base + "#goto=" + Uri.encode(portion);
    }

    /**
     * singleTask launch mode means a notification tapped while the app is already running (even in
     * the background) arrives here instead of a fresh onCreate. If the page already finished
     * loading, jump straight there via JS; otherwise it's still mid-load and app.js's own
     * applyPendingDeepLink (fed by the URL hash) will handle it once rendering finishes.
     */
    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String portion = intent.getStringExtra(EXTRA_GOTO_PORTION);
        if (portion == null || portion.isEmpty()) return;
        if (pageLoaded) {
            String js = "window.kairoGoto && window.kairoGoto('" + portion.replace("'", "") + "')";
            webView.evaluateJavascript(js, null);
        } else {
            webView.loadUrl(urlFor(intent));
        }
    }

    /** Android 13+ (API 33) requires runtime permission before any notification can be shown. */
    private void requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ActivityCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(
                        this, new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1001);
            }
        }
    }

    /**
     * Schedules the background signal/win/loss check to run every 15 minutes (WorkManager's
     * platform-enforced minimum for periodic work -- can't be tightened further) even when the
     * app isn't open. enqueueUniquePeriodicWork with KEEP means re-opening the app never
     * creates a duplicate schedule; only the first launch after install actually enqueues it.
     */
    private void scheduleNotificationChecks() {
        PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(
                NotificationWorker.class, 15, TimeUnit.MINUTES)
                .build();
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
                "kairo_notification_check", ExistingPeriodicWorkPolicy.KEEP, request);
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
