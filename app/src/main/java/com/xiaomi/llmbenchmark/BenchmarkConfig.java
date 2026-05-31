package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class BenchmarkConfig {
    final String benchmarkId;
    final String displayName;
    final String version;
    final String description;
    final int defaultMaxNewTokens;
    final long hardwareSampleIntervalMs;
    final List<BenchmarkItem> items;

    BenchmarkConfig(
            String benchmarkId,
            String displayName,
            String version,
            String description,
            int defaultMaxNewTokens,
            long hardwareSampleIntervalMs,
            List<BenchmarkItem> items) {
        this.benchmarkId = benchmarkId;
        this.displayName = displayName;
        this.version = version;
        this.description = description;
        this.defaultMaxNewTokens = defaultMaxNewTokens;
        this.hardwareSampleIntervalMs = hardwareSampleIntervalMs;
        this.items = Collections.unmodifiableList(items);
    }

    static BenchmarkConfig fromJson(JSONObject json) {
        int defaultMaxTokens = json.optInt("default_max_new_tokens", 96);
        long hardwareSampleIntervalMs = json.optLong("hardware_sample_interval_ms", 1000L);
        JSONArray itemJson = json.optJSONArray("items");
        List<BenchmarkItem> items = new ArrayList<>();
        if (itemJson != null) {
            for (int i = 0; i < itemJson.length(); i++) {
                items.add(BenchmarkItem.fromJson(itemJson.optJSONObject(i), defaultMaxTokens));
            }
        }
        return new BenchmarkConfig(
                json.optString("benchmark_id"),
                json.optString("display_name", json.optString("benchmark_id")),
                json.optString("version"),
                json.optString("description"),
                defaultMaxTokens,
                hardwareSampleIntervalMs,
                items);
    }

    @Override
    public String toString() {
        return displayName + " (" + items.size() + ")";
    }
}
