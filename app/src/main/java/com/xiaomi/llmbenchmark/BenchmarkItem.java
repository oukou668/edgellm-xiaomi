package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class BenchmarkItem {
    private static final int MIN_MAX_NEW_TOKENS = 1;

    final String id;
    final String language;
    final String category;
    final String promptClass;
    final String difficulty;
    final List<String> tags;
    final String prompt;
    final List<BenchmarkMessage> messages;
    final String expectedAnswer;
    final String judgeRule;
    final int maxNewTokens;
    final String datasetId;
    final String sampleId;
    final String scorerId;
    final String parserId;
    final String profileGroupId;
    final String generationProfileId;
    final String datasetArtifactHash;
    final String promptHash;
    final double officialTableScore;
    final GenerationParams generationParams;
    final JSONObject extraMetadata;

    BenchmarkItem(
            String id,
            String language,
            String category,
            String promptClass,
            String difficulty,
            List<String> tags,
            String prompt,
            List<BenchmarkMessage> messages,
            String expectedAnswer,
            String judgeRule,
            int maxNewTokens,
            String datasetId,
            String sampleId,
            String scorerId,
            String parserId,
            String profileGroupId,
            String generationProfileId,
            String datasetArtifactHash,
            String promptHash,
            double officialTableScore,
            GenerationParams generationParams,
            JSONObject extraMetadata) {
        this.id = id;
        this.language = language;
        this.category = category;
        this.promptClass = promptClass;
        this.difficulty = difficulty;
        this.tags = Collections.unmodifiableList(new ArrayList<>(tags));
        this.prompt = prompt;
        this.messages = Collections.unmodifiableList(new ArrayList<>(messages));
        this.expectedAnswer = expectedAnswer;
        this.judgeRule = judgeRule;
        this.maxNewTokens = maxNewTokens;
        this.datasetId = datasetId == null ? "" : datasetId;
        this.sampleId = sampleId == null ? "" : sampleId;
        this.scorerId = scorerId == null ? "" : scorerId;
        this.parserId = parserId == null ? "" : parserId;
        this.profileGroupId = profileGroupId == null ? "" : profileGroupId;
        this.generationProfileId = generationProfileId == null ? "" : generationProfileId;
        this.datasetArtifactHash = datasetArtifactHash == null ? "" : datasetArtifactHash;
        this.promptHash = promptHash == null ? "" : promptHash;
        this.officialTableScore = officialTableScore;
        this.generationParams = generationParams;
        this.extraMetadata = copyMetadata(extraMetadata);
    }

    static BenchmarkItem fromJson(JSONObject json, int defaultMaxTokens) {
        JSONObject generationParamsJson = json.optJSONObject("generation_params");
        int requestedMaxTokens =
                json.has("max_new_tokens")
                        ? json.optInt("max_new_tokens", defaultMaxTokens)
                        : generationParamsJson == null
                                ? defaultMaxTokens
                                : generationParamsJson.optInt(
                                        "max_tokens", generationParamsJson.optInt("max_new_tokens", defaultMaxTokens));
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
        JSONObject expectedJudge = json.optJSONObject("expected_judge");
        String judgeRule = json.optString("judge_rule", "contains");
        String expectedAnswer = json.optString("expected_answer");
        if (expectedJudge != null) {
            judgeRule = expectedJudge.optString("type", judgeRule);
            JSONArray values = expectedJudge.optJSONArray("values");
            if (values != null) {
                List<String> expectedValues = new ArrayList<>();
                for (int i = 0; i < values.length(); i++) {
                    expectedValues.add(values.optString(i));
                }
                expectedAnswer = String.join(",", expectedValues);
            }
        }
        return new BenchmarkItem(
                json.optString("task_id", json.optString("id")),
                json.optString("language"),
                json.optString("category"),
                json.optString("prompt_class", prompt.length() > 160 ? "long" : "short"),
                json.optString("difficulty", "basic"),
                tags,
                prompt,
                messages,
                expectedAnswer,
                judgeRule,
                Math.max(requestedMaxTokens, MIN_MAX_NEW_TOKENS),
                json.optString("dataset_id", json.optString("dataset")),
                json.optString("sample_id", json.optString("task_id", json.optString("id"))),
                json.optString("scorer_id"),
                json.optString("parser_id"),
                json.optString("profile_group_id"),
                json.optString("generation_profile_id"),
                json.optString("dataset_artifact_hash"),
                json.optString("prompt_hash"),
                json.has("official_table_score") ? json.optDouble("official_table_score") : Double.NaN,
                readGenerationParams(json, requestedMaxTokens),
                json.optJSONObject("metadata"));
    }

    GenerationParams resolvedParams(GenerationParams defaults) {
        GenerationParams base = generationParams == null ? defaults : generationParams;
        return base.withMaxTokens(maxNewTokens);
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

    JSONObject metadataToJson() throws Exception {
        JSONObject json = new JSONObject(extraMetadata.toString());
        json.put("dataset_id", datasetId);
        json.put("sample_id", sampleId);
        json.put("scorer_id", scorerId);
        json.put("parser_id", parserId);
        json.put("profile_group_id", profileGroupId);
        json.put("generation_profile_id", generationProfileId);
        json.put("dataset_artifact_hash", datasetArtifactHash);
        json.put("prompt_hash", promptHash);
        if (!Double.isNaN(officialTableScore)) {
            json.put("official_table_score", officialTableScore);
        }
        json.put("generation_params", resolvedParams(generationParams == null ? GenerationParams.fromJson(null) : generationParams).toJson());
        return json;
    }

    private static GenerationParams readGenerationParams(JSONObject json, int maxTokens) {
        JSONObject paramsJson = json.optJSONObject("generation_params");
        if (paramsJson == null) {
            paramsJson = new JSONObject();
        }
        if (!paramsJson.has("max_tokens")) {
            try {
                paramsJson.put("max_tokens", maxTokens);
            } catch (Exception ignored) {
            }
        }
        return GenerationParams.fromJson(paramsJson);
    }

    private static JSONObject copyMetadata(JSONObject metadata) {
        if (metadata == null) {
            return new JSONObject();
        }
        try {
            return new JSONObject(metadata.toString());
        } catch (Exception ignored) {
            return new JSONObject();
        }
    }
}
