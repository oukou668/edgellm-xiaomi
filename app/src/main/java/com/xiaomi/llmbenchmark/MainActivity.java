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
    private TextView logView;
    private List<ModelConfig> models;
    private List<BenchmarkConfig> benchmarks;

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
        statusView.setText("Running " + benchmark.displayName);

        executor.submit(
                () -> {
                    try {
                        BenchmarkRunner runner = new BenchmarkRunner(this);
                        BenchmarkRunReport report = runner.run(model, benchmark, this::appendLog);
                        File reportDir = new ReportWriter(this).write(report);
                        post(
                                () -> {
                                    progressBar.setVisibility(View.GONE);
                                    runButton.setEnabled(true);
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
        if (intent == null || !intent.getBooleanExtra(EXTRA_AUTORUN, false)) {
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
}
