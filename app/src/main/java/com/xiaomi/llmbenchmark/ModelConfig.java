package com.xiaomi.llmbenchmark;

import org.json.JSONObject;

final class ModelConfig {
    final String modelId;
    final String displayName;
    final String mlcModelUrl;
    final String modelLib;
    final String quantization;
    final int contextWindow;
    final long estimatedVramBytes;
    final GenerationParams defaultParams;

    ModelConfig(
            String modelId,
            String displayName,
            String mlcModelUrl,
            String modelLib,
            String quantization,
            int contextWindow,
            long estimatedVramBytes,
            GenerationParams defaultParams) {
        this.modelId = modelId;
        this.displayName = displayName;
        this.mlcModelUrl = mlcModelUrl;
        this.modelLib = modelLib;
        this.quantization = quantization;
        this.contextWindow = contextWindow;
        this.estimatedVramBytes = estimatedVramBytes;
        this.defaultParams = defaultParams;
    }

    static ModelConfig fromJson(JSONObject json) {
        return new ModelConfig(
                json.optString("model_id"),
                json.optString("display_name", json.optString("model_id")),
                json.optString("mlc_model_url"),
                json.optString("model_lib"),
                json.optString("quantization"),
                json.optInt("context_window", 2048),
                json.optLong("estimated_vram_bytes", 0L),
                GenerationParams.fromJson(json.optJSONObject("default_params")));
    }

    @Override
    public String toString() {
        return displayName;
    }
}

