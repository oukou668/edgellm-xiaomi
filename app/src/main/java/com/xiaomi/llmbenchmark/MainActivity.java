package com.xiaomi.llmbenchmark;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import java.io.File;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final String EXTRA_AUTORUN = "autorun";
    private static final String EXTRA_MODEL_ID = "model_id";
    private static final String EXTRA_BENCHMARK_ID = "benchmark_id";

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    private Spinner modelSpinner;
    private Spinner benchmarkSpinner;
    private Button runButton;
    private ProgressBar progressBar;
    private TextView statusView;
    private TextView currentItemView;
    private TextView hardwareView;
    private TextView liveOutputView;
    private TextView logView;
    private List<ModelConfig> models;
    private List<BenchmarkConfig> benchmarks;
    private final StringBuilder liveOutputBuffer = new StringBuilder();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(createContentView());
        loadRegistries();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        maybeAutorun(intent);
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private View createContentView() {
        ScrollView scrollView = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(18), dp(18), dp(28));
        root.setBackgroundColor(0xFFF7F7F2);
        scrollView.addView(root);

        TextView title = new TextView(this);
        title.setText("Xiaomi 17 LLM Benchmark");
        title.setTextSize(22);
        title.setTextColor(0xFF18201D);
        title.setGravity(Gravity.START);
        root.addView(title, matchWrap());

        TextView subtitle = new TextView(this);
        subtitle.setText("MLC LLM QA benchmark with downloadable Qwen-family models");
        subtitle.setTextSize(14);
        subtitle.setTextColor(0xFF4C5A55);
        subtitle.setPadding(0, dp(4), 0, dp(16));
        root.addView(subtitle, matchWrap());

        modelSpinner = new Spinner(this);
        benchmarkSpinner = new Spinner(this);
        root.addView(label("Model"));
        root.addView(modelSpinner, matchWrap());
        root.addView(label("Benchmark"));
        root.addView(benchmarkSpinner, matchWrap());

        runButton = new Button(this);
        runButton.setText("Run Benchmark");
        runButton.setAllCaps(false);
        runButton.setOnClickListener(v -> runSelectedBenchmark());
        root.addView(runButton, matchWrapWithTop(dp(18)));

        progressBar = new ProgressBar(this);
        progressBar.setIndeterminate(true);
        progressBar.setVisibility(View.GONE);
        root.addView(progressBar, matchWrapWithTop(dp(12)));

        statusView = new TextView(this);
        statusView.setTextSize(14);
        statusView.setTextColor(0xFF1D6F5F);
        statusView.setPadding(0, dp(12), 0, dp(8));
        root.addView(statusView, matchWrap());

        currentItemView = new TextView(this);
        currentItemView.setTextSize(13);
        currentItemView.setTextColor(0xFF26332F);
        currentItemView.setPadding(0, dp(4), 0, dp(4));
        root.addView(currentItemView, matchWrap());

        root.addView(label("Live Hardware"));
        hardwareView = new TextView(this);
        hardwareView.setTextSize(13);
        hardwareView.setTextColor(0xFF18201D);
        hardwareView.setTextIsSelectable(true);
        hardwareView.setPadding(dp(10), dp(8), dp(10), dp(8));
        hardwareView.setBackgroundColor(0xFFE8EFEA);
        root.addView(hardwareView, matchWrap());

        root.addView(label("Live Output"));
        liveOutputView = new TextView(this);
        liveOutputView.setTextSize(12);
        liveOutputView.setTextColor(0xFF18201D);
        liveOutputView.setTextIsSelectable(true);
        liveOutputView.setPadding(dp(10), dp(8), dp(10), dp(8));
        liveOutputView.setMinLines(8);
        liveOutputView.setBackgroundColor(0xFFFFFFFF);
        root.addView(liveOutputView, matchWrap());

        root.addView(label("Run Log"));
        logView = new TextView(this);
        logView.setTextSize(12);
        logView.setTextColor(0xFF252B29);
        logView.setTextIsSelectable(true);
        root.addView(logView, matchWrap());
        return scrollView;
    }

    private TextView label(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(13);
        view.setTextColor(0xFF26332F);
        view.setPadding(0, dp(12), 0, dp(4));
        return view;
    }

    private void loadRegistries() {
        try {
            models = ModelRegistry.load(this).all();
            benchmarks = BenchmarkRegistry.load(this).all();
            modelSpinner.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, models));
            benchmarkSpinner.setAdapter(
                    new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, benchmarks));
            statusView.setText("Ready. Models: " + models.size() + ", benchmarks: " + benchmarks.size());
            maybeAutorun(getIntent());
        } catch (Exception error) {
            statusView.setText("Registry load failed: " + error.getMessage());
            runButton.setEnabled(false);
        }
    }

    private void runSelectedBenchmark() {
        if (modelSpinner.getSelectedItem() == null || benchmarkSpinner.getSelectedItem() == null) {
            statusView.setText("Select a model and benchmark first.");
            return;
        }
        ModelConfig model = (ModelConfig) modelSpinner.getSelectedItem();
        BenchmarkConfig benchmark = (BenchmarkConfig) benchmarkSpinner.getSelectedItem();
        runBenchmark(model, benchmark);
    }

    private void runBenchmark(ModelConfig model, BenchmarkConfig benchmark) {
        runButton.setEnabled(false);
        progressBar.setVisibility(View.VISIBLE);
        logView.setText("");
        liveOutputBuffer.setLength(0);
        currentItemView.setText("");
        hardwareView.setText("Waiting for first sample...");
        liveOutputView.setText("");
        statusView.setText("Running " + benchmark.displayName);

        executor.submit(
                () -> {
                    try {
                        BenchmarkRunner runner = new BenchmarkRunner(this);
                        BenchmarkRunReport report = runner.run(model, benchmark, new UiProgressSink());
                        File reportDir = new ReportWriter(this).write(report);
                        post(
                                () -> {
                                    progressBar.setVisibility(View.GONE);
                                    runButton.setEnabled(true);
                                    currentItemView.setText("Finished " + benchmark.benchmarkId);
                                    statusView.setText(
                                            "Done. Passed "
                                                    + report.passedCount()
                                                    + "/"
                                                    + report.results.size()
                                                    + ". Report: "
                                                    + reportDir.getAbsolutePath());
                                });
                    } catch (Exception error) {
                        post(
                                () -> {
                                    progressBar.setVisibility(View.GONE);
                                    runButton.setEnabled(true);
                                    statusView.setText(error.getClass().getSimpleName() + ": " + error.getMessage());
                                    appendLog("Benchmark failed: " + error.getMessage());
                                });
                    }
                });
    }

    private void maybeAutorun(Intent intent) {
        if (!shouldAutorun(intent)) {
            return;
        }
        if (models == null || benchmarks == null || models.isEmpty() || benchmarks.isEmpty()) {
            return;
        }
        if (!runButton.isEnabled()) {
            return;
        }
        String requestedModelId = intent.getStringExtra(EXTRA_MODEL_ID);
        String requestedBenchmarkId = intent.getStringExtra(EXTRA_BENCHMARK_ID);
        ModelConfig model = findModel(requestedModelId);
        BenchmarkConfig benchmark = findBenchmark(requestedBenchmarkId);
        modelSpinner.setSelection(models.indexOf(model));
        benchmarkSpinner.setSelection(benchmarks.indexOf(benchmark));
        statusView.setText("Autorun requested: " + benchmark.benchmarkId);
        mainHandler.post(() -> runBenchmark(model, benchmark));
    }

    private boolean shouldAutorun(Intent intent) {
        if (intent == null) {
            return false;
        }
        if (intent.getBooleanExtra(EXTRA_AUTORUN, false)) {
            return true;
        }
        String autorun = intent.getStringExtra(EXTRA_AUTORUN);
        if ("true".equalsIgnoreCase(autorun) || "1".equals(autorun)) {
            return true;
        }
        return intent.hasExtra(EXTRA_MODEL_ID) || intent.hasExtra(EXTRA_BENCHMARK_ID);
    }

    private ModelConfig findModel(String modelId) {
        if (modelId != null && !modelId.isEmpty()) {
            for (ModelConfig model : models) {
                if (modelId.equals(model.modelId)) {
                    return model;
                }
            }
            appendLog("Requested model not found, using first model: " + modelId);
        }
        return models.get(0);
    }

    private BenchmarkConfig findBenchmark(String benchmarkId) {
        if (benchmarkId != null && !benchmarkId.isEmpty()) {
            for (BenchmarkConfig benchmark : benchmarks) {
                if (benchmarkId.equals(benchmark.benchmarkId)) {
                    return benchmark;
                }
            }
            appendLog("Requested benchmark not found, using first benchmark: " + benchmarkId);
        }
        return benchmarks.get(0);
    }

    private void appendLog(String message) {
        post(() -> logView.append(message + "\n"));
    }

    private void showCurrentItem(int index, int total, BenchmarkItem item) {
        post(
                () -> {
                    currentItemView.setText(
                            "Item "
                                    + index
                                    + "/"
                                    + total
                                    + ": "
                                    + item.id
                                    + " | "
                                    + item.difficulty
                                    + " | "
                                    + item.category);
                    liveOutputBuffer.setLength(0);
                    liveOutputView.setText("");
                });
    }

    private void appendLiveOutput(String token, String fullText) {
        post(
                () -> {
                    if (fullText != null && fullText.length() < liveOutputBuffer.length()) {
                        liveOutputBuffer.setLength(0);
                    }
                    liveOutputBuffer.append(token == null ? "" : token);
                    int maxChars = 8000;
                    if (liveOutputBuffer.length() > maxChars) {
                        liveOutputBuffer.delete(0, liveOutputBuffer.length() - maxChars);
                    }
                    liveOutputView.setText(liveOutputBuffer.toString());
                });
    }

    private void showHardware(HardwareSample sample) {
        post(() -> hardwareView.setText(formatHardware(sample)));
    }

    private static String formatHardware(HardwareSample sample) {
        return "Phase: "
                + sample.phase
                + (sample.itemId == null || sample.itemId.isEmpty() ? "" : " | Item: " + sample.itemId)
                + "\nApp PSS: "
                + formatBytes(sample.appPssBytes)
                + " | Java heap: "
                + formatBytes(sample.appJavaHeapBytes)
                + " | Native heap: "
                + formatBytes(sample.appNativeHeapBytes)
                + "\nSystem memory used: "
                + String.format(Locale.US, "%.1f%%", sample.systemMemoryUsedRatio() * 100.0)
                + " | Available: "
                + formatBytes(sample.systemAvailMemBytes)
                + "\nBattery: "
                + formatTemp(sample.batteryTempC)
                + " | Thermal: "
                + formatTemp(sample.maxThermalTempC)
                + (sample.maxThermalZone == null || sample.maxThermalZone.isEmpty()
                        ? ""
                        : " (" + sample.maxThermalZone + ")")
                + "\nElapsed: "
                + sample.elapsedMs
                + " ms";
    }

    private static String formatBytes(long bytes) {
        if (bytes <= 0L) {
            return "n/a";
        }
        return String.format(Locale.US, "%.1f MiB", bytes / 1024.0 / 1024.0);
    }

    private static String formatTemp(double tempC) {
        if (Double.isNaN(tempC)) {
            return "n/a";
        }
        return String.format(Locale.US, "%.1f C", tempC);
    }

    private void post(Runnable runnable) {
        mainHandler.post(runnable);
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private static LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private static LinearLayout.LayoutParams matchWrapWithTop(int topDp) {
        LinearLayout.LayoutParams params = matchWrap();
        params.topMargin = topDp;
        return params;
    }

    private final class UiProgressSink implements ProgressSink {
        @Override
        public void onProgress(String message) {
            appendLog(message);
        }

        @Override
        public void onItemStarted(int index, int total, BenchmarkItem item) {
            showCurrentItem(index, total, item);
        }

        @Override
        public void onGenerationToken(String itemId, String token, String fullText) {
            appendLiveOutput(token, fullText);
        }

        @Override
        public void onHardwareSample(HardwareSample sample) {
            showHardware(sample);
        }
    }
}
