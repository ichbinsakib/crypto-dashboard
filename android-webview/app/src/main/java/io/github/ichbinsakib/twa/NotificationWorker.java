package io.github.ichbinsakib.twa;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * Runs periodically in the background (scheduled by WorkManager, see MainActivity), even when the
 * app isn't open. Asks the backend for events newer than the last one this device saw, using the
 * per-user notification token the signed-in dashboard page handed over (KairoBridge). The backend
 * only returns events for sections that user was granted, so nobody is notified about anything
 * they can't open. WorkManager's minimum periodic interval is 15 minutes -- a platform floor.
 * No token (signed out) means nothing to do.
 */
public class NotificationWorker extends Worker {

    private static final String CHANNEL_ID = "kairo_signals";

    public NotificationWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        try {
            SharedPreferences prefs = getApplicationContext().getSharedPreferences(KairoBridge.PREFS, Context.MODE_PRIVATE);
            String url = prefs.getString(KairoBridge.KEY_URL, "");
            String anon = prefs.getString(KairoBridge.KEY_ANON, "");
            String token = prefs.getString(KairoBridge.KEY_TOKEN, "");
            if (url.isEmpty() || anon.isEmpty() || token.isEmpty()) return Result.success();

            String lastSeen = prefs.getString(KairoBridge.KEY_LAST_SEEN, "");
            if (lastSeen.isEmpty()) {
                // First check for this sign-in: start from now, don't replay history.
                SimpleDateFormat iso = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
                iso.setTimeZone(TimeZone.getTimeZone("UTC"));
                prefs.edit().putString(KairoBridge.KEY_LAST_SEEN, iso.format(new Date())).apply();
                return Result.success();
            }

            JSONArray events = new JSONArray(rpcNotificationsSince(url, anon, token, lastSeen));
            String newest = lastSeen;
            for (int i = 0; i < events.length(); i++) {           // server returns oldest-first
                JSONObject event = events.getJSONObject(i);
                postNotification(event);
                newest = event.getString("ts");
            }
            if (!newest.equals(lastSeen)) {
                prefs.edit().putString(KairoBridge.KEY_LAST_SEEN, newest).apply();
            }
            return Result.success();
        } catch (Exception e) {
            // Offline, backend briefly unavailable, or the token was revoked: just try next cycle.
            return Result.success();
        }
    }

    private String rpcNotificationsSince(String baseUrl, String anonKey, String token, String since) throws Exception {
        URL url = new URL(baseUrl + "/rest/v1/rpc/notifications_since");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(10000);
        conn.setRequestMethod("POST");
        conn.setDoOutput(true);
        conn.setRequestProperty("apikey", anonKey);
        conn.setRequestProperty("Authorization", "Bearer " + anonKey);
        conn.setRequestProperty("Content-Type", "application/json");
        JSONObject body = new JSONObject().put("p_token", token).put("p_since", since);
        try (OutputStream out = conn.getOutputStream()) {
            out.write(body.toString().getBytes(StandardCharsets.UTF_8));
        }
        if (conn.getResponseCode() != 200) throw new Exception("HTTP " + conn.getResponseCode());
        StringBuilder sb = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) sb.append(line);
        } finally {
            conn.disconnect();
        }
        return sb.toString();
    }

    private void postNotification(JSONObject event) throws Exception {
        Context context = getApplicationContext();
        ensureChannel(context);

        String title = event.optString("title", "Kairo");
        String body = event.optString("body", "");
        String id = event.optString("id", String.valueOf(System.currentTimeMillis()));

        Intent openApp = new Intent(context, MainActivity.class);
        openApp.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                context, id.hashCode(), openApp,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .setAutoCancel(true)
                .setContentIntent(pendingIntent);

        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.notify(id.hashCode(), builder.build());
        }
    }

    private void ensureChannel(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager != null && manager.getNotificationChannel(CHANNEL_ID) == null) {
                NotificationChannel channel = new NotificationChannel(
                        CHANNEL_ID, "Signals & Results", NotificationManager.IMPORTANCE_DEFAULT);
                channel.setDescription("New scanner signals and win/loss/expiry results");
                manager.createNotificationChannel(channel);
            }
        }
    }
}
