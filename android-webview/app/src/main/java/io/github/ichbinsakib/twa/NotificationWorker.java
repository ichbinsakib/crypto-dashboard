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
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * Runs periodically in the background (scheduled by WorkManager, see MainActivity), even when the
 * app isn't open. Reads the site's public notifications.json and notifies about events newer than the last one this
 * device saw (no account or token: the database is gone). WorkManager's minimum periodic interval is 15 minutes -- a platform floor.
 */
public class NotificationWorker extends Worker {

    private static final String CHANNEL_ID = "kairo_signals";
    private static final String FEED_URL = "https://ichbinsakib.github.io/crypto-dashboard/notifications.json";

    public NotificationWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        try {
            SharedPreferences prefs = getApplicationContext().getSharedPreferences(KairoBridge.PREFS, Context.MODE_PRIVATE);
            String lastSeen = prefs.getString(KairoBridge.KEY_LAST_SEEN, "");
            if (lastSeen.isEmpty()) {
                // First check for this sign-in: start from now, don't replay history.
                SimpleDateFormat iso = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
                iso.setTimeZone(TimeZone.getTimeZone("UTC"));
                prefs.edit().putString(KairoBridge.KEY_LAST_SEEN, iso.format(new Date())).apply();
                return Result.success();
            }

            // The feed is a public static file (newest first); notify about everything newer than the last one seen, oldest first.
            JSONArray feed = new JSONArray(fetchFeed());
            String newest = lastSeen;
            for (int i = feed.length() - 1; i >= 0; i--) {
                JSONObject event = feed.getJSONObject(i);
                String ts = event.getString("ts");
                if (ts.compareTo(lastSeen) <= 0) continue;
                postNotification(event);
                if (ts.compareTo(newest) > 0) newest = ts;
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

    private String fetchFeed() throws Exception {
        URL url = new URL(FEED_URL + "?t=" + System.currentTimeMillis());
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(10000);
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
        String portionKey = event.optString("portion_key", "");

        Intent openApp = new Intent(context, MainActivity.class);
        openApp.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        openApp.putExtra(MainActivity.EXTRA_GOTO_PORTION, portionKey);
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
