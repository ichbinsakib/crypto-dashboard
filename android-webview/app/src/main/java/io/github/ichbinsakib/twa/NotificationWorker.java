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

/**
 * Runs periodically in the background (scheduled by WorkManager, see MainActivity) even when
 * the app isn't open. Polls the same small events feed dashboard.py already writes to the
 * live site on every cycle, and posts a system notification for anything newer than the last
 * event this device has already seen. WorkManager's minimum periodic interval is 15 minutes --
 * that's a platform floor, not something this code can tighten further.
 */
public class NotificationWorker extends Worker {

    private static final String FEED_URL = "https://ichbinsakib.github.io/crypto-dashboard/notifications.json";
    private static final String PREFS = "kairo_notifications";
    private static final String KEY_LAST_SEEN_TS = "last_seen_ts";
    private static final String CHANNEL_ID = "kairo_signals";

    public NotificationWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        try {
            String json = fetch(FEED_URL);
            JSONObject root = new JSONObject(json);
            JSONArray events = root.getJSONArray("events");

            SharedPreferences prefs = getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            String lastSeenTs = prefs.getString(KEY_LAST_SEEN_TS, "");

            // Events are newest-first; walk oldest-first so notifications post in the order
            // things actually happened, and track the max ts seen to persist afterward.
            String newestTs = lastSeenTs;
            for (int i = events.length() - 1; i >= 0; i--) {
                JSONObject event = events.getJSONObject(i);
                String ts = event.getString("ts");
                if (ts.compareTo(lastSeenTs) <= 0) continue;
                postNotification(event);
                if (ts.compareTo(newestTs) > 0) newestTs = ts;
            }

            if (!newestTs.equals(lastSeenTs)) {
                prefs.edit().putString(KEY_LAST_SEEN_TS, newestTs).apply();
            }
            return Result.success();
        } catch (Exception e) {
            // Best-effort: a failed check (offline, feed briefly unavailable) just tries again
            // next cycle. WorkManager already handles retry/backoff on Result.retry() but a
            // transient network blip every 15 minutes isn't worth escalating.
            return Result.success();
        }
    }

    private String fetch(String urlStr) throws Exception {
        URL url = new URL(urlStr);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(10000);
        conn.setRequestProperty("Cache-Control", "no-cache");
        StringBuilder sb = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()))) {
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
