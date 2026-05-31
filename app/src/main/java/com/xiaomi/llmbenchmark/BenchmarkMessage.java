package com.xiaomi.llmbenchmark;

import org.json.JSONObject;

final class BenchmarkMessage {
    final String role;
    final String content;

    BenchmarkMessage(String role, String content) {
        this.role = role == null || role.isEmpty() ? "user" : role;
        this.content = content == null ? "" : content;
    }

    static BenchmarkMessage fromJson(JSONObject json) {
        if (json == null) {
            return new BenchmarkMessage("user", "");
        }
        return new BenchmarkMessage(json.optString("role", "user"), json.optString("content", ""));
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("role", role);
        json.put("content", content);
        return json;
    }
}
