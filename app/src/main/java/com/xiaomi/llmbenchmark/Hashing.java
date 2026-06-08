package com.xiaomi.llmbenchmark;

import java.io.File;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

final class Hashing {
    private Hashing() {}

    static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] buffer = new byte[1024 * 1024];
        try (FileInputStream input = new FileInputStream(file)) {
            int read;
            while ((read = input.read(buffer)) != -1) {
                digest.update(buffer, 0, read);
            }
        }
        return hex(digest.digest());
    }

    static String sha256(String text) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        digest.update((text == null ? "" : text).getBytes(StandardCharsets.UTF_8));
        return hex(digest.digest());
    }

    private static String hex(byte[] hash) {
        StringBuilder builder = new StringBuilder(hash.length * 2);
        for (byte value : hash) {
            builder.append(String.format("%02x", value & 0xff));
        }
        return builder.toString();
    }
}
