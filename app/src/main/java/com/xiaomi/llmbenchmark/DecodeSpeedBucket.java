package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Average decode speed within a fixed-width window of KV-cache positions, e.g. [0,4096),
 * [4096,8192), ... The stress test reports one bucket per 4096-token slice so we can see how
 * decode tok/s degrades as the KV cache grows toward 64K.
 */
final class DecodeSpeedBucket {
    static final int WIDTH = 4096;

    final int startToken;
    final int endToken;
    final int tokens;
    final long totalMs;
    final double tokensPerSecond;

    DecodeSpeedBucket(int startToken, int endToken, int tokens, long totalMs, double tokensPerSecond) {
        this.startToken = startToken;
        this.endToken = endToken;
        this.tokens = tokens;
        this.totalMs = totalMs;
        this.tokensPerSecond = tokensPerSecond;
    }

    static DecodeSpeedBucket fromJson(JSONObject json) {
        if (json == null) {
            return new DecodeSpeedBucket(0, WIDTH, 0, 0L, 0.0);
        }
        int start = json.optInt("start", json.optInt("start_token", 0));
        int end = json.optInt("end", json.optInt("end_token", start + WIDTH));
        int tokens = json.optInt("tokens", json.optInt("generated_tokens", 0));
        long totalMs = json.optLong("total_ms", json.optLong("decode_ms", 0L));
        double tps =
                json.has("tokens_per_second")
                        ? json.optDouble("tokens_per_second", 0.0)
                        : (totalMs > 0L ? tokens * 1000.0 / totalMs : 0.0);
        return new DecodeSpeedBucket(start, end, tokens, totalMs, tps);
    }

    static List<DecodeSpeedBucket> listFromJson(JSONArray array) {
        List<DecodeSpeedBucket> buckets = new ArrayList<>();
        if (array != null) {
            for (int i = 0; i < array.length(); i++) {
                buckets.add(fromJson(array.optJSONObject(i)));
            }
        }
        return buckets;
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("start", startToken);
        json.put("end", endToken);
        json.put("tokens", tokens);
        json.put("total_ms", totalMs);
        json.put("tokens_per_second", tokensPerSecond);
        return json;
    }
}
