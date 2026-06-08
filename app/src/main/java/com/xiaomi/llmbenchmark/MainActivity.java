package com.xiaomi.llmbenchmark;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.AdapterView;
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
    private static final String EXTRA_BACKEND_ID = "backend_id";
    private static final String EXTRA_MODEL_ID = "model_id";
    private static final String EXTRA_BENCHMARK_ID = "benchmark_id";
    private static final String EXTRA_SMOKE_TYPE = "smoke_type";
    private static final String EXTRA_REPEAT_COUNT = "repeat_count";
    private static final String EXTRA_WARMUP_COUNT = "warmup_count";
    private static final String EXTRA_BUNDLE_ID = "bundle_id";

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    private Spinner backendSpinner;
    private Spinner modelSpinner;
    private Spinner benchmarkSpinner;
    private Button runButton;
    private ProgressBar progressBar;
    private TextView statusView;
    private TextView logView;
    private List<ModelConfig> models;
    private List<ModelConfig> visibleModels;
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

        backendSpinner = new Spinner(this);
        modelSpinner = new Spinner(this);
        benchmarkSpinner = new Spinner(this);
        root.addView(label("Backend"));
        root.addView(backendSpinner, matchWrap());
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
            backendSpinner.setAdapter(
                    new ArrayAdapter<>(
                            this,
                            android.R.layout.simple_spinner_dropdown_item,
                            new String[] {ModelConfig.BACKEND_MLC, ModelConfig.BACKEND_LLAMA_CPP}));
            backendSpinner.setOnItemSelectedListener(
                    new AdapterView.OnItemSelectedListener() {
                        @Override
                        public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                            updateModelSpinner(String.valueOf(parent.getItemAtPosition(position)));
                        }

                        @Override
                        public void onNothingSelected(AdapterView<?> parent) {}
                    });
            updateModelSpinner(ModelConfig.BACKEND_MLC);
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
        runBenchmark(model, benchmark, BenchmarkRunOptions.defaults(model.backendId));
    }

    private void runBenchmark(ModelConfig model, BenchmarkConfig benchmark, BenchmarkRunOptions options) {
        runButton.setEnabled(false);
        progressBar.setVisibility(View.VISIBLE);
        logView.setText("");
        statusView.setText("Running " + benchmark.displayName + " on " + options.backendId);

        executor.submit(
                () -> {
                    try {
                        BenchmarkRunner runner = new BenchmarkRunner(this);
                        BenchmarkRunReport report = runner.run(model, benchmark, options, this::appendLog);
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
        String requestedBackendId = intent.getStringExtra(EXTRA_BACKEND_ID);
        String requestedBundleId = intent.getStringExtra(EXTRA_BUNDLE_ID);
        if (requestedBackendId == null || requestedBackendId.isEmpty()) {
            requestedBackendId = ModelConfig.BACKEND_MLC;
        }
        selectBackend(requestedBackendId);
        ModelConfig model = findModel(requestedBackendId, requestedModelId);
        BenchmarkConfig benchmark;
        try {
            benchmark =
                    requestedBundleId == null || requestedBundleId.isEmpty()
                            ? findBenchmark(requestedBenchmarkId)
                            : BenchmarkRegistry.loadBundle(this, requestedBundleId);
        } catch (Exception error) {
            appendLog("Requested bundle failed, using asset benchmark: " + error.getMessage());
            benchmark = findBenchmark(requestedBenchmarkId);
        }
        modelSpinner.setSelection(visibleModels.indexOf(model));
        if (benchmarks.indexOf(benchmark) >= 0) {
            benchmarkSpinner.setSelection(benchmarks.indexOf(benchmark));
        }
        statusView.setText("Autorun requested: " + benchmark.benchmarkId);
        BenchmarkRunOptions options =
                new BenchmarkRunOptions(
                        requestedBackendId,
                        intent.getStringExtra(EXTRA_SMOKE_TYPE),
                        intent.getIntExtra(EXTRA_REPEAT_COUNT, 1),
                        intent.getIntExtra(EXTRA_WARMUP_COUNT, 0));
        final BenchmarkConfig selectedBenchmark = benchmark;
        mainHandler.post(() -> runBenchmark(model, selectedBenchmark, options));
    }

    private ModelConfig findModel(String backendId, String modelId) {
        if (modelId != null && !modelId.isEmpty()) {
            for (ModelConfig model : models) {
                if (backendId.equals(model.backendId) && modelId.equals(model.modelId)) {
                    return model;
                }
            }
            appendLog("Requested model not found, using first model: " + modelId);
        }
        for (ModelConfig model : models) {
            if (backendId.equals(model.backendId)) {
                return model;
            }
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

    private void updateModelSpinner(String backendId) {
        visibleModels = new java.util.ArrayList<>();
        for (ModelConfig model : models) {
            if (backendId.equals(model.backendId)) {
                visibleModels.add(model);
            }
        }
        modelSpinner.setAdapter(
                new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, visibleModels));
    }

    private void selectBackend(String backendId) {
        for (int i = 0; i < backendSpinner.getCount(); i++) {
            if (backendId.equals(backendSpinner.getItemAtPosition(i))) {
                backendSpinner.setSelection(i);
                updateModelSpinner(backendId);
                return;
            }
        }
        updateModelSpinner(ModelConfig.BACKEND_MLC);
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
