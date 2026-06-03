package com.xiaomi.llmbenchmark;

interface ProgressSink {
    void onProgress(String message);

    default void onItemStarted(int index, int total, BenchmarkItem item) {}

    default void onGenerationToken(String itemId, String token, String fullText) {}

    default void onHardwareSample(HardwareSample sample) {}
}
