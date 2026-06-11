package com.xiaomi.llmbenchmark;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;
import java.io.File;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class BenchmarkService extends Service {
    private static final String TAG = "XiaomiLlmBenchmark";
    private static final String CHANNEL_ID = "benchmark_runs";
    private static final int NOTIFICATION_ID = 17;

    private ExecutorService executor;

    @Override
    public void onCreate() {
        super.onCreate();
        executor = Executors.newSingleThreadExecutor();
        startForeground(NOTIFICATION_ID, notification("Benchmark starting"));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Intent runIntent = intent == null ? new Intent() : intent;
        executor.submit(() -> runBenchmark(runIntent, startId));
        return START_NOT_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        if (executor != null) {
            executor.shutdownNow();
        }
        super.onDestroy();
    }

    private void runBenchmark(Intent intent, int startId) {
        try {
            List<ModelConfig> models = ModelRegistry.load(this).all();
            List<BenchmarkConfig> benchmarks = BenchmarkRegistry.load(this).all();
            String backendId = valueOrDefault(intent.getStringExtra("backend_id"), ModelConfig.BACKEND_MLC);
            ModelConfig model = findModel(models, backendId, intent.getStringExtra("model_id"));
            String bundleId = intent.getStringExtra("bundle_id");
            BenchmarkConfig benchmark =
                    bundleId == null || bundleId.isEmpty()
                            ? findBenchmark(benchmarks, intent.getStringExtra("benchmark_id"))
                            : BenchmarkRegistry.loadBundle(this, bundleId);
            BenchmarkRunOptions options =
                    new BenchmarkRunOptions(
                            backendId,
                            intent.getStringExtra("smoke_type"),
                            intent.getIntExtra("repeat_count", 1),
                            intent.getIntExtra("warmup_count", 0),
                            intent.getIntExtra("batch_size", 1),
                            intent.getBooleanExtra("stress_mode", false),
                            intent.getBooleanExtra("unload_after_run", false));
            Log.i(TAG, "Service benchmark starting: " + backendId + "/" + model.modelId + " " + benchmark.benchmarkId);
            BenchmarkRunReport report =
                    new BenchmarkRunner(this)
                            .run(
                                    model,
                                    benchmark,
                                    options,
                                    message -> {
                                        Log.i(TAG, message);
                                        updateNotification(message);
                                    });
            File reportDir = new ReportWriter(this).write(report);
            Log.i(TAG, "Service benchmark report: " + reportDir.getAbsolutePath());
            updateNotification("Report written: " + reportDir.getName());
        } catch (Exception error) {
            Log.e(TAG, "Service benchmark failed", error);
            updateNotification(error.getClass().getSimpleName() + ": " + error.getMessage());
        } finally {
            stopForeground(STOP_FOREGROUND_DETACH);
            stopSelf(startId);
        }
    }

    private ModelConfig findModel(List<ModelConfig> models, String backendId, String modelId) {
        if (modelId != null && !modelId.isEmpty()) {
            for (ModelConfig model : models) {
                if (backendId.equals(model.backendId) && modelId.equals(model.modelId)) {
                    return model;
                }
            }
        }
        for (ModelConfig model : models) {
            if (backendId.equals(model.backendId)) {
                return model;
            }
        }
        return models.get(0);
    }

    private BenchmarkConfig findBenchmark(List<BenchmarkConfig> benchmarks, String benchmarkId) {
        if (benchmarkId != null && !benchmarkId.isEmpty()) {
            for (BenchmarkConfig benchmark : benchmarks) {
                if (benchmarkId.equals(benchmark.benchmarkId)) {
                    return benchmark;
                }
            }
        }
        return benchmarks.get(0);
    }

    private Notification notification(String text) {
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel =
                    new NotificationChannel(CHANNEL_ID, "Benchmark Runs", NotificationManager.IMPORTANCE_LOW);
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }
        return builder
                .setSmallIcon(android.R.drawable.stat_sys_upload_done)
                .setContentTitle("LLM benchmark")
                .setContentText(text)
                .setOngoing(true)
                .build();
    }

    private void updateNotification(String text) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.notify(NOTIFICATION_ID, notification(text));
        }
    }

    private static String valueOrDefault(String value, String fallback) {
        return value == null || value.isEmpty() ? fallback : value;
    }
}
