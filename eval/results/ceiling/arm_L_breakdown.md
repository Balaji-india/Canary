Arm L breakdown, `skeptic_d` (openai/gpt-oss-120b). Locked outcome: SOLVABLE. Exploratory, decides nothing. Intervals: 95% Jeffreys per proportion, clustering ignored.

**1. Recall per bug class and tier (caught / planted)**

| Class | obvious | subtle | Both tiers | Planted class named, of caught |
|---|---|---|---|---|
| B01 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 6/6 (100%) [0.67, 1.00] |
| B02 | 3/3 | 2/3 | 5/6 (83%) [0.44, 0.98] | 5/5 (100%) [0.62, 1.00] |
| B03 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 6/6 (100%) [0.67, 1.00] |
| B04 | 3/3 | 2/3 | 5/6 (83%) [0.44, 0.98] | 5/5 (100%) [0.62, 1.00] |
| B05 | 3/3 | 2/3 | 5/6 (83%) [0.44, 0.98] | 5/5 (100%) [0.62, 1.00] |
| B06 | 0/3 | 0/3 | 0/6 (0%) [0.00, 0.33] | none caught |
| B07 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 6/6 (100%) [0.67, 1.00] |
| B08 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 6/6 (100%) [0.67, 1.00] |
| B09 | 1/3 | 0/3 | 1/6 (17%) [0.02, 0.56] | 1/1 (100%) [0.15, 1.00] |
| B10 | 3/3 | 3/3 | 6/6 (100%) [0.67, 1.00] | 0/6 (0%) [0.00, 0.33] |
| All | 25/30 (83%) [0.67, 0.93] | 21/30 (70%) [0.52, 0.84] | 46/60 (77%) [0.65, 0.86] | 40/46 (87%) [0.75, 0.94] |

**1b. Recall by batch**

| Batch | Caught |
|---|---|
| ceiling-ext | 29/40 (72%) [0.57, 0.84] |
| task-dev-2 | 17/20 (85%) [0.65, 0.96] |

**1b. Recall by dataset**

| Dataset | Caught |
|---|---|
| blood-transfusion-service-center | 5/5 (100%) [0.62, 1.00] |
| breast_cancer | 6/7 (86%) [0.50, 0.98] |
| credit-g | 6/8 (75%) [0.41, 0.94] |
| diabetes | 5/8 (62%) [0.29, 0.88] |
| digits | 4/4 (100%) [0.56, 1.00] |
| ozone-level-8hr | 3/4 (75%) [0.28, 0.97] |
| pc1 | 5/12 (42%) [0.18, 0.69] |
| phoneme | 7/7 (100%) [0.71, 1.00] |
| wine | 5/5 (100%) [0.62, 1.00] |

**1b. Recall by metric**

| Metric | Caught |
|---|---|
| accuracy | 12/13 (92%) [0.69, 0.99] |
| balanced_accuracy | 8/11 (73%) [0.43, 0.92] |
| f1 | 15/24 (62%) [0.43, 0.80] |
| roc_auc | 11/12 (92%) [0.67, 0.99] |

**1b. Recall by model**

| Model | Caught |
|---|---|
| decision_tree | 7/12 (58%) [0.31, 0.82] |
| gaussian_nb | 11/12 (92%) [0.67, 0.99] |
| gradient_boosting | 8/11 (73%) [0.43, 0.92] |
| knn | 5/6 (83%) [0.44, 0.98] |
| logistic_regression | 7/8 (88%) [0.55, 0.99] |
| random_forest | 4/5 (80%) [0.37, 0.98] |
| svm | 4/6 (67%) [0.29, 0.92] |

**1b. The missed canaries: class, tier, dataset, metric**

| Missed | Runs |
|---|---|
| B02 subtle on breast_cancer, balanced_accuracy | 1 |
| B04 subtle on diabetes, f1 | 1 |
| B05 subtle on pc1, f1 | 1 |
| B06 obvious on ozone-level-8hr, roc_auc | 1 |
| B06 obvious on pc1, f1 | 2 |
| B06 subtle on diabetes, f1 | 1 |
| B06 subtle on pc1, f1 | 2 |
| B09 obvious on credit-g, accuracy | 1 |
| B09 obvious on diabetes, balanced_accuracy | 1 |
| B09 subtle on credit-g, balanced_accuracy | 1 |
| B09 subtle on pc1, f1 | 2 |

**1c. Caught, but another class named**

| Planted, named | Runs |
|---|---|
| B10 named B01 | 5 |
| B10 named B03 | 1 |

**2. Specificity (passed / clean runs)**

| Group | Passed |
|---|---|
| all clean runs | 60/60 (100%) [0.96, 1.00] |
| type: control | 30/30 (100%) [0.92, 1.00] |
| type: sham | 30/30 (100%) [0.92, 1.00] |
| clean runs carrying a decoy | 60/60 (100%) [0.96, 1.00] |
| clean runs without a decoy | 0/0 |
| decoy tier: obvious | 30/30 (100%) [0.92, 1.00] |
| decoy tier: subtle | 30/30 (100%) [0.92, 1.00] |
| control obvious decoy | 15/15 (100%) [0.85, 1.00] |
| control subtle decoy | 15/15 (100%) [0.85, 1.00] |
| sham obvious decoy | 15/15 (100%) [0.85, 1.00] |
| sham subtle decoy | 15/15 (100%) [0.85, 1.00] |
| decoy of class B01 | 6/6 (100%) [0.67, 1.00] |
| decoy of class B02 | 6/6 (100%) [0.67, 1.00] |
| decoy of class B03 | 6/6 (100%) [0.67, 1.00] |
| decoy of class B04 | 6/6 (100%) [0.67, 1.00] |
| decoy of class B05 | 6/6 (100%) [0.67, 1.00] |
| decoy of class B06 | 6/6 (100%) [0.67, 1.00] |
| decoy of class B07 | 6/6 (100%) [0.67, 1.00] |
| decoy of class B08 | 6/6 (100%) [0.67, 1.00] |
| decoy of class B09 | 6/6 (100%) [0.67, 1.00] |
| decoy of class B10 | 6/6 (100%) [0.67, 1.00] |

**3. Repeat pass (same prompt asked again, days later)**

| Measure | Value |
|---|---|
| runs asked again | 20 (14 buggy, 6 clean) |
| same verdict | 19/20 (95%) [0.79, 0.99] |
| same bug class (a pass names none) | 18/20 (90%) [0.72, 0.98] |
| same bug class, runs flagged both times | 11/12 (92%) [0.67, 0.99] |
| wording differs (not a disagreement) | 16/20 |
| fields that changed | bug_class 2, confidence 6, evidence 16, verdict 1 |
| verdict changes | buggy run: pass then flag (1) |

**4a. SIDE COMPARISON, same runs: task-dev-2. the same 40 padded runs with decoys; the prompts differ (cloud: baseline, llama: checklist with a line check)**

| Reviewer | Model | Flagged buggy | Flagged clean | J | Verdict AUC |
|---|---|---|---|---|---|
| skeptic_d | openai/gpt-oss-120b | 17/20 (85%) [0.65, 0.96] | 0/20 (0%) [0.00, 0.12] | +0.850 | 0.925 |
| skeptic_c_checklist | llama3.1:8b | 0/20 (0%) [0.00, 0.12] | 0/20 (0%) [0.00, 0.12] | +0.000 | 0.500 |

**4b. SIDE COMPARISON, other runs (context only): task-dev-1. 40 different runs, no padding and no decoys, baseline prompt; the cloud model never saw them, so this is context only**

| Reviewer | Model | Flagged buggy | Flagged clean | J | Verdict AUC |
|---|---|---|---|---|---|
| skeptic_a | gemma3:4b | 20/20 (100%) [0.88, 1.00] | 20/20 (100%) [0.88, 1.00] | +0.000 | 0.500 |
| skeptic_b | phi4-mini:latest | 19/20 (95%) [0.79, 0.99] | 17/20 (85%) [0.65, 0.96] | +0.100 | 0.550 |
| skeptic_c | llama3.1:8b | 20/20 (100%) [0.88, 1.00] | 20/20 (100%) [0.88, 1.00] | +0.000 | 0.500 |

From the locked arm file (secondary): cloud verdict AUC minus skeptic_c_checklist's P(flag) AUC on the same 40 runs = +0.283 [+0.080, +0.505] (97.5%, base-level bootstrap).
