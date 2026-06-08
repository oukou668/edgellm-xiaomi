package com.xiaomi.llmbenchmark;

import android.content.Context;

final class EngineFactory {
    private EngineFactory() {}

    static InferenceEngine create(Context context, String backendId) {
        if (ModelConfig.BACKEND_LLAMA_CPP.equals(backendId)) {
            return new LlamaCppInferenceEngine(context);
        }
        return new MlcInferenceEngine(context);
    }
}
