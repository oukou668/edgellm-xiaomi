package com.xiaomi.llmbenchmark;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
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
    private static final String EXTRA_BATCH_SIZE = "batch_size";
    private static final String EXTRA_STRESS_MODE = "stress_mode";
    private static final String EXTRA_BUNDLE_ID = "bundle_id";

    private static final int[] BATCH_SIZES = {1, 2, 4};
    private static final long POLL_INTERVAL_MS = 150L;

    // Palette
    private static final int COLOR_PAGE = 0xFFEDF1EF;
    private static final int COLOR_CARD = 0xFFFFFFFF;
    private static final int COLOR_ACCENT = 0xFF1D6F5F;
    private static final int COLOR_TITLE = 0xFF14201C;
    private static final int COLOR_MUTED = 0xFF5B6B66;
    private static final int COLOR_PROMPT_BG = 0xFFF1F5F3;
    private static final int COLOR_TERM_BG = 0xFF0E1512;
    private static final int COLOR_TERM_TEXT = 0xFFB8F0DA;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    private Spinner backendSpinner;
    private Spinner modelSpinner;
    private Spinner benchmarkSpinner;
    private Spinner batchSpinner;
    private Spinner modeSpinner;
    private Button runButton;
    private ProgressBar spinnerBar;
    private TextView statusView;

    private TextView jobModelView;
    private TextView jobDatasetView;
    private TextView jobMetaView;
    private TextView phaseView;
    private ProgressBar itemProgressBar;
    private TextView progressLabel;
    private TextView promptView;
    private TextView outputView;
    private ScrollView outputScroll;
    private TextView logView;

    private List<ModelConfig> models;
    private List<ModelConfig> visibleModels;
    private List<BenchmarkConfig> benchmarks;

    private volatile boolean polling;
    private final Runnable pollRunnable =
            new Runnable() {
                @Override
                public void run() {
                    renderLive(LiveStatus.get().snapshot());
                    if (polling) {
                        mainHandler.postDelayed(this, POLL_INTERVAL_MS);
                    }
                }
            };

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
    protected void onResume() {
        super.onResume();
        startPolling();
    }

    @Override
    protected void onPause() {
        polling = false;
        mainHandler.removeCallbacks(pollRunnable);
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        polling = false;
        mainHandler.removeCallbacks(pollRunnable);
        executor.shutdownNow();
        super.onDestroy();
    }

    private View createContentView() {
        ScrollView scrollView = new ScrollView(this);
        scrollView.setFillViewport(true);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(14), dp(16), dp(14), dp(28));
        root.setBackgroundColor(COLOR_PAGE);
        scrollView.addView(root);

        TextView title = new TextView(this);
        title.setText("Xiaomi LLM Benchmark");
        title.setTextSize(22);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setTextColor(COLOR_TITLE);
        root.addView(title, matchWrap());

        TextView subtitle = new TextView(this);
        subtitle.setText("端侧推理压测 · 实时查看 prompt 与生成内容");
        subtitle.setTextSize(13);
        subtitle.setTextColor(COLOR_MUTED);
        subtitle.setPadding(0, dp(2), 0, dp(12));
        root.addView(subtitle, matchWrap());

        // ---- Controls card ----
        LinearLayout controls = card(root, "运行配置");
        backendSpinner = new Spinner(this);
        modelSpinner = new Spinner(this);
        benchmarkSpinner = new Spinner(this);
        batchSpinner = new Spinner(this);
        modeSpinner = new Spinner(this);
        controls.addView(fieldLabel("后端 Backend"));
        controls.addView(backendSpinner, matchWrap());
        controls.addView(fieldLabel("模型 Model"));
        controls.addView(modelSpinner, matchWrap());
        controls.addView(fieldLabel("数据集 Benchmark"));
        controls.addView(benchmarkSpinner, matchWrap());
        LinearLayout twoCol = new LinearLayout(this);
        twoCol.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout batchCol = new LinearLayout(this);
        batchCol.setOrientation(LinearLayout.VERTICAL);
        batchCol.addView(fieldLabel("Batch size"));
        batchCol.addView(batchSpinner, matchWrap());
        LinearLayout modeCol = new LinearLayout(this);
        modeCol.setOrientation(LinearLayout.VERTICAL);
        modeCol.addView(fieldLabel("模式 Mode"));
        modeCol.addView(modeSpinner, matchWrap());
        LinearLayout.LayoutParams half =
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        half.rightMargin = dp(6);
        twoCol.addView(batchCol, half);
        LinearLayout.LayoutParams half2 =
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        half2.leftMargin = dp(6);
        twoCol.addView(modeCol, half2);
        controls.addView(twoCol, matchWrapWithTop(dp(2)));

        runButton = new Button(this);
        runButton.setText("运行 Benchmark");
        runButton.setAllCaps(false);
        runButton.setTextColor(Color.WHITE);
        runButton.setBackground(rounded(COLOR_ACCENT, dp(12)));
        runButton.setOnClickListener(v -> runSelectedBenchmark());
        controls.addView(runButton, matchWrapWithTop(dp(14)));

        spinnerBar = new ProgressBar(this);
        spinnerBar.setIndeterminate(true);
        spinnerBar.setVisibility(View.GONE);
        controls.addView(spinnerBar, matchWrapWithTop(dp(8)));

        statusView = new TextView(this);
        statusView.setTextSize(13);
        statusView.setTextColor(COLOR_ACCENT);
        statusView.setPadding(0, dp(8), 0, 0);
        controls.addView(statusView, matchWrap());

        // ---- Current job card ----
        LinearLayout job = card(root, "当前任务 Current Job");
        jobModelView = bodyText(job, "模型: —");
        jobDatasetView = bodyText(job, "数据集: —");
        jobMetaView = bodyText(job, "后端: — · batch: — · 用时: 0s");
        phaseView = bodyText(job, "阶段: idle");
        itemProgressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        itemProgressBar.setIndeterminate(false);
        itemProgressBar.setMax(100);
        itemProgressBar.setProgress(0);
        job.addView(itemProgressBar, matchWrapWithTop(dp(8)));
        progressLabel = bodyText(job, "样本 0/0");

        // ---- Current prompt card ----
        LinearLayout promptCard = card(root, "当前 Prompt");
        promptView = new TextView(this);
        promptView.setTextSize(12);
        promptView.setTextColor(COLOR_TITLE);
        promptView.setTypeface(Typeface.MONOSPACE);
        promptView.setTextIsSelectable(true);
        promptView.setPadding(dp(10), dp(10), dp(10), dp(10));
        promptView.setBackground(rounded(COLOR_PROMPT_BG, dp(10)));
        ScrollView promptScroll = new ScrollView(this);
        promptScroll.addView(promptView);
        promptCard.addView(promptScroll, fixedHeight(dp(132)));

        // ---- Live generation card ----
        LinearLayout genCard = card(root, "实时推理输出 Live Generation");
        outputView = new TextView(this);
        outputView.setTextSize(12);
        outputView.setTextColor(COLOR_TERM_TEXT);
        outputView.setTypeface(Typeface.MONOSPACE);
        outputView.setTextIsSelectable(true);
        outputView.setPadding(dp(10), dp(10), dp(10), dp(10));
        outputView.setBackground(rounded(COLOR_TERM_BG, dp(10)));
        outputScroll = new ScrollView(this);
        outputScroll.addView(outputView);
        genCard.addView(outputScroll, fixedHeight(dp(300)));

        // ---- Run log card ----
        LinearLayout logCard = card(root, "运行日志 Log");
        logView = new TextView(this);
        logView.setTextSize(11);
        logView.setTextColor(0xFF394641);
        logView.setTypeface(Typeface.MONOSPACE);
        logView.setTextIsSelectable(true);
        logCard.addView(logView, matchWrap());

        return scrollView;
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
            List<String> batchLabels = new ArrayList<>();
            for (int size : BATCH_SIZES) {
                batchLabels.add(String.valueOf(size));
            }
            batchSpinner.setAdapter(
                    new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, batchLabels));
            modeSpinner.setAdapter(
                    new ArrayAdapter<>(
                            this,
                            android.R.layout.simple_spinner_dropdown_item,
                            new String[] {"真实推理 Real", "Dummy 流水线"}));
            updateModelSpinner(ModelConfig.BACKEND_MLC);
            benchmarkSpinner.setAdapter(
                    new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, benchmarks));
            statusView.setText("就绪 · 模型 " + models.size() + " 个, 数据集 " + benchmarks.size() + " 个");
            maybeAutorun(getIntent());
        } catch (Exception error) {
            statusView.setText("Registry load failed: " + error.getMessage());
            runButton.setEnabled(false);
        }
    }

    private void runSelectedBenchmark() {
        if (modelSpinner.getSelectedItem() == null || benchmarkSpinner.getSelectedItem() == null) {
            statusView.setText("请先选择模型与数据集。");
            return;
        }
        ModelConfig model = (ModelConfig) modelSpinner.getSelectedItem();
        BenchmarkConfig benchmark = (BenchmarkConfig) benchmarkSpinner.getSelectedItem();
        int batchSize = BATCH_SIZES[Math.max(0, batchSpinner.getSelectedItemPosition())];
        String smokeType =
                modeSpinner.getSelectedItemPosition() == 1
                        ? BenchmarkRunOptions.SMOKE_DUMMY
                        : BenchmarkRunOptions.SMOKE_REAL;
        BenchmarkRunOptions options =
                new BenchmarkRunOptions(model.backendId, smokeType, 1, 0, batchSize, batchSize > 1);
        runBenchmark(model, benchmark, options);
    }

    private void runBenchmark(ModelConfig model, BenchmarkConfig benchmark, BenchmarkRunOptions options) {
        runButton.setEnabled(false);
        spinnerBar.setVisibility(View.VISIBLE);
        logView.setText("");
        promptView.setText("");
        outputView.setText("");
        statusView.setText("正在运行 " + benchmark.displayName + " · " + options.backendId
                + " · batch " + options.batchSize);
        startPolling();

        executor.submit(
                () -> {
                    try {
                        BenchmarkRunner runner = new BenchmarkRunner(this);
                        BenchmarkRunReport report = runner.run(model, benchmark, options, this::appendLog);
                        File reportDir = new ReportWriter(this).write(report);
                        post(
                                () -> {
                                    stopPolling();
                                    spinnerBar.setVisibility(View.GONE);
                                    runButton.setEnabled(true);
                                    statusView.setText(
                                            "完成 · 通过 "
                                                    + report.passedCount()
                                                    + "/"
                                                    + report.results.size()
                                                    + " · 报告: "
                                                    + reportDir.getName());
                                });
                    } catch (Exception error) {
                        post(
                                () -> {
                                    stopPolling();
                                    spinnerBar.setVisibility(View.GONE);
                                    runButton.setEnabled(true);
                                    statusView.setText(error.getClass().getSimpleName() + ": " + error.getMessage());
                                    appendLog("Benchmark failed: " + error.getMessage());
                                });
                    }
                });
    }

    private void startPolling() {
        polling = true;
        mainHandler.removeCallbacks(pollRunnable);
        mainHandler.post(pollRunnable);
    }

    private void stopPolling() {
        polling = false;
        mainHandler.removeCallbacks(pollRunnable);
        renderLive(LiveStatus.get().snapshot());
    }

    private void renderLive(LiveStatus.Snapshot s) {
        String model = s.modelDisplay.isEmpty() ? s.modelId : s.modelDisplay;
        jobModelView.setText("模型: " + (model.isEmpty() ? "—" : model));
        String dataset = s.benchmarkDisplay.isEmpty() ? s.benchmarkId : s.benchmarkDisplay;
        jobDatasetView.setText("数据集: " + (dataset.isEmpty() ? "—" : dataset));
        long elapsed = s.jobStartedMs > 0 ? Math.max(0, System.currentTimeMillis() - s.jobStartedMs) / 1000 : 0;
        jobMetaView.setText(
                "后端: " + (s.backendId.isEmpty() ? "—" : s.backendId)
                        + " · batch: " + s.batchSize
                        + " · 用时: " + elapsed + "s");
        phaseView.setText("阶段: " + (s.phase.isEmpty() ? "idle" : s.phase) + (s.running ? " ●" : ""));

        if (s.itemTotal > 0) {
            itemProgressBar.setIndeterminate(false);
            itemProgressBar.setMax(s.itemTotal);
            itemProgressBar.setProgress(Math.min(s.itemIndex, s.itemTotal));
        } else {
            itemProgressBar.setIndeterminate(s.running);
        }
        StringBuilder label = new StringBuilder();
        label.append("样本 ").append(s.itemIndex).append('/').append(s.itemTotal);
        if (s.repeatTotal > 1) {
            label.append(" · 轮次 ").append(s.repeatIndex).append('/').append(s.repeatTotal);
        }
        if (!s.itemId.isEmpty()) {
            label.append(" · ").append(s.itemId);
        }
        progressLabel.setText(label.toString());

        if (!s.prompt.equals(promptView.getText().toString())) {
            promptView.setText(s.prompt);
        }
        if (!s.output.equals(outputView.getText().toString())) {
            outputView.setText(s.output);
            outputScroll.post(() -> outputScroll.fullScroll(View.FOCUS_DOWN));
        }
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
        int batchSize = intent.getIntExtra(EXTRA_BATCH_SIZE, 1);
        selectBatch(batchSize);
        statusView.setText("自动运行: " + benchmark.benchmarkId);
        BenchmarkRunOptions options =
                new BenchmarkRunOptions(
                        requestedBackendId,
                        intent.getStringExtra(EXTRA_SMOKE_TYPE),
                        intent.getIntExtra(EXTRA_REPEAT_COUNT, 1),
                        intent.getIntExtra(EXTRA_WARMUP_COUNT, 0),
                        batchSize,
                        intent.getBooleanExtra(EXTRA_STRESS_MODE, false));
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
        visibleModels = new ArrayList<>();
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

    private void selectBatch(int batchSize) {
        for (int i = 0; i < BATCH_SIZES.length; i++) {
            if (BATCH_SIZES[i] == batchSize) {
                batchSpinner.setSelection(i);
                return;
            }
        }
    }

    private void post(Runnable runnable) {
        mainHandler.post(runnable);
    }

    // ---- view helpers ----

    private LinearLayout card(LinearLayout parent, String title) {
        LinearLayout cardView = new LinearLayout(this);
        cardView.setOrientation(LinearLayout.VERTICAL);
        cardView.setPadding(dp(14), dp(12), dp(14), dp(14));
        cardView.setBackground(rounded(COLOR_CARD, dp(16)));
        TextView header = new TextView(this);
        header.setText(title);
        header.setTextSize(13);
        header.setTypeface(Typeface.DEFAULT_BOLD);
        header.setTextColor(COLOR_ACCENT);
        header.setPadding(0, 0, 0, dp(8));
        cardView.addView(header, matchWrap());
        LinearLayout.LayoutParams params = matchWrap();
        params.topMargin = dp(10);
        parent.addView(cardView, params);
        return cardView;
    }

    private TextView fieldLabel(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(12);
        view.setTextColor(COLOR_MUTED);
        view.setPadding(0, dp(8), 0, dp(2));
        return view;
    }

    private TextView bodyText(LinearLayout parent, String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(13);
        view.setTextColor(COLOR_TITLE);
        view.setPadding(0, dp(2), 0, dp(2));
        parent.addView(view, matchWrap());
        return view;
    }

    private GradientDrawable rounded(int color, int radius) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(radius);
        return drawable;
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private static LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private static LinearLayout.LayoutParams matchWrapWithTop(int topPx) {
        LinearLayout.LayoutParams params = matchWrap();
        params.topMargin = topPx;
        return params;
    }

    private static LinearLayout.LayoutParams fixedHeight(int heightPx) {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, heightPx);
    }
}
