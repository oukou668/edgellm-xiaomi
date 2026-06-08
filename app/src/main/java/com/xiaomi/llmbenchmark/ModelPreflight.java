package com.xiaomi.llmbenchmark;

import java.io.File;

final class ModelPreflight {
    private ModelPreflight() {}

    static void verify(ModelConfig model, File modelDir) throws Exception {
        if (!modelDir.exists()) {
            throw new IllegalStateException("Model directory is missing: " + modelDir.getAbsolutePath());
        }
        if (model.isLlamaCpp()) {
            verifyGguf(model, modelDir);
        } else if (model.isMlc()) {
            verifyMlc(model, modelDir);
        }
    }

    private static void verifyGguf(ModelConfig model, File modelDir) throws Exception {
        File gguf = new File(modelDir, model.artifactFilename);
        if (!gguf.exists() || !gguf.isFile()) {
            throw new IllegalStateException("GGUF file is missing: " + gguf.getAbsolutePath());
        }
        if (model.artifactSizeBytes > 0L && gguf.length() != model.artifactSizeBytes) {
            throw new IllegalStateException(
                    "GGUF file size mismatch. expected="
                            + model.artifactSizeBytes
                            + " actual="
                            + gguf.length());
        }
        if (!model.artifactSha256.isEmpty()) {
            String actual = Hashing.sha256(gguf);
            if (!actual.equalsIgnoreCase(model.artifactSha256)) {
                throw new IllegalStateException(
                        "GGUF sha256 mismatch. expected=" + model.artifactSha256 + " actual=" + actual);
            }
        }
    }

    private static void verifyMlc(ModelConfig model, File modelDir) {
        if (model.requiredFiles.isEmpty()) {
            return;
        }
        for (String requiredFile : model.requiredFiles) {
            if (!containsFile(modelDir, requiredFile)) {
                throw new IllegalStateException("MLC required file is missing: " + requiredFile);
            }
        }
        if (!containsFileWithPrefix(modelDir, "params_shard_", ".bin")) {
            throw new IllegalStateException("MLC params_shard_*.bin is missing.");
        }
    }

    private static boolean containsFile(File root, String name) {
        File[] files = root.listFiles();
        if (files == null) {
            return false;
        }
        for (File file : files) {
            if (file.getName().equals(name)) {
                return true;
            }
            if (file.isDirectory() && containsFile(file, name)) {
                return true;
            }
        }
        return false;
    }

    private static boolean containsFileWithPrefix(File root, String prefix, String suffix) {
        File[] files = root.listFiles();
        if (files == null) {
            return false;
        }
        for (File file : files) {
            if (file.getName().startsWith(prefix) && file.getName().endsWith(suffix)) {
                return true;
            }
            if (file.isDirectory() && containsFileWithPrefix(file, prefix, suffix)) {
                return true;
            }
        }
        return false;
    }
}

