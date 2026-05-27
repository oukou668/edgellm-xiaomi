package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONObject;

final class BenchmarkRegistry {
    private final List<BenchmarkConfig> benchmarks;

    private BenchmarkRegistry(List<BenchmarkConfig> benchmarks) {
        this.benchmarks = Collections.unmodifiableList(benchmarks);
    }

    static BenchmarkRegistry load(Context context) throws Exception {
        String[] files = context.getAssets().list("benchmarks");
        List<BenchmarkConfig> configs = new ArrayList<>();
        if (files != null) {
            for (String file : files) {
                if (file.endsWith(".json")) {
                    String text = AssetText.read(context, "benchmarks/" + file);
                    configs.add(BenchmarkConfig.fromJson(new JSONObject(text)));
                }
            }
        }
        return new BenchmarkRegistry(configs);
    }

    List<BenchmarkConfig> all() {
        return benchmarks;
    }
}

