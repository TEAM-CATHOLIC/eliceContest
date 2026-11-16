"""Offline frozen multilingual E5 + logistic regression development prototype."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

LABELS = ["signup", "security", "activity", "terms", "deleted", "promo"]
ROOT = Path(__file__).resolve().parent
MODEL_ID = "intfloat/multilingual-e5-small"


def model_text(row):
    # Never feed labels, suggested labels, comments, filenames, or domain groups to the model.
    return "query: " + row.get("subject", "") + "\n" + row.get("body_text", "")


def load_rows(path):
    rows = [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate mail IDs")
    return rows


def stage_hint(subject, body):
    """Supplementary deterministic hint, independent from six-way ML prediction."""
    text = subject + "\n" + body[:1600]
    if re.search(r"계정.{0,25}(?:찾을 수 없|찾지 못|연결된 계정이 없)", text):
        return "account_not_found"
    if "이미 연결된 AWS 계정" in text or "이메일이 이미 AWS 계정" in text:
        return "existing_address_signup_blocked"
    if re.search(r"(?:구독|이모티콘 플러스).{0,25}해지(?:되었|가 완료)", text):
        return "subscription_cancelled"
    if re.search(
        r"(?:계정.{0,30}(?:삭제처리 되었|삭제되었습니다|안전하게 파기되었)|회원 탈퇴(?:가| 처리가)? 완료)",
        text,
    ):
        return "account_deleted_completed"
    if re.search(r"인증.{0,15}(?:필수적인 단계|마쳐야|완료해야)|이메일.{0,5}인증(?:하기|해)", text):
        return "requested"
    if re.search(
        r"비밀번호.{0,30}(?:요청|링크입니다)|비밀번호.{0,15}변경해주세요", text
    ) and not re.search(
        r"비밀번호(?:가| 변경이| 재설정이)? (?:성공적으로 )?(?:변경되었|재설정되었|완료)", text
    ):
        return "requested"
    return "unknown"


def explicit_rule(subject, body):
    """Narrow deterministic fallback; rules are not learned-model performance."""
    hint = stage_hint(subject, body)
    if hint == "account_deleted_completed":
        return "deleted", "본문의 계정 삭제 완료 표현"
    if re.match(r"^\s*[([]?광고[)\]]?", subject):
        return "promo", "제목의 광고 표시"
    if re.search(r"약관|처리방침|개인정보 이용.{0,5}내역|휴면", subject):
        return "terms", "제목의 약관·휴면 안내"
    if hint == "requested" and re.search(r"가입|이메일 인증", subject + " " + body[:500]):
        return "signup", "가입용 이메일 인증 요청"
    if re.search(r"회원\s*가입\s*완료", subject) and re.search(
        r"회원이 되신|가입.{0,15}완료|계정 생성.{0,15}완료", body[:600]
    ):
        return "signup", "제목과 본문의 명시적 가입 완료"
    return None, None


class Encoder:
    def __init__(self, model_path):
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(min(4, os.cpu_count() or 1))
        self.model = SentenceTransformer(
            str(model_path), local_files_only=True, device="cpu", trust_remote_code=False
        )
        self.model.max_seq_length = 512

    def encode(self, rows, on_progress=None, should_cancel=None):
        import numpy as np

        batches = []
        for start in range(0, len(rows), 8):
            if should_cancel and should_cancel():
                raise InterruptedError("Analysis cancelled")
            batches.append(
                self.model.encode(
                    [model_text(r) for r in rows[start : start + 8]],
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            )
            if on_progress:
                on_progress(min(start + 8, len(rows)), len(rows))
        return np.concatenate(batches) if batches else np.empty((0, 384))


def split_rows(rows):
    """One deterministic group holdout; no metric-based split selection."""
    from sklearn.model_selection import GroupShuffleSplit

    y = [r["label"] for r in rows]
    groups = [r["split_group"] for r in rows]
    # Find first split with all six classes in both sets. No performance is inspected.
    for train, test in GroupShuffleSplit(n_splits=200, test_size=0.25, random_state=42).split(
        rows, y, groups
    ):
        if {y[i] for i in train} == set(LABELS) and {y[i] for i in test} == set(LABELS):
            assert not {groups[i] for i in train} & {groups[i] for i in test}
            return train, test
    raise ValueError("Not enough independent service groups per class for six-class holdout")


def train(args):
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
    from sklearn.pipeline import make_pipeline

    rows = [r for r in load_rows(args.input) if r.get("training_eligible")]
    if any(r.get("label") not in LABELS for r in rows):
        raise ValueError("Missing or invalid draft label")
    if not args.allow_draft and any(not r.get("user_verified") for r in rows):
        raise ValueError(
            "User-unverified labels. Explicit --allow-draft only for development runs."
        )
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    train_idx, test_idx = split_rows(rows)
    y = np.array([r["label"] for r in rows])
    encoder = Encoder(args.model_path)
    x = encoder.encode(rows, lambda done, total: print(f"Embedding {done}/{total}", flush=True))
    clf = LogisticRegression(class_weight="balanced", max_iter=2000, random_state=42)
    clf.fit(x[train_idx], y[train_idx])
    pred = clf.predict(x[test_idx])
    baseline = make_pipeline(
        TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1, max_features=30000),
        LogisticRegression(class_weight="balanced", max_iter=2000, random_state=42),
    )
    texts = [model_text(r) for r in rows]
    baseline.fit([texts[i] for i in train_idx], y[train_idx])
    bp = baseline.predict([texts[i] for i in test_idx])

    def metrics(p):
        return {
            "accuracy": float(accuracy_score(y[test_idx], p)),
            "macro_f1": float(
                f1_score(y[test_idx], p, labels=LABELS, average="macro", zero_division=0)
            ),
            "per_class": classification_report(
                y[test_idx], p, labels=LABELS, output_dict=True, zero_division=0
            ),
            "confusion_matrix": confusion_matrix(y[test_idx], p, labels=LABELS).tolist(),
        }

    report = {
        "status": "development_only_assistant_labels_not_gold",
        "label_order": LABELS,
        "input_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
        "train_count": len(train_idx),
        "test_count": len(test_idx),
        "train_groups": sorted({rows[i]["split_group"] for i in train_idx}),
        "test_groups": sorted({rows[i]["split_group"] for i in test_idx}),
        "embedding": metrics(pred),
        "tfidf_baseline": metrics(bp),
        "warnings": [
            "Assistant draft labels: not independent gold evaluation.",
            "Only two deletion examples; each split has one.",
            "Model input truncated at 512 tokens; long-body evidence may be missed.",
            "Groups use curated aliases; unknown related providers may remain.",
            "No calibrated account-existence probability.",
        ],
    }
    (out / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    predictions = [
        {
            "id": rows[i]["id"],
            "truth_draft": rows[i]["label"],
            "prediction": str(p),
            "baseline": str(b),
            "split_group": rows[i]["split_group"],
        }
        for i, p, b in zip(test_idx, pred, bp)
    ]
    (out / "holdout_predictions.json").write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Ship a fitted dev model using only training partition; preserve untouched holdout.
    (out / "weights.json").write_text(
        json.dumps(
            {
                "classes": clf.classes_.tolist(),
                "coef": clf.coef_.tolist(),
                "intercept": clf.intercept_.tolist(),
            }
        ),
        encoding="utf-8",
    )
    import importlib.metadata

    manifest = {
        "model_id": MODEL_ID,
        "model_path": str(Path(args.model_path).resolve()),
        "max_tokens": 512,
        "prefix": "query: ",
        "normalization": True,
        "encoder_frozen": True,
        "classes": clf.classes_.tolist(),
        "label_status": "assistant_draft_not_gold",
        "train_ids": [rows[i]["id"] for i in train_idx],
        "test_ids": [rows[i]["id"] for i in test_idx],
        "packages": {
            p: importlib.metadata.version(p)
            for p in ["sentence-transformers", "scikit-learn", "torch", "transformers"]
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "train": len(train_idx),
                "test": len(test_idx),
                "embedding_macro_f1": report["embedding"]["macro_f1"],
                "baseline_macro_f1": report["tfidf_baseline"]["macro_f1"],
                "development_only": True,
            }
        )
    )


class Predictor:
    def __init__(self, artifacts):
        artifacts = Path(artifacts)
        self.manifest = json.loads((artifacts / "manifest.json").read_text(encoding="utf-8"))
        if self.manifest.get("model_id") != MODEL_ID or self.manifest.get("prefix") != "query: ":
            raise ValueError("Unsupported local embedding model or input prefix")
        weights = json.loads((artifacts / "weights.json").read_text(encoding="utf-8"))
        self.clf = LinearHead(weights)
        self.encoder = Encoder(self.manifest["model_path"])

    def predict(self, rows, on_progress=None, should_cancel=None):
        if not rows:
            return []
        x = self.encoder.encode(rows, on_progress, should_cancel)
        output = []
        for row, probabilities in zip(rows, self.clf.predict_proba(x)):
            values = {str(c): float(p) for c, p in zip(self.clf.classes_, probabilities)}
            model_label = max(values, key=values.get)
            rule_label, reason = explicit_rule(row.get("subject", ""), row.get("body_text", ""))
            label = rule_label or model_label
            output.append(
                {
                    "id": row["id"],
                    "type": label,
                    "classification_score": values[label],
                    "model_type": model_label,
                    "model_score": values[model_label],
                    "decision_source": "rule" if rule_label else "model",
                    "rule_reason": reason,
                    "scores": values,
                    "needs_review": not rule_label and values[label] < 0.6,
                    "stage_hint": stage_hint(row.get("subject", ""), row.get("body_text", "")),
                    "model_status": "development_draft_labels",
                }
            )
        return output


class LinearHead:
    """Portable JSON coefficients; no executable pickle or sklearn-version coupling."""

    def __init__(self, weights):
        import numpy as np

        self.classes_ = weights["classes"]
        self.coef = np.asarray(weights["coef"], dtype=float)
        self.intercept = np.asarray(weights["intercept"], dtype=float)
        if (
            set(self.classes_) != set(LABELS)
            or len(self.classes_) != 6
            or self.coef.shape != (6, 384)
            or self.intercept.shape != (6,)
            or not np.isfinite(self.coef).all()
            or not np.isfinite(self.intercept).all()
        ):
            raise ValueError("Invalid six-class linear model weights")

    def predict_proba(self, x):
        import numpy as np

        logits = x @ self.coef.T + self.intercept
        logits -= logits.max(axis=1, keepdims=True)
        values = np.exp(logits)
        return values / values.sum(axis=1, keepdims=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    tr = subs.add_parser("train")
    tr.add_argument("--input", default=str(ROOT / "private/annotated_draft.jsonl"))
    tr.add_argument("--model-path", required=True)
    tr.add_argument("--output", default=str(ROOT / "artifacts"))
    tr.add_argument("--allow-draft", action="store_true")
    pr = subs.add_parser("predict")
    pr.add_argument("--input", required=True)
    pr.add_argument("--output", required=True)
    pr.add_argument("--artifacts", default=str(ROOT / "artifacts"))
    args = parser.parse_args()
    if args.command == "train":
        train(args)
    else:
        results = Predictor(args.artifacts).predict(load_rows(args.input))
        Path(args.output).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8"
        )
        print(f"Predicted {len(results)} messages locally")


if __name__ == "__main__":
    main()
