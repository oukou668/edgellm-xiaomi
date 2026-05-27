package com.xiaomi.llmbenchmark;

final class EngineFactory {
    private EngineFactory() {}

    static InferenceEngine create() {
        return new MlcInferenceEngine();
    }
}

