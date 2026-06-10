package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;

final class MlcInferenceEngine implements InferenceEngine {
    private static final String TAG = "XiaomiLlmBenchmark";
    // Per-sample inference timeout: 120 minutes. On timeout we return the partial generation with
    // finish_reason="timeout" (so the decode-speed profile is preserved), then reset the engine.
    private static final long PER_SAMPLE_TIMEOUT_MS = 120L * 60L * 1000L;

    private final Context context;
    private Object engine;
    private Method reload;
    private Method chatCompletion;
    private Method reset;
    private Method unload;
    private boolean servingMode;
    private RuntimeDiagnostics diagnostics = RuntimeDiagnostics.unknown();
    private final LinkedBlockingQueue<String> streamEvents = new LinkedBlockingQueue<>();

    MlcInferenceEngine(Context context) {
        this.context = context.getApplicationContext();
    }

    /**
     * Switch the engine into MLC's continuous-batching "server" mode for batched runs. Must be
     * called before {@link #load}. Default (false) keeps today's single-request "interactive" mode.
     */
    void setServingMode(boolean enabled) {
        this.servingMode = enabled;
    }

    @Override
    public void load(ModelConfig model, File modelDir) throws Exception {
        loadKnownNativeLibraries();
        Class<?> engineClass = Class.forName("ai.mlc.mlcllm.JSONFFIEngine");
        Class<?> callbackClass = Class.forName("ai.mlc.mlcllm.JSONFFIEngine$KotlinFunction");

        engine = engineClass.getConstructor().newInstance();
        Method initBackgroundEngine = engineClass.getMethod("initBackgroundEngine", callbackClass);
        reload = engineClass.getMethod("reload", String.class);
        chatCompletion = engineClass.getMethod("chatCompletion", String.class, String.class);
        reset = engineClass.getMethod("reset");
        unload = engineClass.getMethod("unload");
        Method runBackgroundLoop = engineClass.getMethod("runBackgroundLoop");
        Method runBackgroundStreamBackLoop = engineClass.getMethod("runBackgroundStreamBackLoop");

        Object callback =
                Proxy.newProxyInstance(
                        callbackClass.getClassLoader(),
                        new Class<?>[] {callbackClass},
                        (proxy, method, args) -> {
                            if (args != null && args.length > 0 && args[0] != null) {
                                streamEvents.offer(String.valueOf(args[0]));
                            }
                            return null;
                        });

        initBackgroundEngine.invoke(engine, callback);
        startDaemon("mlc-background-loop", () -> invokeNoArg(runBackgroundLoop));
        startDaemon("mlc-stream-loop", () -> invokeNoArg(runBackgroundStreamBackLoop));

        String mode = servingMode ? "server" : "interactive";
        JSONObject config = new JSONObject();
        config.put("model", modelDir.getAbsolutePath());
        if (model.modelLib != null && !model.modelLib.isEmpty()) {
            config.put("model_lib", "system://" + model.modelLib);
        }
        config.put("mode", mode);
        Log.i(TAG, "Calling MLC reload with config: " + config);
        reload.invoke(engine, config.toString());
        Log.i(TAG, "MLC reload returned.");
        Map<String, String> details = new LinkedHashMap<>();
        details.put("model_path", modelDir.getAbsolutePath());
        details.put("model_id", model.modelId);
        details.put("hf_repo", model.hfRepo);
        details.put("hf_revision", model.hfRevision);
        details.put("mode", mode);
        String runtimeLibrary = System.mapLibraryName("tvm4j_runtime_packed");
        details.put("runtime_library", runtimeLibrary);
        diagnostics =
                new RuntimeDiagnostics(
                        model.backendId,
                        "JSONFFIEngine",
                        model.modelLib,
                        NativeLibraryInfo.path(context, runtimeLibrary),
                        NativeLibraryInfo.sha256(context, runtimeLibrary),
                        BuildConfig.MLC_LLM_GIT_COMMIT,
                        details);
    }

    @Override
    public GenerationResult generate(BenchmarkItem item, GenerationParams params) throws Exception {
        if (engine == null) {
            throw new IllegalStateException("MLC engine is not loaded.");
        }

        streamEvents.clear();
        reset.invoke(engine);
        String requestId = UUID.randomUUID().toString();
        JSONObject request = buildRequest(item, params, requestId);

        int promptEstimate = estimateTokens(item.displayPrompt());
        long startNs = System.nanoTime();
        long firstTokenNs = 0L;
        long lastTokenNs = startNs;
        int cumulativeGenerated = 0;
        StringBuilder text = new StringBuilder();
        BucketAccumulator buckets = new BucketAccumulator();
        chatCompletion.invoke(engine, request.toString(), requestId);

        long deadlineNs = startNs + TimeUnit.MILLISECONDS.toNanos(PER_SAMPLE_TIMEOUT_MS);
        boolean finished = false;
        while (System.nanoTime() < deadlineNs) {
            String event = streamEvents.poll(250, TimeUnit.MILLISECONDS);
            if (event == null) {
                continue;
            }
            for (ParsedDelta delta : parseDeltas(event)) {
                if (!delta.id.isEmpty() && !delta.id.equals(requestId)) {
                    continue;
                }
                if (!delta.content.isEmpty()) {
                    long nowNs = System.nanoTime();
                    if (firstTokenNs == 0L) {
                        firstTokenNs = nowNs;
                    }
                    int tokens = estimateTokens(delta.content);
                    buckets.add(promptEstimate + cumulativeGenerated, tokens,
                            (nowNs - lastTokenNs) / 1_000_000L);
                    lastTokenNs = nowNs;
                    cumulativeGenerated += tokens;
                    text.append(delta.content);
                }
                if (delta.finished) {
                    finished = true;
                    break;
                }
            }
            if (finished) {
                break;
            }
        }

        long endNs = System.nanoTime();
        String finishReason = finished ? "stop" : "timeout";
        if (!finished) {
            try {
                reset.invoke(engine);
            } catch (Exception ignored) {
            }
        }
        String output = text.toString();
        long decodeMs = TimeUnit.NANOSECONDS.toMillis(endNs - startNs);
        return new GenerationResult(
                output,
                firstTokenNs == 0L ? -1L : TimeUnit.NANOSECONDS.toMillis(firstTokenNs - startNs),
                -1L,
                decodeMs,
                decodeMs,
                promptEstimate,
                estimateTokens(output),
                finishReason,
                diagnostics,
                buckets.build());
    }

    @Override
    public BatchGenerationResult generateBatch(List<BenchmarkItem> items, List<GenerationParams> params)
            throws Exception {
        if (engine == null) {
            throw new IllegalStateException("MLC engine is not loaded.");
        }
        int n = items.size();
        streamEvents.clear();
        reset.invoke(engine);

        String[] ids = new String[n];
        StringBuilder[] texts = new StringBuilder[n];
        long[] firstTokenNs = new long[n];
        long[] endNs = new long[n];
        long[] lastTokenNs = new long[n];
        boolean[] done = new boolean[n];
        int[] promptEstimate = new int[n];
        int[] cumulativeGenerated = new int[n];
        String[] finishReason = new String[n];
        BucketAccumulator[] buckets = new BucketAccumulator[n];
        Map<String, Integer> idToIndex = new HashMap<>();

        long startNs = System.nanoTime();
        for (int i = 0; i < n; i++) {
            ids[i] = UUID.randomUUID().toString();
            idToIndex.put(ids[i], i);
            texts[i] = new StringBuilder();
            lastTokenNs[i] = startNs;
            promptEstimate[i] = estimateTokens(items.get(i).displayPrompt());
            finishReason[i] = "length";
            buckets[i] = new BucketAccumulator();
            JSONObject request = buildRequest(items.get(i), params.get(i), ids[i]);
            chatCompletion.invoke(engine, request.toString(), ids[i]);
        }

        long deadlineNs = startNs + TimeUnit.MILLISECONDS.toNanos(PER_SAMPLE_TIMEOUT_MS);
        int remaining = n;
        while (remaining > 0 && System.nanoTime() < deadlineNs) {
            String event = streamEvents.poll(250, TimeUnit.MILLISECONDS);
            if (event == null) {
                continue;
            }
            for (ParsedDelta delta : parseDeltas(event)) {
                Integer index = idToIndex.get(delta.id);
                if (index == null) {
                    continue;
                }
                int i = index;
                if (done[i]) {
                    continue;
                }
                if (!delta.content.isEmpty()) {
                    long nowNs = System.nanoTime();
                    if (firstTokenNs[i] == 0L) {
                        firstTokenNs[i] = nowNs;
                    }
                    int tokens = estimateTokens(delta.content);
                    buckets[i].add(promptEstimate[i] + cumulativeGenerated[i], tokens,
                            (nowNs - lastTokenNs[i]) / 1_000_000L);
                    lastTokenNs[i] = nowNs;
                    cumulativeGenerated[i] += tokens;
                    texts[i].append(delta.content);
                }
                if (delta.finished) {
                    done[i] = true;
                    endNs[i] = System.nanoTime();
                    finishReason[i] = "stop";
                    remaining--;
                }
            }
        }

        long wallEndNs = System.nanoTime();
        for (int i = 0; i < n; i++) {
            if (!done[i]) {
                finishReason[i] = "timeout";
                endNs[i] = wallEndNs;
            }
        }
        if (remaining > 0) {
            try {
                reset.invoke(engine);
            } catch (Exception ignored) {
            }
        }

        long maxEndNs = startNs;
        for (int i = 0; i < n; i++) {
            maxEndNs = Math.max(maxEndNs, endNs[i]);
        }
        long decodeWallMs = TimeUnit.NANOSECONDS.toMillis(maxEndNs - startNs);
        int totalGenerated = 0;
        List<GenerationResult> results = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            String output = texts[i].toString();
            int generated = estimateTokens(output);
            totalGenerated += generated;
            results.add(
                    new GenerationResult(
                            output,
                            firstTokenNs[i] == 0L ? -1L : TimeUnit.NANOSECONDS.toMillis(firstTokenNs[i] - startNs),
                            -1L,
                            decodeWallMs,
                            decodeWallMs,
                            promptEstimate[i],
                            generated,
                            finishReason[i],
                            diagnostics,
                            buckets[i].build()));
        }
        double aggregateTps = decodeWallMs > 0L ? totalGenerated * 1000.0 / decodeWallMs : 0.0;
        return new BatchGenerationResult(results, decodeWallMs, 0L, totalGenerated, n, aggregateTps, diagnostics);
    }

    @Override
    public RuntimeDiagnostics diagnostics() {
        return diagnostics;
    }

    @Override
    public void unload() {
        if (engine != null && unload != null) {
            try {
                unload.invoke(engine);
            } catch (Exception ignored) {
            }
        }
    }

    // Send the benchmark item's messages verbatim. Thinking on/off is governed by the model's
    // official conversation template (mlc-chat-config.json) — we do NOT inject system prompts or
    // /no_think tokens.
    private JSONObject buildRequest(BenchmarkItem item, GenerationParams params, String requestId)
            throws Exception {
        JSONObject request = new JSONObject();
        request.put("model", "local");
        request.put("stream", true);
        request.put("temperature", params.temperature);
        request.put("top_p", params.topP);
        request.put("max_tokens", params.maxTokens);
        JSONArray messages = new JSONArray();
        for (BenchmarkMessage message : item.messages) {
            messages.put(new JSONObject().put("role", message.role).put("content", message.content));
        }
        request.put("messages", messages);
        return request;
    }

    private static List<ParsedDelta> parseDeltas(String event) {
        List<ParsedDelta> deltas = new ArrayList<>();
        try {
            String trimmed = event.trim();
            if (trimmed.startsWith("[")) {
                JSONArray array = new JSONArray(trimmed);
                for (int i = 0; i < array.length(); i++) {
                    addDelta(deltas, array.optJSONObject(i));
                }
            } else {
                addDelta(deltas, new JSONObject(trimmed));
            }
        } catch (Exception ignored) {
        }
        return deltas;
    }

    private static void addDelta(List<ParsedDelta> deltas, JSONObject root) {
        if (root == null) {
            return;
        }
        String id = root.optString("id", "");
        if (!root.isNull("usage")) {
            deltas.add(new ParsedDelta(id, "", true));
            return;
        }
        JSONArray choices = root.optJSONArray("choices");
        if (choices == null || choices.length() == 0) {
            deltas.add(new ParsedDelta(id, "", root.optBoolean("finished", false)));
            return;
        }
        JSONObject choice = choices.optJSONObject(0);
        String finishReason = choice.isNull("finish_reason") ? "" : choice.optString("finish_reason", "");
        JSONObject delta = choice.optJSONObject("delta");
        JSONObject message = choice.optJSONObject("message");
        String content = "";
        if (delta != null) {
            content = delta.optString("content", "");
        } else if (message != null) {
            content = message.optString("content", "");
        }
        deltas.add(new ParsedDelta(id, content, finishReason != null && !finishReason.isEmpty()));
    }

    private static int estimateTokens(String text) {
        if (text == null || text.trim().isEmpty()) {
            return 0;
        }
        int cjk = 0;
        StringBuilder ascii = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (Character.UnicodeScript.of(ch) == Character.UnicodeScript.HAN) {
                cjk++;
                ascii.append(' ');
            } else {
                ascii.append(ch);
            }
        }
        String[] parts = ascii.toString().trim().split("\\s+");
        int asciiWords = parts.length == 1 && parts[0].isEmpty() ? 0 : parts.length;
        return Math.max(1, cjk + asciiWords);
    }

    private static void startDaemon(String name, Runnable runnable) {
        Thread thread = new Thread(runnable, name);
        thread.setDaemon(true);
        thread.start();
    }

    private static void loadKnownNativeLibraries() {
        String[] names = {
            "tvm4j_runtime_packed",
            "tvm_runtime",
            "mlc_llm",
            "tokenizers_cpp",
            "sentencepiece"
        };
        for (String name : names) {
            try {
                System.loadLibrary(name);
            } catch (UnsatisfiedLinkError ignored) {
            }
        }
    }

    private void invokeNoArg(Method method) {
        try {
            method.invoke(engine);
        } catch (Exception error) {
            Log.e(TAG, "MLC background method failed: " + method.getName(), error);
        }
    }

    private static final class ParsedDelta {
        final String id;
        final String content;
        final boolean finished;

        ParsedDelta(String id, String content, boolean finished) {
            this.id = id == null ? "" : id;
            this.content = content == null ? "" : content;
            this.finished = finished;
        }
    }

    // Accumulates decode time and token counts per 4096-position KV bucket. MLC has no exact token
    // positions, so the bucket index uses an estimated cumulative-token position (approximate).
    private static final class BucketAccumulator {
        private final List<Integer> tokens = new ArrayList<>();
        private final List<Long> ms = new ArrayList<>();

        void add(int position, int tokenCount, long deltaMs) {
            int idx = Math.max(0, position) / DecodeSpeedBucket.WIDTH;
            while (tokens.size() <= idx) {
                tokens.add(0);
                ms.add(0L);
            }
            tokens.set(idx, tokens.get(idx) + tokenCount);
            ms.set(idx, ms.get(idx) + Math.max(0L, deltaMs));
        }

        List<DecodeSpeedBucket> build() {
            List<DecodeSpeedBucket> out = new ArrayList<>();
            for (int b = 0; b < tokens.size(); b++) {
                int t = tokens.get(b);
                long m = ms.get(b);
                if (t == 0 && m == 0L) {
                    continue;
                }
                int start = b * DecodeSpeedBucket.WIDTH;
                double tps = m > 0L ? t * 1000.0 / m : 0.0;
                out.add(new DecodeSpeedBucket(start, start + DecodeSpeedBucket.WIDTH, t, m, tps));
            }
            return out;
        }
    }
}
