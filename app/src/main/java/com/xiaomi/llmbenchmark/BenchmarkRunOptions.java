package com.xiaomi.llmbenchmark;

import org.json.JSONObject;

final class BenchmarkRunOptions {
    static final String SMOKE_DUMMY = "dummy_backend_regression";
    static final String SMOKE_REAL = "real_model_smoke";
    static final String LLAMA_ACCELERATOR_AUTO = "auto";
    static final String LLAMA_ACCELERATOR_CPU = "cpu";
    static final String LLAMA_ACCELERATOR_VULKAN_REQUIRED = "vulkan_required";

    final String backendId;
    final String smokeType;
    final int repeatCount;
    final int warmupCount;
    final int batchSize;
    final boolean stressMode;
    final boolean unloadAfterRun;
    final String llamaAccelerator;
    final int llamaGpuLayers;

    BenchmarkRunOptions(String backendId, String smokeType, int repeatCount, int warmupCount) {
        this(backendId, smokeType, repeatCount, warmupCount, 1, false, false);
    }

    BenchmarkRunOptions(
            String backendId,
            String smokeType,
            int repeatCount,
            int warmupCount,
            int batchSize,
            boolean stressMode) {
        this(backendId, smokeType, repeatCount, warmupCount, batchSize, stressMode, false);
    }

    BenchmarkRunOptions(
            String backendId,
            String smokeType,
            int repeatCount,
            int warmupCount,
            int batchSize,
            boolean stressMode,
            boolean unloadAfterRun) {
        this(
                backendId,
                smokeType,
                repeatCount,
                warmupCount,
                batchSize,
                stressMode,
                unloadAfterRun,
                LLAMA_ACCELERATOR_AUTO,
                -1);
    }

    BenchmarkRunOptions(
            String backendId,
            String smokeType,
            int repeatCount,
            int warmupCount,
            int batchSize,
            boolean stressMode,
            boolean unloadAfterRun,
            String llamaAccelerator,
            int llamaGpuLayers) {
        this.backendId = backendId == null || backendId.isEmpty() ? ModelConfig.BACKEND_MLC : backendId;
        this.smokeType = smokeType == null || smokeType.isEmpty() ? SMOKE_DUMMY : smokeType;
        this.repeatCount = Math.max(1, repeatCount);
        this.warmupCount = Math.max(0, warmupCount);
        this.batchSize = Math.max(1, batchSize);
        this.stressMode = stressMode;
        this.unloadAfterRun = unloadAfterRun;
        this.llamaAccelerator = normalizeLlamaAccelerator(llamaAccelerator);
        this.llamaGpuLayers = llamaGpuLayers;
    }

    static BenchmarkRunOptions defaults(String backendId) {
        return new BenchmarkRunOptions(backendId, SMOKE_DUMMY, 1, 0, 1, false, false);
    }

    boolean isRealSmoke() {
        return SMOKE_REAL.equals(smokeType);
    }

    boolean isDummy() {
        return SMOKE_DUMMY.equals(smokeType);
    }

    boolean isBatched() {
        return batchSize > 1;
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("backend_id", backendId);
        json.put("smoke_type", smokeType);
        json.put("repeat_count", repeatCount);
        json.put("warmup_count", warmupCount);
        json.put("batch_size", batchSize);
        json.put("stress_mode", stressMode);
        json.put("unload_after_run", unloadAfterRun);
        json.put("llama_accelerator", llamaAccelerator);
        json.put("llama_gpu_layers", llamaGpuLayers);
        return json;
    }

    private static String normalizeLlamaAccelerator(String value) {
        if (value == null || value.trim().isEmpty()) {
            return LLAMA_ACCELERATOR_AUTO;
        }
        String clean = value.trim().toLowerCase(java.util.Locale.US);
        if (LLAMA_ACCELERATOR_CPU.equals(clean)
                || LLAMA_ACCELERATOR_VULKAN_REQUIRED.equals(clean)
                || LLAMA_ACCELERATOR_AUTO.equals(clean)) {
            return clean;
        }
        return LLAMA_ACCELERATOR_AUTO;
    }
}
