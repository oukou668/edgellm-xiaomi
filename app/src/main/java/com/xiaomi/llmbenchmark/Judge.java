package com.xiaomi.llmbenchmark;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class Judge {
    // Last \boxed{...} group, and any 1-3 digit run (AIME answers are integers 0-999).
    private static final Pattern BOXED = Pattern.compile("\\\\boxed\\s*\\{([^}]*)\\}");
    private static final Pattern DIGITS = Pattern.compile("\\d{1,3}");

    private Judge() {}

    static boolean score(BenchmarkItem item, String output) {
        String normalizedOutput = normalize(output);
        String expected = item.expectedAnswer == null ? "" : item.expectedAnswer;
        if (expected.isEmpty()) {
            return false;
        }
        if ("boxed_integer".equals(item.judgeRule) || "final_integer".equals(item.judgeRule)) {
            Integer expectedInt = parseIntInRange(expected.trim());
            if (expectedInt == null) {
                return false;
            }
            Integer actual = extractFinalInteger(output);
            return actual != null && actual.equals(expectedInt);
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

    /**
     * Pulls the model's final integer answer out of (possibly long, chain-of-thought) output:
     * prefer the last {@code \boxed{...}} integer; otherwise fall back to the last 0-999 integer in
     * the text. Lenient on purpose (MathArena aime_2026 uses {@code strict_parsing: false}).
     */
    private static Integer extractFinalInteger(String output) {
        if (output == null || output.isEmpty()) {
            return null;
        }
        Matcher boxed = BOXED.matcher(output);
        String lastBoxed = null;
        while (boxed.find()) {
            lastBoxed = boxed.group(1);
        }
        if (lastBoxed != null) {
            Integer fromBoxed = firstIntInRange(lastBoxed);
            if (fromBoxed != null) {
                return fromBoxed;
            }
        }
        Matcher digits = DIGITS.matcher(output);
        Integer last = null;
        while (digits.find()) {
            Integer value = parseIntInRange(digits.group());
            if (value != null) {
                last = value;
            }
        }
        return last;
    }

    private static Integer firstIntInRange(String value) {
        Matcher digits = DIGITS.matcher(value);
        while (digits.find()) {
            Integer parsed = parseIntInRange(digits.group());
            if (parsed != null) {
                return parsed;
            }
        }
        return null;
    }

    private static Integer parseIntInRange(String value) {
        if (value == null) {
            return null;
        }
        try {
            int parsed = Integer.parseInt(value.trim());
            return parsed >= 0 && parsed <= 999 ? parsed : null;
        } catch (NumberFormatException ignored) {
            return null;
        }
    }
}
