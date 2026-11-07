# Azure Machine Learning Deployment Guide (Serverless Model Serving & Cloud MLOps)

এই গাইডে হাইব্রিড ফ্রড মডেলটি (LightGBM + Isolation Forest) এবং পুরো প্রজেক্ট কোডবেস **Azure Machine Learning (Azure ML)**-এ চালানোর দুটি পদ্ধতি আলোচনা করা হয়েছে:

1. **পদ্ধতি ১ — লোকাল ট্রেইন করে সরাসরি মডেল রেজিস্ট্রি ও এন্ডপয়েন্ট ডেপ্লয়মেন্ট:** লোকাল পিসিতে ট্রেইন করা মডেলটি ক্লাউডে রেজিস্টার করে Managed Online Endpoint তৈরি করা।
2. **পদ্ধতি ২ — সম্পূর্ণ ক্লাউড-নেটিভ এন্ড-টু-এন্ড MLOps পাইপলাইন (Git Push ➔ CI ➔ Cloud Train ➔ Register ➔ Endpoint):** সম্পূর্ণ কোডবেস গিটহাবে পুশ করার পর CI টেস্ট রান হবে, এরপর Azure ML Compute Cluster-এ স্বয়ংক্রিয়ভাবে মডেল ট্রেইন হবে, মডেল সেভ ও রেজিস্টার হবে, এবং লাইভ REST API তৈরি হয়ে টেস্ট হবে।

---

## প্রয়োজনীয় ফাইলসমূহ

| ফাইল | কাজের বিবরণ |
| :--- | :--- |
| [`artifacts/score.py`](../artifacts/score.py) | `init()` মডেল লোড করে, `run()` ইনকামিং ট্রানজ্যাকশন প্রেডিকশন করে |
| [`artifacts/conda.yaml`](../artifacts/conda.yaml) | কন্টেইনারের ডিপেনডেন্সি (`lightgbm`, `scikit-learn`, `joblib`, `azureml-inference-server-http`) |
| [`infra/azureml/endpoint.yml`](../infra/azureml/endpoint.yml) | ডিক্লেয়ারেটিভ Managed Online Endpoint স্পেসিফিকেশন (CLI v2) |
| [`infra/azureml/environment.yml`](../infra/azureml/environment.yml) | ডিক্লেয়ারেটিভ কাস্টম ইনফারেন্স এনভায়রনমেন্ট স্পেসিফিকেশন (CLI v2) |
| [`infra/azureml/deployment.yml`](../infra/azureml/deployment.yml) | ডিক্লেয়ারেটিভ ডেপ্লয়মেন্ট কনফিগ — VM সাইজ, ইনস্ট্যান্স সংখ্যা (CLI v2) |
| [`infra/azureml/train_job.yml`](../infra/azureml/train_job.yml) | Azure ML Compute Cluster-এ ক্লাউড ট্রেইনিং জব চালানোর কনফিগ (CLI v2) |
| [`scripts/run_azureml_pipeline.py`](../scripts/run_azureml_pipeline.py) | **সম্পূর্ণ এন্ড-টু-এন্ড অটোমেশন:** Compute Cluster ➔ Cloud Train ➔ Register ➔ Deploy ➔ Smoke Test |
| [`scripts/deploy_azureml.py`](../scripts/deploy_azureml.py) | বিদ্যমান লোকাল মডেল থেকে সরাসরি মডেল রেজিস্টার ও এন্ডপয়েন্ট ডেপ্লয় করার স্ক্রিপ্ট |
| [`.github/workflows/cd-azureml.yml`](../.github/workflows/cd-azureml.yml) | `git push` বা ম্যানুয়াল ট্রিগারে CI টেস্ট + ক্লাউড ট্রেইনিং + ডেপ্লয়মেন্ট ওয়ার্কফ্লো |

---

# অংশ ১: প্রাথমিক ক্লাউড সেটআপ ও প্রোভাইডার ভেরিফিকেশন

### ধাপ ১: Resource Providers রেজিস্টার করা (একবারই করতে হয়)

Azure Portal ➔ **Subscriptions** ➔ আপনার সাবস্ক্রিপশন (Free Trial / Pay-As-You-Go) ➔ **Settings ➔ Resource providers** ➔ নিচেরগুলো সার্চ করে **Register** বাটনে ক্লিক করুন:

- `Microsoft.MachineLearningServices`
- `Microsoft.ContainerService` (ম্যানেজড এন্ডপয়েন্ট ও কন্টেইনারের জন্য বাধ্যতামূলক)
- `Microsoft.ContainerRegistry`
- `Microsoft.ContainerInstance`

> [!IMPORTANT]
> Azure for Students সাবস্ক্রিপশনে Managed Online Endpoint ব্যাকগ্রাউন্ডে পলিসি দ্বারা ব্লক থাকে (`SubscriptionNotRegistered [N/A]`)। নিরবচ্ছিন্ন ডেপ্লয়মেন্টের জন্য $200 ফ্রি ক্রেডিট সহ **Free Trial** বা **Pay-As-You-Go** সাবস্ক্রিপশন ব্যবহার করুন।

---

# অংশ ২: বেসিক ডেপ্লয়মেন্ট (লোকাল মডেল ➔ Model Registry ➔ Endpoint)

আপনার কাছে যদি আগে থেকেই লোকাল পিসিতে ট্রেইন করা `artifacts/fraud_model.joblib` ফাইল থাকে, তবে এই অংশটি অনুসরণ করুন।

### ধাপ ২.১: Workspace তৈরি করা
Portal ➔ **Azure Machine Learning** ➔ **+ Create ➔ New workspace**
- **Resource group:** `rg-fraud-ml`
- **Workspace name:** `aml-fraud-prod`
- **Region:** `East US`
- **Review + create ➔ Create** ➔ **Launch studio** ([ml.azure.com](https://ml.azure.com))

### ধাপ ২.২: Model Registry-তে মডেল আপলোড (Studio UI)
1. Studio ➔ **Models ➔ + Register ➔ From local files**
2. Model type: `Custom model`, File: `artifacts/fraud_model.joblib`
3. Name: `fraud_hybrid_model`, Version: `1`

### ধাপ ২.৩: Custom Environment তৈরি করা
1. Studio ➔ **Environments ➔ + Create**
2. Name: `fraud-inference-env`
3. Source: `Use existing docker image with conda file`
4. Image: `mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04:latest`
5. Conda file: `artifacts/conda.yaml` ফাইলটি আপলোড করুন।

> [!WARNING]
> কিউরেটেড `sklearn` এনভায়রনমেন্টে `lightgbm` থাকে না। কাস্টম এনভায়রনমেন্ট ছাড়া ডেপ্লয় করলে কন্টেইনার `ModuleNotFoundError: No module named 'lightgbm'` দিয়ে ক্র্যাশ করবে।

### ধাপ ২.৪: Managed Online Endpoint তৈরি ও ডেপ্লয়মেন্ট
1. Studio ➔ **Endpoints ➔ + Create**
   - Endpoint name: একটি ইউনিক নাম (যেমন: `fraud-live-fahd40`)
   - Auth: `Key` ➔ Create.
2. এন্ডপয়েন্টের ভেতর গিয়ে ➔ **+ Add deployment**
   - Deployment name: `real-time-fraud-v1`
   - Model: `fraud_hybrid_model:1`
   - Scoring script: `artifacts/score.py`
   - Environment: **Custom** ➔ `fraud-inference-env`
   - Compute: `Standard_DS2_v2`, Instance count: `1`, Traffic: `100%`

---

# অংশ ৩: সম্পূর্ণ ক্লাউড-নেটিভ এন্ড-টু-এন্ড MLOps পাইপলাইন (Git Push ➔ CI ➔ Cloud Train ➔ Register ➔ Endpoint)

এই পদ্ধতিতে আপনার লোকাল পিসিতে মডেল ট্রেইন করার কোনো প্রয়োজন নেই। সম্পূর্ণ কোডবেস গিটহাবে পুশ করবেন, GitHub Actions কোড টেস্ট করবে, তারপর Azure ML স্বয়ংক্রিয়ভাবে ক্লাউড ক্লাস্টারে পুরো কোডবেস রান করে মডেল ট্রেইন করবে, মেট্রিক্স ট্র্যাক করবে, মডেল রেজিস্টার করবে এবং লাইভ REST API ডেপ্লয় করবে।

```
  [ Developer ]
       │ git push origin master
       ▼
  [ GitHub Actions CI ] ──► Pytest + Ruff Lint
       │ Tests Passed
       ▼
  [ Azure ML Cloud Cluster ] ──► pip install -e . && python -m fraud_detection.ml.train
       │ Model Training & Metrics Logged to MLflow (AUC-ROC, F1)
       ▼
  [ Azure ML Model Registry ] ──► fraud_hybrid_model_<unique-suffix>:v1
       │ Automatic Promotion
       ▼
  [ Managed Online Endpoint ] ──► https://fraud-api-<unique-suffix>.eastus.inference.ml.azure.com/score
       │ Zero-Downtime Rollout (100% Traffic)
       ▼
  [ Automated Smoke Test ] ──► Live JSON Verification (APPROVED / REJECTED)
```

---

## ৩.১ ম্যান্ডেটরি ইউনিক নেমিং নিয়মাবলী (Mandatory Unique Naming Convention)

Azure-এ কাজ করার সময় সবচেয়ে সাধারণ এরর হলো নামের সংঘর্ষ (Name Collision):
1. **Endpoint Name Collision:** Azure ML Managed Online Endpoint-এর একটি পাবলিক DNS URL থাকে (`https://<endpoint_name>.eastus.inference.ml.azure.com/score`)। এই নামটি সমগ্র বিশ্বের সকল Azure গ্রাহকের জন্য গ্লোবালি ইউনিক হতে হয়। জেনেরিক নাম (যেমন `fraud-api` বা `fraud-prod`) দিলে DNS সংঘর্ষের কারণে `400 BadRequest: ValidationFailure` এরর আসে।
2. **Workspace & Compute Collision:** আপনার সাবস্ক্রিপশনে একাধিক প্রজেক্ট আলাদা রাখতে রিসোর্স গ্রুপ ও ওয়ার্কস্পেস নাম ইউনিক রাখা জরুরি।

### ইউনিক নেমিং ফর্মুলা:
আপনার নাম বা আইডির ওপর ভিত্তি করে একটি **ইউনিক সাফিক্স** ঠিক করুন: `<UNIQUE_SUFFIX>` (যেমন: `fahd40` বা আপনার ইনিশিয়াল ও বছর `abf26`)।

নিচের টেবিলে সবগুলো রিসোর্সের ইউনিক নাম দেওয়া হলো:

| রিসোর্স টাইপ | নেমিং ফর্মুলা | উদাহরণ (`fahd40` দিয়ে) | কেন ইউনিক হওয়া বাধ্যতামূলক? |
| :--- | :--- | :--- | :--- |
| **Resource Group** | `rg-fraud-mlops-<UNIQUE_SUFFIX>` | `rg-fraud-mlops-fahd40` | সাবস্ক্রিপশনে প্রজেক্ট রিসোর্স আলাদা রাখার জন্য |
| **Workspace Name** | `aml-fraud-workspace-<UNIQUE_SUFFIX>` | `aml-fraud-workspace-fahd40` | সেন্ট্রাল MLOps হাব আইডেন্টিফিকেশন |
| **Compute Cluster** | `cc-cpu-<UNIQUE_SUFFIX>` | `cc-cpu-fahd40` | অটো-স্কেলিং ক্লাউড ট্রেইনিং ক্লাস্টার |
| **Model Registry Name** | `fraud_hybrid_model_<UNIQUE_SUFFIX>` | `fraud_hybrid_model_fahd40` | মডেল ভার্সনিং ও ট্র্যাকিং |
| **Custom Environment** | `fraud-inference-env-<UNIQUE_SUFFIX>` | `fraud-inference-env-fahd40` | LightGBM সহ কাস্টম ডকার/কনডা এনভায়রনমেন্ট |
| **Online Endpoint** | `fraud-api-<UNIQUE_SUFFIX>` | `fraud-api-fahd40` | **গ্লোবালি ইউনিক পাবলিক DNS URL (East US)** |
| **Deployment Slot** | `blue-v1` | `blue-v1` | জিরো-ডাউনটাইম ট্রাফিক স্লট |
| **Experiment Name** | `fraud-cloud-training-<UNIQUE_SUFFIX>` | `fraud-cloud-training-fahd40` | MLflow ট্রেইনিং রান মেট্রিক্স গ্রুপ |

---

## ৩.২ ধাপ ১: ইউনিক Workspace ও Resource Group তৈরি

Azure Portal অথবা Azure Cloud Shell-এ নিচের কমান্ড চালিয়ে ইউনিক ওয়ার্কস্পেস তৈরি করুন:

```bash
# Set your unique suffix
UNIQUE_SUFFIX="fahd40"
LOCATION="eastus"

# 1. Create Unique Resource Group
az group create \
  --name "rg-fraud-mlops-${UNIQUE_SUFFIX}" \
  --location "${LOCATION}"

# 2. Create Unique Azure ML Workspace
az ml workspace create \
  --name "aml-fraud-workspace-${UNIQUE_SUFFIX}" \
  --resource-group "rg-fraud-mlops-${UNIQUE_SUFFIX}" \
  --location "${LOCATION}"
```

---

## ৩.৩ ধাপ ২: ক্লাউড ট্রেইনিং ক্লাস্টার তৈরি (Compute Cluster)

Azure ML Compute Cluster হলো একটি ক্লাউড VM পুল যা ট্রেইনিং চলার সময় চালু হয় এবং কাজ শেষ হলে স্বয়ংক্রিয়ভাবে ০ নোডে নেমে যায় (ফলে অলস বসে থাকার জন্য কোনো বিল কাটে না):

```bash
az ml compute create \
  --name "cc-cpu-${UNIQUE_SUFFIX}" \
  --resource-group "rg-fraud-mlops-${UNIQUE_SUFFIX}" \
  --workspace-name "aml-fraud-workspace-${UNIQUE_SUFFIX}" \
  --type amlcompute \
  --size Standard_DS2_v2 \
  --min-instances 0 \
  --max-instances 2 \
  --idle-time-before-scale-down 120
```

---

## ৩.৪ ধাপ ৩: Azure ML-এ সম্পূর্ণ কোডবেস ক্লাউড ট্রেইনিংয়ে পাঠানো

আমাদের রিপোজিটরির পুরো কোডবেস (`src/fraud_detection`, `pyproject.toml`, ডাটা লোডার) ক্লাউড ক্লাস্টারে এক্সিকিউট করার জন্য [`infra/azureml/train_job.yml`](../infra/azureml/train_job.yml) ফাইলটি প্রস্তুত রয়েছে:

```yaml
# infra/azureml/train_job.yml
$schema: https://azuremlschemas.azureedge.net/latest/commandJob.schema.json
experiment_name: fraud-cloud-training-fahd40
display_name: hybrid-fraud-model-train
code: ../../
command: >-
  pip install -e . &&
  python -m fraud_detection.ml.train
environment: azureml:AzureML-sklearn-1.5-ubuntu20.04-py38-cpu@latest
compute: azureml:cc-cpu-fahd40
```

জবটি ক্লাউডে রান করতে কমান্ড দিন:
```bash
az ml job create \
  --file infra/azureml/train_job.yml \
  --resource-group "rg-fraud-mlops-${UNIQUE_SUFFIX}" \
  --workspace-name "aml-fraud-workspace-${UNIQUE_SUFFIX}" \
  --stream
```

### স্টুডিও UI-তে যা দেখতে পাবেন:
Azure ML Studio ([ml.azure.com](https://ml.azure.com)) ➔ **Jobs** মেনুতে গেলে দেখতে পাবেন:
- ক্লাউড ক্লাস্টার নোড প্রভিশন করছে
- লাইভ কনসোলে ১০,০০০ ট্রানজ্যাকশন জেনারেট হচ্ছে
- LightGBM এবং Isolation Forest মডেল ফিট হচ্ছে
- **MLflow** স্বয়ংক্রিয়ভাবে PR-AUC, ROC-AUC, F1-Score এবং Confusion Matrix চার্ট লাইভ লগ করছে!

---

## ৩.৫ ধাপ ৪: ক্লাউড জব আউটপুট থেকে মডেল রেজিস্টার করা

ট্রেইনিং সফল হলে আউটপুট মডেল ফাইলটি সরাসরি ক্লাউড Model Registry-তে যুক্ত করুন:

```bash
az ml model create \
  --name "fraud_hybrid_model_${UNIQUE_SUFFIX}" \
  --path "artifacts/fraud_model.joblib" \
  --type custom_model \
  --resource-group "rg-fraud-mlops-${UNIQUE_SUFFIX}" \
  --workspace-name "aml-fraud-workspace-${UNIQUE_SUFFIX}"
```

---

## ৩.৬ ধাপ ৫: Managed Online Endpoint ও কাস্টম ডিপ্লয়মেন্ট

১. **ইউনিক এন্ডপয়েন্ট তৈরি:**
   ```bash
   az ml online-endpoint create \
     --name "fraud-api-${UNIQUE_SUFFIX}" \
     --auth-mode key \
     --resource-group "rg-fraud-mlops-${UNIQUE_SUFFIX}" \
     --workspace-name "aml-fraud-workspace-${UNIQUE_SUFFIX}"
   ```

২. **কাস্টম এনভায়রনমেন্ট রেজিস্টার:**
   ```bash
   az ml environment create \
     --file infra/azureml/environment.yml \
     --resource-group "rg-fraud-mlops-${UNIQUE_SUFFIX}" \
     --workspace-name "aml-fraud-workspace-${UNIQUE_SUFFIX}"
   ```

৩. **মডেল ডেপ্লয় ও ১০০% ট্রাফিক রাউটিং:**
   ```bash
   az ml online-deployment create \
     --file infra/azureml/deployment.yml \
     --all-traffic \
     --resource-group "rg-fraud-mlops-${UNIQUE_SUFFIX}" \
     --workspace-name "aml-fraud-workspace-${UNIQUE_SUFFIX}"
   ```

---

## ৩.৭ ধাপ ৬: Python SDK v2 দিয়ে এক স্ক্রিপ্টে পুরো পাইপলাইন চালানো

উপরের সমস্ত স্টেপ (Compute ➔ Cloud Train ➔ Register ➔ Endpoint Deploy ➔ Live Test) ম্যানুয়ালি না চালিয়ে এক ক্লিকে সম্পন্ন করার জন্য আমাদের প্রজেক্টে রয়েছে [`scripts/run_azureml_pipeline.py`](../scripts/run_azureml_pipeline.py):

```powershell
uv pip install azure-ai-ml azure-identity joblib lightgbm scikit-learn numpy
az login

uv run python scripts/run_azureml_pipeline.py `
  --unique-suffix "fahd40" `
  --subscription-id "<YOUR_SUBSCRIPTION_ID>" `
  --resource-group "rg-fraud-mlops-fahd40" `
  --workspace-name "aml-fraud-workspace-fahd40"
```

এই স্ক্রিপ্টটি একা একাই:
1. ক্লাস্টার চেক বা তৈরি করবে (`cc-cpu-fahd40`)
2. সম্পূর্ণ কোডবেস ক্লাউডে সাবমিট করে ট্রেইন করবে
3. মডেলটি Model Registry-তে `fraud_hybrid_model_fahd40:1` হিসেবে সেভ করবে
4. `fraud-inference-env-fahd40` তৈরি করবে
5. `fraud-api-fahd40` এন্ডপয়েন্টে ডেপ্লয় করে ১০০% ট্রাফিক দেবে
6. স্বয়ংক্রিয়ভাবে একটি লাইভ HTTP POST টেস্ট ট্রানজ্যাকশন পাঠিয়ে কনসোলে প্রেডিকশন আউটপুট প্রিন্ট করে ভেরিফাই করবে!

---

## ৩.৮ ধাপ ৭: GitHub Actions CI/CD সম্পূর্ণ অটোমেশন (Git Push ➔ Cloud)

যখনই আপনি বা আপনার টিম কোডবেসে পরিবর্তন করে গিটহাবে পুশ করবেন, GitHub Actions স্বয়ংক্রিয়ভাবে পুরো পাইপলাইন এক্সিকিউট করবে।

### ১. GitHub Secrets কনফিগারেশন:
আপনার গিটহাব রিপোজিটরির **Settings ➔ Secrets and variables ➔ Actions**-এ নিচের সিক্রেটগুলো যোগ করুন:

| সিক্রেট নাম | কীভাবে পাবেন / মান |
| :--- | :--- |
| `AZURE_CREDENTIALS` | `az ad sp create-for-rbac --name "sp-fraud-fahd40" --role contributor --scopes /subscriptions/<SUB_ID>/resourceGroups/rg-fraud-mlops-fahd40 --sdk-auth` কমান্ডের পুরো JSON আউটপুট |
| `AZURE_SUBSCRIPTION_ID` | আপনার Azure সাবস্ক্রিপশন আইডি |
| `AZURE_RESOURCE_GROUP` | `rg-fraud-mlops-fahd40` |
| `AZURE_WORKSPACE_NAME` | `aml-fraud-workspace-fahd40` |

### ২. GitHub Repository Variable যোগ করুন:
**Settings ➔ Secrets and variables ➔ Actions ➔ Variables** ট্যাবে যান:
- `ENABLE_AZUREML_CD`: `true`
- `AZUREML_UNIQUE_SUFFIX`: `fahd40`

### ৩. গিট পুশ করে পাইপলাইন ট্রিগার করুন:
```bash
git add .
git commit -m "feat(mlops): update fraud detection rules and model pipeline"
git push origin master
```

### পাইপলাইন যেভাবে ধাপে ধাপে এক্সিকিউট হবে ([`.github/workflows/cd-azureml.yml`](../.github/workflows/cd-azureml.yml)):
1. **CI Step:** GitHub Actions রানারে `pytest` চলবে — সমস্ত ইউনিট টেস্ট এবং রুল ইঞ্জিন পাস হতে হবে।
2. **Auth Step:** Azure Service Principal দিয়ে ক্লাউডে নিরাপদ অথেনটিকেশন হবে।
3. **Cloud Train Step:** Azure ML ক্লাস্টারে (`cc-cpu-fahd40`) পুরো কোডবেস রান করে মডেল ট্রেইন হবে এবং MLflow মেট্রিক্স লগ হবে।
4. **Registry Step:** ট্রেইন হওয়া মডেলটি `fraud_hybrid_model_fahd40` হিসেবে সেন্ট্রাল রেজিস্ট্রিতে নতুন ভার্সন পাবে।
5. **Serving Step:** জিরো-ডাউনটাইমে `fraud-api-fahd40` এন্ডপয়েন্ট আপডেট হয়ে নতুন কন্টেইনারে ট্রাফিক সুইচ হবে।
6. **Smoke Test Step:** লাইভ এপিআই-তে টেস্ট ট্রানজ্যাকশন পাঠিয়ে নিশ্চিত করা হবে যে রেসপন্স কোড `200 OK` এবং ডিসিশন সঠিক এসেছে।

---

## ৩.৯ ধাপ ৮: লাইভ ক্লাউড এন্ডপয়েন্ট টেস্টিং

এন্ডপয়েন্ট লাইভ হওয়ার পর যেকোনো অ্যাপ্লিকেশন বা টার্মিনাল থেকে সরাসরি টেস্ট করা যায়:

```python
import json
import urllib.request

# Live Azure ML Scoring Endpoint URL
url = "https://fraud-api-fahd40.eastus.inference.ml.azure.com/score"
api_key = "<YOUR_PRIMARY_KEY>"  # Studio Consume tab থেকে সংগৃহীত

payload = {
    "data": [
        {
            "amount": 4850.0,
            "hour_of_day": 3,
            "day_of_week": 6,
            "is_weekend": 1,
            "distance_from_home_km": 920.0,
            "velocity_1h": 11,
            "velocity_24h": 28,
            "avg_amount_24h": 40.0,
            "amount_to_avg_ratio": 121.25,
            "high_risk_mcc": 1,
        }
    ]
}

req = urllib.request.Request(
    url,
    data=str.encode(json.dumps(payload)),
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    },
)

with urllib.request.urlopen(req) as resp:
    print(json.dumps(json.loads(resp.read().decode("utf-8")), indent=2))
```

**প্রত্যাশিত লাইভ আউটপুট:**
```json
{
  "predictions": [
    {
      "status": "REJECTED",
      "risk_score": 0.8924,
      "lightgbm_fraud_prob": 0.9412,
      "isolation_forest_anomaly": 0.8015,
      "thresholds": {
        "flagged": 0.4,
        "rejected": 0.75
      }
    }
  ]
}
```

---

# অংশ ৪: ট্রাবলশুটিং ও এরর গাইড

| এরর কোড | সম্ভাব্য কারণ | স্থায়ী সমাধান |
| :--- | :--- | :--- |
| `SubscriptionNotRegistered: Resource provider [N/A]` | নতুন সাবস্ক্রিপশনে `ContainerService` আনরেজিস্টার্ড অথবা Student সাবস্ক্রিপশন পলিসি ব্লক। | অংশ ১ অনুযায়ী প্রোভাইডার রেজিস্টার করুন; $200 ফ্রি ক্রেডিট সহ Free Trial ব্যবহার করুন। |
| `Specified endpoint [...] has not been created successfully` | এন্ডপয়েন্টের নাম গ্লোবালি ইউনিক নয় (DNS সংঘর্ষ) অথবা পুরোনো ফেইল্ড অবজেক্ট রয়ে গেছে। | অংশ ৩.১-এর ইউনিক নেমিং ফর্মুলা অনুসরণ করে ইউনিক সাফিক্স ব্যবহার করুন (যেমন: `fraud-api-fahd40`)। |
| `User container has crashed (ModuleNotFoundError: lightgbm)` | ডিফল্ট কিউরেটেড এনভায়রনমেন্টে LightGBM নেই। | `artifacts/conda.yaml` ব্যবহার করে কাস্টম এনভায়রনমেন্ট (`fraud-inference-env-<suffix>`) তৈরি করুন। |
| `403 Forbidden: key_auth_bad_header_forbidden` | ব্রাউজার অ্যাড্রেস বারে সরাসরি গেট রিকোয়েস্ট দেওয়া হয়েছে অথবা হেডারে `Bearer ` শব্দ বাদ পড়েছে। | HTTP POST রিকোয়েস্টের হেডারে `"Authorization": "Bearer <KEY>"` প্রদান করুন। |
| `ComputeClusterNotFound` | জবে উল্লিখিত নামের ক্লাউড ক্লাস্টার উপস্থিত নেই। | `scripts/run_azureml_pipeline.py` স্ক্রিপ্ট চালান যা নিজে থেকেই ক্লাস্টার তৈরি করে নেয়। |

---

# অংশ ৫: ক্লাউড ক্রেডিট সুরক্ষা ও ক্লিনআপ

প্র্যাকটিস বা ডেমো শেষ হওয়ার পর অপ্রয়োজনীয় ক্লাউড খরচ রোধ করার নিয়মাবলী:

1. **অটো-স্কেলিং ক্লাস্টার নিয়ে চিন্তা নেই:** আমাদের Compute Cluster-এ `min_instances=0` থাকায় কাজ শেষ হলে ১২০ সেকেন্ডের মধ্যে এটি ০ নোডে নেমে যায়, ফলে এর জন্য কোনো অতিরিক্ত বিল আসে না।
2. **এন্ডপয়েন্ট ডিলিট করা (প্রধান খরচ):** লাইভ Managed Online Endpoint সার্বক্ষণিক ১টি VM ধরে রাখে। ডেমো শেষে Studio ➔ **Endpoints** ➔ আপনার এন্ডপয়েন্ট সিলেক্ট করে ওপরে **`Delete`** বাটনে চাপ দিন।
3. **এক কমান্ডে সম্পূর্ণ প্রজেক্ট ডিলিট (Azure Cloud Shell):**
   ```bash
   az group delete --name "rg-fraud-mlops-fahd40" --yes --no-wait
   ```
