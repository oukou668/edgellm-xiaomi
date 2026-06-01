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
        if ("contains_ordered".equals(item.judgeRule)) {
            int cursor = 0;
            for (String needle : needles) {
                String normalizedNeedle = normalize(needle);
                int position = normalizedOutput.indexOf(normalizedNeedle, cursor);
                if (position < 0) {
                    return false;
                }
                cursor = position + normalizedNeedle.length();
            }
            return true;
        }
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
