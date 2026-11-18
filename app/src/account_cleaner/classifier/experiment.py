"""Reproducible local multi-head development experiment; no private data in this module."""

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
from pathlib import Path

from .model import MODEL_ID, Encoder

TARGETS = {
    "type": ("type_label", {"signup", "security", "activity", "terms", "deleted", "promo"}),
    "relevance": ("relevance_label", {"candidate", "weak", "unrelated", "suspicious"}),
    "stage": (
        "stage_label",
        {"completed", "requested", "notice", "transaction", "promotion", "deletion_scheduled"},
    ),
}


def validate_rows(rows):
    seen = set()
    for row in rows:
        if not isinstance(row.get("id"), str) or not row["id"] or row["id"] in seen:
            raise ValueError("Missing or duplicate message ID")
        seen.add(row["id"])
        if not isinstance(row.get("group"), str) or not row["group"]:
            raise ValueError("Independent group key required")
        if row.get("role") in {"reserved_candidate", "test", "final_evaluation"}:
            raise ValueError("Reserved/final evaluation records cannot be used in this experiment")
        if row.get("provenance") not in {
            "human_verified",
            "assistant_draft_existing",
            "assistant_semantic_draft_tovnet",
        }:
            raise ValueError("Explicit annotation provenance required")
        for key in ("subject", "body_text"):
            if not isinstance(row.get(key), str):
                raise TypeError("Plain text inputs required")
        if (
            not isinstance(row.get("weight"), (float, int))
            or not math.isfinite(row["weight"])
            or row["weight"] <= 0
        ):
            raise ValueError("Finite positive sample weight required")
        for field, labels in TARGETS.values():
            if row.get(field) is not None and row[field] not in labels:
                raise ValueError(f"Unknown label: {field}")


def fit_heads(rows, features):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report, f1_score
    from sklearn.model_selection import GroupShuffleSplit

    validate_rows(rows)
    features = np.asarray(features)
    if features.shape != (len(rows), 384) or not np.isfinite(features).all():
        raise ValueError("Expected finite 384-dimensional features in input row order")
    splitter = GroupShuffleSplit(n_splits=500, test_size=0.25, random_state=42)
    for train, test in splitter.split(rows, groups=[r["group"] for r in rows]):
        if all(
            {rows[i][field] for i in train if rows[i][field]} == labels
            and {rows[i][field] for i in test if rows[i][field]} == labels
            for field, labels in [TARGETS["type"], TARGETS["relevance"]]
        ):
            break
    else:
        raise ValueError("Not enough independent groups to cover type and relevance labels")
    assert not {rows[i]["group"] for i in train} & {rows[i]["group"] for i in test}
    heads, metrics = {}, {}
    for name, (field, _labels) in TARGETS.items():
        tr = [i for i in train if rows[i][field]]
        te = [i for i in test if rows[i][field]]
        model = LogisticRegression(class_weight="balanced", C=4.0, max_iter=2000, random_state=42)
        model.fit(
            features[tr],
            [rows[i][field] for i in tr],
            sample_weight=[rows[i]["weight"] for i in tr],
        )
        predicted = model.predict(features[te])
        truth = [rows[i][field] for i in te]
        heads[name] = {
            "classes": model.classes_.tolist(),
            "coef": model.coef_.tolist(),
            "intercept": model.intercept_.tolist(),
        }
        metrics[name] = {
            "train": len(tr),
            "test": len(te),
            "accuracy": float(accuracy_score(truth, predicted)),
            "macro_f1": float(f1_score(truth, predicted, average="macro", zero_division=0)),
            "per_class": classification_report(truth, predicted, output_dict=True, zero_division=0),
        }
    return heads, metrics, train.tolist(), test.tolist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = args.input.read_bytes()
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    validate_rows(rows)
    args.output.mkdir(parents=True, exist_ok=False)
    features = Encoder(args.model_path).encode(
        rows, lambda n, t: print(f"Embedding {n}/{t}", flush=True)
    )
    heads, metrics, train, test = fit_heads(rows, features)
    weights = json.dumps({"schema_version": 2, "heads": heads}).encode()
    (args.output / "weights.json").write_bytes(weights)
    manifest = {
        "schema_version": 2,
        "status": "development_teacher_labels_not_gold",
        "model_id": MODEL_ID,
        "model_path": str(args.model_path.resolve()),
        "encoder_frozen": True,
        "prefix": "query: ",
        "max_tokens": 512,
        "embedding_dimension": 384,
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "training_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "weights_sha256": hashlib.sha256(weights).hexdigest(),
        "python": platform.python_version(),
        "packages": {
            p: importlib.metadata.version(p)
            for p in ["sentence-transformers", "scikit-learn", "torch", "transformers"]
        },
        "parameters": {"class_weight": "balanced", "C": 4.0, "max_iter": 2000, "random_state": 42},
        "train_indices": train,
        "test_indices": test,
        "sample_weight_policy": "Input weights: human-reviewed records 2.0, assistant drafts 1.0; ambiguous targets null",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (args.output / "evaluation.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "train": len(train),
                "test": len(test),
                "input_sha256": manifest["input_sha256"],
                "metrics": {
                    k: {n: v[n] for n in ["train", "test", "accuracy", "macro_f1"]}
                    for k, v in metrics.items()
                },
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
