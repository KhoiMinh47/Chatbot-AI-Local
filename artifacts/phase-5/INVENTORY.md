# Phase 5 evidence inventory

Inventory này phân biệt canonical winner evidence với rejected/debug history.
SHA-256 được kiểm lại từ bytes hiện có trong workspace ngày 2026-07-15.

## Canonical finalization run

Directory:
[`runs/20260715T022157Z-embed300m-final-r3`](runs/20260715T022157Z-embed300m-final-r3)

| Artifact | Mục đích | SHA-256 |
|---|---|---|
| [`decision-report.json`](runs/20260715T022157Z-embed300m-final-r3/decision-report.json) | Immutable decision, exact inputs/runtime/source/config/policy/metrics | `290d1b34f7c350658207dea14c8e1f045314fc2126c3522adeecf1eea12cb610` |
| [`activation-receipt.json`](runs/20260715T022157Z-embed300m-final-r3/activation-receipt.json) | Post-decision atomic alias switch và read-back | `2b0f68582a8e1398b4507e73a596887fa271cf33308456efeb294225f08fd76f` |
| [`calibration-raw-observations.jsonl`](runs/20260715T022157Z-embed300m-final-r3/calibration-raw-observations.jsonl) | 50 calibration-query raw observations | `03c1741d8275b9db654bee701c6f99a54eaaa5f159ff6ca76ffde805ccd9ed23` |
| [`evaluation-raw-observations.jsonl`](runs/20260715T022157Z-embed300m-final-r3/evaluation-raw-observations.jsonl) | 50 held-out raw dense observations | `6fdf8684e11966d8d61824fe8aad1937e039b01a64e16be722d90853387a3ba6` |
| [`evaluation-policy-observations.jsonl`](runs/20260715T022157Z-embed300m-final-r3/evaluation-policy-observations.jsonl) | 50 held-out approved-policy observations | `2551155d39d132b339d9bb1d1d50e2e82cf2e770037833d27e5b8327670fb226` |
| [`acl-qdrant-contract.xml`](runs/20260715T022157Z-embed300m-final-r3/acl-qdrant-contract.xml) | Live ACL + dimension/model immutable-contract JUnit; 1 pass | `f62ff66e3ed876efec12ac32645b13b79e2bbf874c06f8c220ba123ea18d789c` |

Decision report tự bind ba observation hashes. Receipt tự bind decision-report
hash `290d...` cùng index fingerprint, retrieval-policy fingerprint và expected
point count; vì vậy decision và activation không bị nhập thành một mutable file.

## External canonical input

| Artifact | Mục đích | SHA-256 |
|---|---|---|
| [`../phase-4/runs/20260715T0912Z-live-e2e-r3/gold-final-100-v2-stratified.jsonl`](../phase-4/runs/20260715T0912Z-live-e2e-r3/gold-final-100-v2-stratified.jsonl) | Gold 100 case: 50 calibration + 50 evaluation | `393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3` |
| READY corpus manifest (canonical hash in decision report) | 10 document, 10 current version, 12 child chunk | `095bc081a101f02197934cdc8849c20287fba99aeede3d6730ea94ffa55b5bac` |

Corpus manifest là canonical digest của authoritative PostgreSQL rows; nó không
phải file chứa plaintext document. Decision report xác nhận không ghi database
URL hoặc document text.

## Rejected finalization history

Các file này được giữ để audit debug; không có activation receipt và không phải
winner evidence.

### `20260715T021639Z-embed300m-final` (`r1`)

| Artifact | SHA-256 |
|---|---|
| `decision-report.json` | `394d862a3fade32f7b6ce1c726d900b2bb89021ccbe0c682cc9411dbfb7544e4` |
| `calibration-raw-observations.jsonl` | `f1d3d905f54dab6dd30ad11f363b5406d2aa14d581753e34d6f8c4f26422c246` |
| `evaluation-raw-observations.jsonl` | `977c16a29ff0801eab9ed8e9018f779d3292a58ef3757c36bd8585c3fa5d1ad6` |
| `evaluation-policy-observations.jsonl` | `91778e7d85366b72b4baed1132b1d73916c9bc6a5c04e5f8233a84faa55c4824` |

Status `REJECTED`; held-out Recall/MRR/nDCG `0.65`; alias không activate.

### `20260715T022021Z-embed300m-final-r2` (`r2`)

| Artifact | SHA-256 |
|---|---|
| `decision-report.json` | `21eea8a0c6625efbb8db768c0673f0fa13c0a1cebb847ead2197fdf33f9bcde2` |
| `calibration-raw-observations.jsonl` | `610b493db25f713b2b86f2cbfc9e31f09e03186fbb1f02af5976a193c2c40906` |
| `evaluation-raw-observations.jsonl` | `2ccc3d5671d2055a0d7cb2ced2753f207815212b9cef92737dfc53f0dfbd4293` |
| `evaluation-policy-observations.jsonl` | `13a25e389a4c69ec6ab467024775a1f1aeff8b8d02176d043be9fde9e7890424` |

Status `REJECTED`; max-F1 threshold `0.3152053`; held-out
Recall/MRR/nDCG `0.775`; alias không activate.

## Superseded candidate evidence

Directories `20260714T172546Z-embed300m-r2` đến
`20260714T175000Z-embed300m-r5` là chunk-grid/candidate benchmark history trên
fixture cũ. Chúng hữu ích để audit các bug token-window và
cut-before-deduplicate, nhưng không được dùng để thay final decision, corpus
manifest, held-out split hoặc alias receipt của canonical `r3`.

[`runtime-cleanup.md`](runtime-cleanup.md) chỉ ghi cleanup của candidate run
`20260714T175000Z-embed300m-r5`; nó không mô tả lifecycle runtime đang được dùng
cho Phase 6.
