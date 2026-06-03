package com.xiaomi.llmbenchmark;

import java.io.File;

interface InferenceEngine {
    void load(ModelConfig model, File modelDir) throws Exception;

    GenerationResult generate(BenchmarkItem item, GenerationParams params, ProgressSink progress) throws Exception;

    void unload();
}
