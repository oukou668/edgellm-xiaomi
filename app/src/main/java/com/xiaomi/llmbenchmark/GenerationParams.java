package com.xiaomi.llmbenchmark;

import org.json.JSONObject;

final class GenerationParams {
    final double temperature;
    final double topP;
    final int topK;
    final long seed;
    final int maxTokens;
    final int contextWindowSize;
    final boolean thinkingEnabled;

    GenerationParams(
            double temperature,
            double topP,
            int topK,
            long seed,
            int maxTokens,
            int contextWindowSize,
            boolean thinkingEnabled) {
        this.temperature = temperature;
        this.topP = topP;
        this.topK = topK;
        this.seed = seed;
        this.maxTokens = maxTokens;
        this.contextWindowSize = contextWindowSize;
        this.thinkingEnabled = thinkingEnabled;
    }

    static GenerationParams fromJson(JSONObject json) {
        if (json == null) {
            return new GenerationParams(0.0, 1.0, 0, 0L, 128, 0, false);
        }
        return new GenerationParams(
                json.optDouble("temperature", 0.0),
                json.optDouble("top_p", 1.0),
                json.optInt("top_k", 0),
                json.optLong("seed", 0L),
                json.optInt("max_tokens", json.optInt("max_new_tokens", 128)),
                json.optInt("context_window_size", json.optInt("context_window", 0)),
                json.optBoolean("thinking_enabled", json.optBoolean("thinking", false)));
    }

    GenerationParams withMaxTokens(int value) {
        return new GenerationParams(
                temperature, topP, topK, seed, Math.max(1, value), contextWindowSize, thinkingEnabled);
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("temperature", temperature);
        json.put("top_p", topP);
        json.put("top_k", topK);
        json.put("seed", seed);
        json.put("max_tokens", maxTokens);
        json.put("context_window_size", contextWindowSize);
        json.put("thinking_enabled", thinkingEnabled);
        return json;
    }
}
