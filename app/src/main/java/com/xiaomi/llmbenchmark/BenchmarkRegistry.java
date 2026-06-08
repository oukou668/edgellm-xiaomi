package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
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
                } else if (file.endsWith(".jsonl")) {
                    String text = AssetText.read(context, "benchmarks/" + file);
                    configs.add(fromJsonl(file, text));
                }
            }
        }
        return new BenchmarkRegistry(configs);
    }

    List<BenchmarkConfig> all() {
        return benchmarks;
    }

    static BenchmarkConfig loadBundle(Context context, String bundleId) throws Exception {
        if (bundleId == null || bundleId.isEmpty()) {
            throw new IllegalArgumentException("bundle_id is empty");
        }
        if (bundleId.contains("/") || bundleId.contains("..")) {
            throw new IllegalArgumentException("Invalid bundle_id: " + bundleId);
        }
        File dir = new File(context.getFilesDir(), "run_bundles/" + bundleId);
        File jsonl = new File(dir, "benchmark.jsonl");
        File json = new File(dir, "benchmark.json");
        if (jsonl.exists()) {
            String text = new String(Files.readAllBytes(jsonl.toPath()), StandardCharsets.UTF_8);
            return fromJsonl(jsonl.getName(), text, bundleId);
        }
        if (json.exists()) {
            String text = new String(Files.readAllBytes(json.toPath()), StandardCharsets.UTF_8);
            return BenchmarkConfig.fromJson(new JSONObject(text));
        }
        throw new IllegalStateException("Bundle benchmark not found: " + dir.getAbsolutePath());
    }

    private static BenchmarkConfig fromJsonl(String file, String text) throws Exception {
        String id = file.substring(0, file.length() - ".jsonl".length());
        return fromJsonl(file, text, id);
    }

    private static BenchmarkConfig fromJsonl(String file, String text, String benchmarkId) throws Exception {
        JSONArray items = new JSONArray();
        String[] lines = text.split("\\r?\\n");
        for (String line : lines) {
            String trimmed = line.trim();
            if (!trimmed.isEmpty()) {
                items.put(new JSONObject(trimmed));
            }
        }
        JSONObject json = new JSONObject();
        json.put("benchmark_id", benchmarkId);
        json.put("display_name", benchmarkId);
        json.put("version", "jsonl");
        json.put("description", "JSONL benchmark loaded from assets.");
        json.put("default_max_new_tokens", 64);
        json.put("items", items);
        return BenchmarkConfig.fromJson(json);
    }
}
