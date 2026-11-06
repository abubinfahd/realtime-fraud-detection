# Azure Machine Learning Deployment Guide (Serverless Model Serving)

এই গাইডে হাইব্রিড ফ্রড মডেলটি (LightGBM + Isolation Forest) **Azure ML Managed Online Endpoint**-এ REST API হিসেবে ডেপ্লয় করার ধাপগুলো দেওয়া আছে। এখানে কোনো VM নিজে ম্যানেজ করতে হয় না।

```
fraud_model.joblib ──► Model Registry ──► Custom Environment ──► Online Endpoint ──► https://<name>.eastus.inference.ml.azure.com/score
```

> [!IMPORTANT]
> Azure for Students সাবস্ক্রিপশনে Managed Online Endpoint প্রায়ই ব্লক থাকে (`SubscriptionNotRegistered [N/A]`)। Free Trial / Pay-As-You-Go সাবস্ক্রিপশন ব্যবহার করুন।

---

## প্রয়োজনীয় ফাইল

| ফাইল | কাজ |
| :--- | :--- |
| `artifacts/fraud_model.joblib` | ট্রেইন করা মডেল বান্ডেল (gitignored — `python -m fraud_detection.ml.train` দিয়ে তৈরি করুন) |
| [`artifacts/score.py`](../artifacts/score.py) | `init()` মডেল লোড করে, `run()` প্রেডিকশন দেয় |
| [`artifacts/conda.yaml`](../artifacts/conda.yaml) | কন্টেইনারের ডিপেনডেন্সি (`lightgbm`, `scikit-learn`, `azureml-inference-server-http`) |
| [`infra/azureml/endpoint.yml`](../infra/azureml/endpoint.yml) | এন্ডপয়েন্ট কনফিগ (CLI v2) |
| [`infra/azureml/environment.yml`](../infra/azureml/environment.yml) | এনভায়রনমেন্ট কনফিগ (CLI v2) |
| [`infra/azureml/deployment.yml`](../infra/azureml/deployment.yml) | ডেপ্লয়মেন্ট কনফিগ — VM সাইজ, ইনস্ট্যান্স সংখ্যা (CLI v2) |
| [`scripts/deploy_azureml.py`](../scripts/deploy_azureml.py) | Python SDK v2 দিয়ে এক কমান্ডে পুরো ডেপ্লয়মেন্ট |
| [`.github/workflows/cd-azureml.yml`](../.github/workflows/cd-azureml.yml) | git push ➔ অটো ডেপ্লয় |
| [`prod-inf.py`](../prod-inf.py) | লাইভ এন্ডপয়েন্ট টেস্ট ক্লায়েন্ট |

---

## ধাপ ১: Resource Providers রেজিস্টার করা (একবারই)

Portal ➔ **Subscriptions** ➔ আপনার সাবস্ক্রিপশন ➔ **Settings ➔ Resource providers** ➔ নিচেরগুলো সার্চ করে **Register**:

- `Microsoft.MachineLearningServices`
- `Microsoft.ContainerService`
- `Microsoft.ContainerRegistry`
- `Microsoft.ContainerInstance`

---

## ধাপ ২: Workspace তৈরি

Portal ➔ **Azure Machine Learning** ➔ **+ Create ➔ New workspace**

| ফিল্ড | মান |
| :--- | :--- |
| Resource group | `rg-fraud-ml` |
| Workspace name | `aml-fraud-prod` |
| Region | `East US` |
| Storage / Key vault / App insights | ডিফল্ট |

**Review + create ➔ Create** ➔ **Launch studio** ([ml.azure.com](https://ml.azure.com))

---

## ধাপ ৩: মডেল তৈরি (লোকাল)

```powershell
uv run python -m fraud_detection.ml.train
# Output: artifacts/fraud_model.joblib
```

---

## ধাপ ৪ থেকে ৭: দুটি পদ্ধতি — যেকোনো একটি বেছে নিন

### পদ্ধতি A: Studio UI (শেখার জন্য ভালো)

**ধাপ ৪ — মডেল রেজিস্টার:**
Studio ➔ **Models ➔ + Register ➔ From local files**
- Model type: `Custom model`
- File: `artifacts/fraud_model.joblib`
- Name: `fraud_hybrid_model`, Version: `1`

**ধাপ ৫ — কাস্টম এনভায়রনমেন্ট:**
Studio ➔ **Environments ➔ + Create**
- Name: `fraud-inference-env`
- Source: `Use existing docker image with conda file`
- Image: `mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04:latest`
- Conda file: `artifacts/conda.yaml` আপলোড

> [!WARNING]
> কিউরেটেড `sklearn` এনভায়রনমেন্টে `lightgbm` নেই। ওটা ব্যবহার করলে কন্টেইনার `ModuleNotFoundError: No module named 'lightgbm'` দিয়ে ক্র্যাশ করবে।

**ধাপ ৬ — এন্ডপয়েন্ট তৈরি (আলাদাভাবে আগে):**
Studio ➔ **Endpoints ➔ + Create**
- Endpoint name: গ্লোবালি ইউনিক নাম, যেমন `fraud-live-fahd40`
- Auth: `Key`

**ধাপ ৭ — ডেপ্লয়মেন্ট যোগ:**
এন্ডপয়েন্ট ➔ **+ Add deployment**
- Deployment name: `real-time-fraud-v1`
- Model: `fraud_hybrid_model:1`
- Scoring script: `artifacts/score.py`
- Environment: **Custom** ➔ `fraud-inference-env`
- VM: `Standard_DS2_v2`, Instance count: `1`
- Traffic: `100%`

৫–৮ মিনিট পর deployment-এর পাশে সবুজ টিক দেখাবে।

---

### পদ্ধতি B: Python SDK — এক কমান্ড

```powershell
uv pip install azure-ai-ml azure-identity
az login

uv run python scripts/deploy_azureml.py `
  --subscription-id "<SUBSCRIPTION_ID>" `
  --resource-group "rg-fraud-ml" `
  --workspace-name "aml-fraud-prod" `
  --endpoint-name "fraud-live-fahd40"
```

স্ক্রিপ্টটি ক্রমানুসারে: মডেল রেজিস্টার ➔ এনভায়রনমেন্ট রেজিস্টার ➔ এন্ডপয়েন্ট তৈরি ➔ ডেপ্লয়মেন্ট ➔ ১০০% ট্রাফিক ➔ Scoring URI প্রিন্ট।

> [!NOTE]
> Azure ML Compute Instance-এর টার্মিনালে `az login` "security defaults"-এর কারণে ব্লক হতে পারে। তখন লোকাল পিসি বা Azure Cloud Shell থেকে চালান।

---

## ধাপ ৮: টেস্ট করা

**Studio থেকে:** এন্ডপয়েন্ট ➔ **Test** ট্যাব ➔ নিচের JSON দিয়ে **Test**:

```json
{
  "data": [
    {
      "amount": 4850.0, "hour_of_day": 3, "day_of_week": 6, "is_weekend": 1,
      "distance_from_home_km": 920.0, "velocity_1h": 11, "velocity_24h": 28,
      "avg_amount_24h": 40.0, "amount_to_avg_ratio": 121.25, "high_risk_mcc": 1
    }
  ]
}
```

**লোকাল পিসি থেকে:** **Consume** ট্যাব থেকে URL ও Primary key কপি করুন:

```powershell
$env:AZUREML_SCORING_URL = "https://fraud-live-fahd40.eastus.inference.ml.azure.com/score"
$env:AZUREML_API_KEY = "<PRIMARY_KEY>"
uv run python prod-inf.py
```

> [!CAUTION]
> API key কখনো কোডে হার্ডকোড করে GitHub-এ পুশ করবেন না। ভুলে পুশ হয়ে গেলে Consume ট্যাব থেকে key regenerate করুন।

---

## ধাপ ৯: CI/CD অটোমেশন (git push ➔ Azure ML)

### ৯.১ Service Principal তৈরি (Azure Cloud Shell)

```bash
az ad sp create-for-rbac \
  --name "sp-fraud-github-actions" \
  --role contributor \
  --scopes /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-fraud-ml \
  --sdk-auth
```

### ৯.২ GitHub Secrets ও Variable

Repository ➔ **Settings ➔ Secrets and variables ➔ Actions**

| ধরন | নাম | মান |
| :--- | :--- | :--- |
| Secret | `AZURE_CREDENTIALS` | উপরের কমান্ডের পুরো JSON আউটপুট |
| Secret | `AZURE_SUBSCRIPTION_ID` | সাবস্ক্রিপশন আইডি |
| Secret | `AZURE_RESOURCE_GROUP` | `rg-fraud-ml` |
| Secret | `AZURE_WORKSPACE_NAME` | `aml-fraud-prod` |
| Variable | `ENABLE_AZUREML_CD` | `true` |

### ৯.৩ পাইপলাইন ফ্লো

`artifacts/score.py`, `artifacts/conda.yaml`, `infra/azureml/**` বা `scripts/deploy_azureml.py` পরিবর্তন করে `git push origin master` করলে **`cd-azureml.yml`**:

1. Azure-এ Service Principal দিয়ে লগইন করে
2. মডেল না থাকলে ট্রেইন করে
3. `scripts/deploy_azureml.py` চালিয়ে নতুন ভার্সন রেজিস্টার ও এন্ডপয়েন্ট আপডেট করে

Actions ট্যাব থেকে **Run workflow** দিয়ে ম্যানুয়ালিও চালানো যায়।

---

## ট্রাবলশুটিং

| এরর | কারণ | সমাধান |
| :--- | :--- | :--- |
| `SubscriptionNotRegistered: Resource provider [N/A]` | প্রোভাইডার রেজিস্টার নেই বা Student সাবস্ক্রিপশন | ধাপ ১; Free Trial / PAYG সাবস্ক্রিপশন |
| `Specified endpoint [...] has not been created successfully` | নাম ইউনিক নয় বা আগের ফেইল্ড এন্ডপয়েন্ট আছে | ফেইল্ড এন্ডপয়েন্ট ডিলিট করে নতুন ইউনিক নাম; এন্ডপয়েন্ট আগে আলাদাভাবে তৈরি করুন |
| `User container has crashed` + `No module named 'lightgbm'` | কিউরেটেড এনভায়রনমেন্টে lightgbm নেই | `conda.yaml` দিয়ে কাস্টম এনভায়রনমেন্ট |
| `403 key_auth_bad_header_forbidden` | হেডারে key নেই বা `Bearer ` প্রিফিক্স নেই | `Authorization: Bearer <KEY>`; ব্রাউজারে সরাসরি URL খুলবেন না |
| `DefaultAzureCredential failed` | টার্মিনালে লগইন নেই | `az login` অথবা Studio UI ব্যবহার |
| `pip ... requires a different Python` | `pyproject.toml`-এ `>=3.12` ছিল | এখন `>=3.11` করা আছে |

---

## খরচ নিয়ন্ত্রণ

- `Standard_DS2_v2` × ১ ইনস্ট্যান্স ≈ দিনে \$২–৩
- কাজ শেষে: Studio ➔ **Endpoints** ➔ এন্ডপয়েন্ট ➔ **Delete** (মডেল ও এনভায়রনমেন্ট থেকে যায়, খরচ প্রায় শূন্য)
- সব মুছতে: `az group delete --name rg-fraud-ml --yes --no-wait`

