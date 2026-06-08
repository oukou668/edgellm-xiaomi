package com.xiaomi.llmbenchmark;

import org.json.JSONObject;

final class BenchmarkRunOptions {
    static final String SMOKE_DUMMY = "dummy_backend_regression";
    static final String SMOKE_REAL = "real_model_smoke";

    final String backendId;
    final String smokeType;
    final int repeatCount;
    final int warmupCount;

    BenchmarkRunOptions(String backendId, String smokeType, int repeatCount, int warmupCount) {
        this.backendId = backendId == null || backendId.isEmpty() ? ModelConfig.BACKEND_MLC : backendId;
        this.smokeType = smokeType == null || smokeType.isEmpty() ? SMOKE_DUMMY : smokeType;
        this.repeatCount = Math.max(1, repeatCount);
        this.warmupCount = Math.max(0, warmupCount);
    }

    static BenchmarkRunOptions defaults(String backendId) {
        return new BenchmarkRunOptions(backendId, SMOKE_DUMMY, 1, 0);
    }

    boolean isRealSmoke() {
        return SMOKE_REAL.equals(smokeType);
    }

    boolean isDummy() {
        return SMOKE_DUMMY.equals(smokeType);
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("backend_id", backendId);
        json.put("smoke_type", smokeType);
        json.put("repeat_count", repeatCount);
        json.put("warmup_count", warmupCount);
        return json;
    }
}
