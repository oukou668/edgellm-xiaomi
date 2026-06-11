package com.xiaomi.llmbenchmark;

/**
 * Thread-safe holder for the currently running job so the UI can show, in real time, which
 * model/dataset is running, progress, the prompt being inferred, and the reasoning text generated
 * so far. Written by {@link BenchmarkRunner} (job/item lifecycle) and by the inference engines
 * (streamed tokens). The UI polls {@link #snapshot()} on a timer.
 *
 * <p>The engines stream tokens here directly: {@link MlcInferenceEngine} pushes each delta, and the
 * llama.cpp native layer calls {@link #appendToken} per token via JNI. Only tokens for the current
 * "primary" item (the one shown in the UI) are accumulated; for batched runs the first sequence in
 * the batch is the primary and the others are ignored for display.
 */
final class LiveStatus {
    private static final int MAX_OUTPUT_CHARS = 200_000;
    private static final LiveStatus INSTANCE = new LiveStatus();

    static LiveStatus get() {
        return INSTANCE;
    }

    /** Native (llama.cpp) and MLC streaming entrypoint. Safe to call from any thread. */
    static void appendToken(String itemId, String piece) {
        INSTANCE.append(itemId, piece);
    }

    private boolean running;
    private String backendId = "";
    private String modelId = "";
    private String modelDisplay = "";
    private String benchmarkId = "";
    private String benchmarkDisplay = "";
    private int batchSize = 1;
    private int totalItems;
    private long jobStartedMs;

    private String phase = "";
    private String itemId = "";
    private String prompt = "";
    private String expected = "";
    private int itemIndex;
    private int itemTotal;
    private int repeatIndex;
    private int repeatTotal;
    private long itemStartedMs;
    private final StringBuilder output = new StringBuilder();

    private LiveStatus() {}

    synchronized void startJob(
            String backendId,
            String modelId,
            String modelDisplay,
            String benchmarkId,
            String benchmarkDisplay,
            int batchSize,
            int totalItems,
            int repeatTotal) {
        this.running = true;
        this.backendId = nz(backendId);
        this.modelId = nz(modelId);
        this.modelDisplay = nz(modelDisplay);
        this.benchmarkId = nz(benchmarkId);
        this.benchmarkDisplay = nz(benchmarkDisplay);
        this.batchSize = Math.max(1, batchSize);
        this.totalItems = totalItems;
        this.repeatTotal = Math.max(1, repeatTotal);
        this.repeatIndex = 0;
        this.jobStartedMs = System.currentTimeMillis();
        this.phase = "starting";
        this.itemIndex = 0;
        this.itemTotal = totalItems;
        this.itemId = "";
        this.prompt = "";
        this.expected = "";
        this.output.setLength(0);
    }

    synchronized void setPhase(String phase) {
        this.phase = nz(phase);
    }

    synchronized void startItem(
            int itemIndex, int itemTotal, int repeatIndex, String itemId, String prompt, String expected) {
        this.itemIndex = itemIndex;
        this.itemTotal = itemTotal;
        this.repeatIndex = repeatIndex;
        this.itemId = nz(itemId);
        this.prompt = nz(prompt);
        this.expected = nz(expected);
        this.phase = "inference";
        this.itemStartedMs = System.currentTimeMillis();
        this.output.setLength(0);
    }

    synchronized void append(String tokenItemId, String piece) {
        if (!running || piece == null || piece.isEmpty()) {
            return;
        }
        // Only accumulate the primary (currently displayed) item's stream.
        if (itemId == null || itemId.isEmpty() || !itemId.equals(tokenItemId)) {
            return;
        }
        output.append(piece);
        if (output.length() > MAX_OUTPUT_CHARS) {
            output.delete(0, output.length() - MAX_OUTPUT_CHARS);
        }
    }

    synchronized void finishJob() {
        this.running = false;
        this.phase = "done";
    }

    synchronized Snapshot snapshot() {
        return new Snapshot(
                running,
                backendId,
                modelId,
                modelDisplay,
                benchmarkId,
                benchmarkDisplay,
                batchSize,
                totalItems,
                phase,
                itemIndex,
                itemTotal,
                repeatIndex,
                repeatTotal,
                itemId,
                prompt,
                expected,
                output.toString(),
                jobStartedMs,
                itemStartedMs);
    }

    private static String nz(String value) {
        return value == null ? "" : value;
    }

    /** Immutable view passed to the UI thread. */
    static final class Snapshot {
        final boolean running;
        final String backendId;
        final String modelId;
        final String modelDisplay;
        final String benchmarkId;
        final String benchmarkDisplay;
        final int batchSize;
        final int totalItems;
        final String phase;
        final int itemIndex;
        final int itemTotal;
        final int repeatIndex;
        final int repeatTotal;
        final String itemId;
        final String prompt;
        final String expected;
        final String output;
        final long jobStartedMs;
        final long itemStartedMs;

        Snapshot(
                boolean running,
                String backendId,
                String modelId,
                String modelDisplay,
                String benchmarkId,
                String benchmarkDisplay,
                int batchSize,
                int totalItems,
                String phase,
                int itemIndex,
                int itemTotal,
                int repeatIndex,
                int repeatTotal,
                String itemId,
                String prompt,
                String expected,
                String output,
                long jobStartedMs,
                long itemStartedMs) {
            this.running = running;
            this.backendId = backendId;
            this.modelId = modelId;
            this.modelDisplay = modelDisplay;
            this.benchmarkId = benchmarkId;
            this.benchmarkDisplay = benchmarkDisplay;
            this.batchSize = batchSize;
            this.totalItems = totalItems;
            this.phase = phase;
            this.itemIndex = itemIndex;
            this.itemTotal = itemTotal;
            this.repeatIndex = repeatIndex;
            this.repeatTotal = repeatTotal;
            this.itemId = itemId;
            this.prompt = prompt;
            this.expected = expected;
            this.output = output;
            this.jobStartedMs = jobStartedMs;
            this.itemStartedMs = itemStartedMs;
        }
    }
}
