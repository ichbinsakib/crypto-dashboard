package io.github.ichbinsakib.twa;

import android.content.Context;
import android.content.SharedPreferences;
import android.webkit.JavascriptInterface;

/**
 * Exposed to the dashboard page as window.KairoAndroid. After sign-in the page hands over a
 * per-user, read-only notification token (never the login session itself -- two clients sharing
 * one rotating refresh token would sign each other out). The background check in
 * NotificationWorker reads it from here; sign-out clears it, which also stops notifications.
 * Only our own origin is ever loaded in the WebView, so only our own page can call this.
 */
public class KairoBridge {

    static final String PREFS = "kairo_notifications";
    static final String KEY_URL = "backend_url";
    static final String KEY_ANON = "backend_anon_key";
    static final String KEY_TOKEN = "notify_token";
    static final String KEY_LAST_SEEN = "last_seen_ts";

    private final Context context;

    public KairoBridge(Context context) {
        this.context = context.getApplicationContext();
    }

    @JavascriptInterface
    public void saveNotifyConfig(String url, String anonKey, String token) {
        if (url == null || anonKey == null || token == null || token.length() < 32) return;
        if (!url.startsWith("https://")) return;
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        SharedPreferences.Editor edit = prefs.edit();
        String previous = prefs.getString(KEY_TOKEN, "");
        edit.putString(KEY_URL, url).putString(KEY_ANON, anonKey).putString(KEY_TOKEN, token);
        // A different account (or first sign-in) starts from "now" so old history never floods the phone.
        if (!token.equals(previous)) edit.remove(KEY_LAST_SEEN);
        edit.apply();
    }

    @JavascriptInterface
    public String getVersion() {
        try {
            return context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "unknown";
        }
    }

    @JavascriptInterface
    public void clearNotifyConfig() {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply();
    }
}
