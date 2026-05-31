package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class BenchmarkItem {
    private static final int MIN_MAX_NEW_TOKENS = 192;

    final String id;
    final String language;
    final String category;
    final String difficulty;
    final List<String> tags;
    final String prompt;
    final List<BenchmarkMessage> messages;
    final String expectedAnswer;
    final String judgeRule;
    final int maxNewTokens;

    BenchmarkItem(
            String id,
            String language,
            String category,
            String difficulty,
            List<String> tags,
            String prompt,
            List<BenchmarkMessage> messages,
            String expectedAnswer,
            String judgeRule,
            int maxNewTokens) {
        this.id = id;
        this.language = language;
        this.category = category;
        this.difficulty = difficulty;
        this.tags = Collections.unmodifiableList(new ArrayList<>(tags));
        this.prompt = prompt;
        this.messages = Collections.unmodifiableList(new ArrayList<>(messages));
        this.expectedAnswer = expectedAnswer;
        this.judgeRule = judgeRule;
        this.maxNewTokens = maxNewTokens;
    }

    static BenchmarkItem fromJson(JSONObject json, int defaultMaxTokens) {
        int requestedMaxTokens = json.optInt("max_new_tokens", defaultMaxTokens);
        List<String> tags = new ArrayList<>();
        JSONArray tagJson = json.optJSONArray("tags");
        if (tagJson != null) {
            for (int i = 0; i < tagJson.length(); i++) {
                tags.add(tagJson.optString(i));
            }
        }
        String prompt = json.optString("prompt", "");
        List<BenchmarkMessage> messages = new ArrayList<>();
        JSONArray messageJson = json.optJSONArray("messages");
        if (messageJson != null) {
            for (int i = 0; i < messageJson.length(); i++) {
                messages.add(BenchmarkMessage.fromJson(messageJson.optJSONObject(i)));
            }
        }
        if (messages.isEmpty()) {
            messages.add(new BenchmarkMessage("user", prompt));
        }
        return new BenchmarkItem(
                json.optString("id"),
                json.optString("language"),
                json.optString("category"),
                json.optString("difficulty", "basic"),
                tags,
                prompt,
                messages,
                json.optString("expected_answer"),
                json.optString("judge_rule", "contains"),
                Math.max(requestedMaxTokens, MIN_MAX_NEW_TOKENS));
    }

    JSONArray messagesToJson() throws Exception {
        JSONArray array = new JSONArray();
        for (BenchmarkMessage message : messages) {
            array.put(message.toJson());
        }
        return array;
    }

    String displayPrompt() {
        if (prompt != null && !prompt.isEmpty()) {
            return prompt;
        }
        for (int i = messages.size() - 1; i >= 0; i--) {
            BenchmarkMessage message = messages.get(i);
            if ("user".equals(message.role)) {
                return message.content;
            }
        }
        return messages.isEmpty() ? "" : messages.get(messages.size() - 1).content;
    }
}
