package com.xiaomi.llmbenchmark;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

public final class BenchmarkItemTest {
    @Test
    public void parsesFormalReproductionMetadata() throws Exception {
        BenchmarkItem item =
                BenchmarkItem.fromJson(
                        new JSONObject()
                                .put("task_id", "mmlu_pro__1")
                                .put("dataset_id", "mmlu_pro")
                                .put("sample_id", "1")
                                .put("prompt", "Question?")
                                .put("expected_answer", "A")
                                .put("judge_rule", "external_scorer")
                                .put("scorer_id", "exact_match_letter_v1")
                                .put("parser_id", "mc_letter_v1")
                                .put("profile_group_id", "G1")
                                .put("generation_profile_id", "G1_32768_4096")
                                .put("dataset_artifact_hash", "hash")
                                .put("official_table_score", 48.85)
                                .put(
                                        "generation_params",
                                        new JSONObject()
                                                .put("temperature", 0.9)
                                                .put("top_p", 0.95)
                                                .put("max_tokens", 4096)
                                                .put("thinking_enabled", true)),
                        32);

        assertEquals("mmlu_pro", item.datasetId);
        assertEquals("exact_match_letter_v1", item.scorerId);
        assertEquals("mc_letter_v1", item.parserId);
        assertEquals("G1_32768_4096", item.generationProfileId);
        assertEquals(4096, item.resolvedParams(GenerationParams.fromJson(null)).maxTokens);
        assertTrue(item.resolvedParams(GenerationParams.fromJson(null)).thinkingEnabled);
        assertEquals("hash", item.metadataToJson().getString("dataset_artifact_hash"));
    }
}
