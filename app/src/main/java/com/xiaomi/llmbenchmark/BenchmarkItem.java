package com.xiaomi.llmbenchmark;

import org.json.JSONObject;

final class BenchmarkItem {
    private static final int MIN_MAX_NEW_TOKENS = 192;

    final String id;
    final String language;
    final String category;
    final String prompt;
    final String expectedAnswer;
    final String judgeRule;
    final int maxNewTokens;

    BenchmarkItem(
            String id,
            String language,
            String category,
            String prompt,
            String expectedAnswer,
            String judgeRule,
            int maxNewTokens) {
        this.id = id;
        this.language = language;
        this.category = category;
        this.prompt = prompt;
        this.expectedAnswer = expectedAnswer;
        this.judgeRule = judgeRule;
        this.maxNewTokens = maxNewTokens;
    }

    static BenchmarkItem fromJson(JSONObject json, int defaultMaxTokens) {
        int requestedMaxTokens = json.optInt("max_new_tokens", defaultMaxTokens);
        return new BenchmarkItem(
                json.optString("id"),
                json.optString("language"),
                json.optString("category"),
                json.optString("prompt"),
                json.optString("expected_answer"),
                json.optString("judge_rule", "contains"),
                Math.max(requestedMaxTokens, MIN_MAX_NEW_TOKENS));
    }
}
