package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class ModelRegistry {
    private final List<ModelConfig> models;

    private ModelRegistry(List<ModelConfig> models) {
        this.models = Collections.unmodifiableList(models);
    }

    static ModelRegistry load(Context context) throws Exception {
        JSONObject root = new JSONObject(AssetText.read(context, "models.json"));
        JSONArray jsonModels = root.optJSONArray("models");
        List<ModelConfig> models = new ArrayList<>();
        if (jsonModels != null) {
            for (int i = 0; i < jsonModels.length(); i++) {
                models.add(ModelConfig.fromJson(jsonModels.getJSONObject(i)));
            }
        }
        return new ModelRegistry(models);
    }

    List<ModelConfig> all() {
        return models;
    }
}

