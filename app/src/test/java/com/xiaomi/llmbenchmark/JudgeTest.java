package com.xiaomi.llmbenchmark;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

public final class JudgeTest {
    @Test
    public void supportsExpectedJudgeObject() throws Exception {
        BenchmarkItem item =
                BenchmarkItem.fromJson(
                        new JSONObject()
                                .put("task_id", "t")
                                .put("prompt", "prompt")
                                .put(
                                        "expected_judge",
                                        new JSONObject()
                                                .put("type", "contains_any")
                                                .put("values", new org.json.JSONArray().put("alpha").put("beta"))),
                        32);
        assertTrue(Judge.score(item, "contains beta"));
        assertFalse(Judge.score(item, "contains gamma"));
    }
}
