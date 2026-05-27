package com.xiaomi.llmbenchmark;

import java.io.File;

interface InferenceEngine {
    void load(ModelConfig model, File modelDir) throws Exception;

    GenerationResult generate(String prompt, GenerationParams params, int maxNewTokens) throws Exception;

    void unload();
}

