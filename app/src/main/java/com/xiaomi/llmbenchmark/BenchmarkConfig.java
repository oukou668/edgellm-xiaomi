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
    final List<BenchmarkItem> items;

    BenchmarkConfig(
            String benchmarkId,
            String displayName,
            String version,
            String description,
            int defaultMaxNewTokens,
            List<BenchmarkItem> items) {
        this.benchmarkId = benchmarkId;
        this.displayName = displayName;
        this.version = version;
        this.description = description;
        this.defaultMaxNewTokens = defaultMaxNewTokens;
        this.items = Collections.unmodifiableList(items);
    }

    static BenchmarkConfig fromJson(JSONObject json) {
        int defaultMaxTokens = json.optInt("default_max_new_tokens", 96);
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
                items);
    }

    @Override
    public String toString() {
        return displayName + " (" + items.size() + ")";
    }
}

