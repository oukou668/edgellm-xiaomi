package com.xiaomi.llmbenchmark;

import java.io.File;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.UUID;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;

final class MlcInferenceEngine implements InferenceEngine {
    private static final String TAG = "XiaomiLlmBenchmark";
    private Object engine;
    private Method reload;
    private Method chatCompletion;
    private Method reset;
    private Method unload;
    private final LinkedBlockingQueue<String> streamEvents = new LinkedBlockingQueue<>();

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

        JSONObject config = new JSONObject();
        config.put("model", modelDir.getAbsolutePath());
        config.put("model_lib", "system://" + model.modelLib);
        config.put("mode", "interactive");
        Log.i(TAG, "Calling MLC reload with config: " + config);
        reload.invoke(engine, config.toString());
        Log.i(TAG, "MLC reload returned.");
    }

    @Override
    public GenerationResult generate(BenchmarkItem item, GenerationParams params) throws Exception {
        if (engine == null) {
            throw new IllegalStateException("MLC engine is not loaded.");
        }

        streamEvents.clear();
        reset.invoke(engine);
        String requestId = UUID.randomUUID().toString();
        JSONObject request = new JSONObject();
        request.put("model", "local");
        request.put("stream", true);
        request.put("temperature", params.temperature);
        request.put("top_p", params.topP);
        request.put("max_tokens", item.maxNewTokens);
        JSONArray messages = new JSONArray();
        messages.put(
                new JSONObject()
                        .put("role", "system")
                        .put(
                                "content",
                                "You are running inside a benchmark. Do not reveal chain-of-thought. "
                                        + "Do not include <think> sections. Return only the final answer."));
        for (BenchmarkMessage message : item.messages) {
            String content = message.content;
            if ("user".equals(message.role)) {
                content = content + "\n/no_think";
            }
            messages.put(new JSONObject().put("role", message.role).put("content", content));
        }
        request.put("messages", messages);

        long startNs = System.nanoTime();
        long firstTokenNs = 0L;
        StringBuilder text = new StringBuilder();
        chatCompletion.invoke(engine, request.toString(), requestId);

        long timeoutSeconds = Math.max(180L, item.maxNewTokens * 2L);
        long deadlineNs = startNs + TimeUnit.SECONDS.toNanos(timeoutSeconds);
        boolean finished = false;
        while (System.nanoTime() < deadlineNs) {
            String event = streamEvents.poll(250, TimeUnit.MILLISECONDS);
            if (event == null) {
                continue;
            }
            ParsedStreamEvent parsed = parseStreamEvent(event, requestId);
            if (!parsed.content.isEmpty()) {
                if (firstTokenNs == 0L) {
                    firstTokenNs = System.nanoTime();
                }
                text.append(parsed.content);
            }
            if (parsed.finished) {
                finished = true;
                break;
            }
        }

        long endNs = System.nanoTime();
        if (!finished) {
            try {
                reset.invoke(engine);
            } catch (Exception ignored) {
            }
            throw new IllegalStateException("MLC generation timed out after " + timeoutSeconds + " seconds.");
        }
        return new GenerationResult(
                text.toString(),
                firstTokenNs == 0L ? -1L : TimeUnit.NANOSECONDS.toMillis(firstTokenNs - startNs),
                TimeUnit.NANOSECONDS.toMillis(endNs - startNs),
                estimateTokens(text.toString()));
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

    private static ParsedStreamEvent parseStreamEvent(String event, String requestId) {
        try {
            if (event.trim().startsWith("[")) {
                JSONArray events = new JSONArray(event);
                StringBuilder content = new StringBuilder();
                boolean finished = false;
                for (int i = 0; i < events.length(); i++) {
                    ParsedStreamEvent parsed = parseStreamObject(events.optJSONObject(i), requestId);
                    content.append(parsed.content);
                    finished = finished || parsed.finished;
                }
                return new ParsedStreamEvent(content.toString(), finished);
            }
            return parseStreamObject(new JSONObject(event), requestId);
        } catch (Exception ignored) {
            return new ParsedStreamEvent(event, false);
        }
    }

    private static ParsedStreamEvent parseStreamObject(JSONObject root, String requestId) {
        if (root == null) {
            return new ParsedStreamEvent("", false);
        }
        try {
            String responseId = root.optString("id", "");
            if (!responseId.isEmpty() && !responseId.equals(requestId)) {
                return new ParsedStreamEvent("", false);
            }
            if (!root.isNull("usage")) {
                return new ParsedStreamEvent("", true);
            }
            JSONArray choices = root.optJSONArray("choices");
            if (choices == null || choices.length() == 0) {
                return new ParsedStreamEvent("", root.optBoolean("finished", false));
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
            return new ParsedStreamEvent(content, finishReason != null && !finishReason.isEmpty());
        } catch (Exception ignored) {
            return new ParsedStreamEvent("", false);
        }
    }

    private static int estimateTokens(String text) {
        if (text == null || text.trim().isEmpty()) {
            return 0;
        }
        int cjk = 0;
        int asciiWords = 0;
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
        if (parts.length == 1 && parts[0].isEmpty()) {
            asciiWords = 0;
        } else {
            asciiWords = parts.length;
        }
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

    private static final class ParsedStreamEvent {
        final String content;
        final boolean finished;

        ParsedStreamEvent(String content, boolean finished) {
            this.content = content == null ? "" : content;
            this.finished = finished;
        }
    }
}
