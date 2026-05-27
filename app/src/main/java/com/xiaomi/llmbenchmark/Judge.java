package com.xiaomi.llmbenchmark;

import java.util.Locale;

final class Judge {
    private Judge() {}

    static boolean score(BenchmarkItem item, String output) {
        String normalizedOutput = normalize(output);
        String expected = item.expectedAnswer == null ? "" : item.expectedAnswer;
        if (expected.isEmpty()) {
            return false;
        }
        if ("exact".equals(item.judgeRule)) {
            return normalizedOutput.equals(normalize(expected));
        }
        String[] needles = expected.split(",");
        if ("contains_any".equals(item.judgeRule)) {
            for (String needle : needles) {
                if (normalizedOutput.contains(normalize(needle))) {
                    return true;
                }
            }
            return false;
        }
        for (String needle : needles) {
            if (!normalizedOutput.contains(normalize(needle))) {
                return false;
            }
        }
        return true;
    }

    private static String normalize(String value) {
        return value == null
                ? ""
                : value.toLowerCase(Locale.ROOT).replaceAll("\\s+", " ").trim();
    }
}

