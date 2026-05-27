package com.xiaomi.llmbenchmark;

import org.json.JSONObject;

final class GenerationParams {
    final double temperature;
    final double topP;
    final int maxTokens;

    GenerationParams(double temperature, double topP, int maxTokens) {
        this.temperature = temperature;
        this.topP = topP;
        this.maxTokens = maxTokens;
    }

    static GenerationParams fromJson(JSONObject json) {
        if (json == null) {
            return new GenerationParams(0.0, 1.0, 128);
        }
        return new GenerationParams(
                json.optDouble("temperature", 0.0),
                json.optDouble("top_p", 1.0),
                json.optInt("max_tokens", 128));
    }
}

