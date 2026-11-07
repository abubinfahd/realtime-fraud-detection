# Azure Machine Learning Deployment Guide (Cloud-Native Data, Training & MLOps)

এই গাইডে আমাদের সম্পূর্ণ রিয়েল-টাইম ফ্রড ডিটেকশন সিস্টেম **Azure Machine Learning (Azure ML)**-এ সম্পূর্ণ **ক্লাউড-নেটিভ (Cloud-Native)** আর্কিটেকচারে পরিচালনা করার পূর্ণাঙ্গ গাইড দেওয়া হলো।

> [!IMPORTANT]
> **ব্যবহারকারীর মূল নীতিসমূহ (Core Design Principles):**
> 1. **Git-এ কোনো ডেটাসেট থাকবে না:** বড় ডেটাসেট বা ট্রানজ্যাকশন CSV কখনোই গিটহাবে পুশ হবে না। গিট রিপোজিটরি সম্পূর্ণ হালকা এবং ক্লিন থাকবে।
> 2. **ডেটাসেট সরাসরি Azure Cloud-এ আপলোড হবে:** ডেটাসেট একবার সরাসরি Azure ML Data Asset (Azure Blob Storage `workspaceblobstore`)-এ আপলোড হবে।
> 3. **ক্লাউডেই কোডবেসের সাথে Azure Data Asset কানেক্ট করে ট্রেইন হবে:** Azure ML Compute Instance-এ কোডবেস ক্লাউডের Data Asset থেকে ডেটা রিড করে সম্পূর্ণ মডেল ট্রেইনিং সম্পন্ন করবে।
> 4. **মডেল ক্লাউড থেকেই সরাসরি Model Registry-তে রেজিস্টার হবে (লোকাল পিসি ছাড়া):** ট্রেইন হওয়া মডেল `fraud_model.joblib` লোকাল পিসিতে ডাউনলোড বা লোকাল পিসি থেকে আপলোড করার কোনো দরকার নেই। ক্লাউড টার্মিনাল বা Studio UI দিয়ে সরাসরি ক্লাউড স্টোরেজ থেকেই Azure Model Registry-তে রেজিস্টার হবে!
> 5. **Git Push-এ কোনো ক্লাউড বিল আসবে না:** `git push origin master` করলে কেবল GitHub Actions-এ CI (Linter, Unit Tests) চলবে। Azure-এ কোনো রিসোর্স তৈরি বা স্বয়ংক্রিয় বিল হবে না। বাকি সমস্ত কাজ আপনি Azure ML Studio UI এবং ক্লাউড টার্মিনালে নিজের সুবিধামতো ধাপে ধাপে করবেন।

---

## 🏛️ ক্লাউড-নেটিভ আর্কিটেকচার ফ্লো

```
┌─────────────────────────────────┐
│        Local PC (Developer)     │
│   (Only Python Code & Configs)  │
└────────────────┬────────────────┘
                 │ git push (No dataset!)
                 ▼
┌────────────────────────────────────────────────────────┐
│                   GitHub Repository                    │
│   • CI Pipeline (Ruff + Mypy + Pytest) auto-runs       │
│   • Zero Cloud Resources Created (Zero Cost)           │
└────────────────────────────────────────────────────────┘

                 ┌───────────────────────────────────────┐
                 │    Dataset CSV (Local PC or GCS/S3)   │
                 └──────────────────┬────────────────────┘
                                    │ Direct Upload (One-time)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       Azure ML Studio (East US)                        │
│                                                                        │
│  [Step 1: Data Asset]                                                  │
│  • fraud_transactions_data_fahd40 (Stored in workspaceblobstore)       │
│                                                                        │
│  [Step 2: Compute Instance (ci-dev-fahd40)]                            │
│  • git clone codebase (clean, lightweight)                             │
│  • Connect Data Asset ➔ python -m fraud_detection.ml.train            │
│  • Output saved directly to: artifacts/fraud_model.joblib              │
│                                                                        │
│  [Step 3: Direct In-Cloud Model Registration]                          │
│  • python scripts/register_model.py (Run inside cloud terminal)        │
│    OR Studio UI: Models ➔ Register from Datastore                      │
│    (Zero bytes downloaded to local PC!)                                │
│                                                                        │
│  [Step 4: Custom Environment]                                          │
│  • fraud-inference-env-fahd40 (LightGBM + Scikit-Learn Docker)         │
│                                                                        │
│  [Step 5: Managed Online Endpoint & Deployment]                        │
│  • Endpoint: fraud-api-fahd40 (Unique East US Public URL)              │
│  • Deployment: blue-v1 (100% Live Traffic)                             │
│  • Sub-millisecond real-time scoring via Studio Test Tab               │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🏷️ ম্যান্ডেটরি ইউনিক নেমিং চার্ট (Unique Naming Convention)

Azure-এ গ্লোবালি পাবলিক DNS ও ক্লাউড নেইমিং সংঘর্ষ এড়াতে আপনার নির্ধারিত **ইউনিক নামসমূহ** নিচে দেওয়া হলো (সাফিক্স `fahd40` ব্যবহার করে):

| রিসোর্স টাইপ | নির্ধারিত ইউনিক নাম | কাজের বিবরণ |
| :--- | :--- | :--- |
| **Resource Group** | **`rg-fraud-mlops-fahd40`** | প্রজেক্টের সমস্ত ক্লাউড রিসোর্স একত্রিত রাখার পাত্র |
| **Workspace Name** | **`aml-fraud-workspace-fahd40`** | সেন্ট্রাল Azure MLOps হাব |
| **Data Asset Name** | **`fraud_transactions_data_fahd40`** | ক্লাউড ব্লব স্টোরেজে সংরক্ষিত ডেটাসেট |
| **Compute Instance** | **`ci-dev-fahd40`** | কোড রান ও মডেল ট্রেইনিংয়ের ক্লাউড ওয়ার্কস্টেশন |
| **Model Registry Name** | **`fraud_hybrid_model_fahd40`** | ক্লাউডে ভার্সন ট্র্যাকিং ও মডেল রেজিস্ট্রেশন |
| **Custom Environment** | **`fraud-inference-env-fahd40`** | LightGBM সহ কাস্টম ডকার/কনডা এনভায়রনমেন্ট |
| **Managed Online Endpoint** | **`fraud-api-fahd40`** | **গ্লোবালি ইউনিক পাবলিক DNS URL (East US)** |
| **Deployment Name** | **`blue-v1`** | জিরো-ডাউনটাইম ট্রাফিক স্লট (১০০% লাইভ ট্রাফিক) |

---

## 📂 রিপোজিটরির সংশ্লিষ্ট ফাইলসমূহ

| ফাইল | কাজের বিবরণ |
| :--- | :--- |
| [`.gitignore`](../.gitignore) | সব ধরনের CSV ডেটাসেট গিট থেকে বাদ রাখে (`data/raw/*`, `artifacts/*` ইগনোর করা) |
| [`src/fraud_detection/ml/train.py`](../src/fraud_detection/ml/train.py) | ক্লাউড ট্রেইনিং স্ক্রিপ্ট (যেকোনো কাস্টম `--data-path` সাপোর্ট করে) |
| [`scripts/register_model.py`](../scripts/register_model.py) | **ক্লাউড থেকেই সরাসরি মডেল রেজিস্ট্রেশন স্ক্রিপ্ট (নো লোকাল ডাউনলোড)** |
| [`artifacts/conda.yaml`](../artifacts/conda.yaml) | কন্টেইনার ডিপেনডেন্সি (`lightgbm`, `scikit-learn`, `joblib`, `azureml-inference-server-http`) |
| [`artifacts/score.py`](../artifacts/score.py) | রিয়েল-টাইম ইনফারেন্স স্ক্রিপ্ট (`init` মডেল লোড করে, `run` লাইভ প্রেডিকশন করে) |
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | `git push` করলে স্বয়ংক্রিয় CI রান করে (কোনো ক্লাউড খরচ নেই) |

---

# পর্ব ১: গিট পুশ ও CI টেস্ট (Zero Dataset in Git)

আপনার লোকাল পিসিতে কোড পরিবর্তন করার পর গিটহাবে পুশ করবেন:

১. লোকাল টার্মিনালে লিখুন:
   ```bash
   git add .
   git commit -m "feat: cloud-native training and in-azure registration"
   git push origin master
   ```
২. **নিশ্চিতকরণ:**
   - ডেটাসেট CSV ফাইলটি গিটহাবে আপলোড হবে না (`.gitignore` দ্বারা সুরক্ষিত)।
   - গিটহাবে আপনার রিপোজিটরির **`Actions`** ট্যাবে গেলে দেখতে পাবেন শুধুমাত্র **`CI Pipeline`** চলছে (Ruff, Mypy, Pytest)।
   - **Azure ক্লাউডে স্বয়ংক্রিয় কোনো কাজ চলবে না এবং কোনো অপ্রত্যাশিত বিল আসবে না!**

---

# পর্ব ২: Azure Portal-এ সাবস্ক্রিপশন ও প্রোভাইডার চেক

১. ব্রাউজারে [portal.azure.com](https://portal.azure.com)-এ গিয়ে সার্চ বারে লিখুন: **`Subscriptions`**।
২. আপনার সক্রিয় সাবস্ক্রিপশনে ক্লিক করুন ➔ বাম পাশের মেনুতে **Settings ➔ Resource providers**-এ যান।
৩. সার্চ করে নিচের ৩টি প্রোভাইডার চেক করে নিন যে স্ট্যাটাস **`Registered`** আছে কি না:
   - `Microsoft.MachineLearningServices`
   - `Microsoft.ContainerService` *(অনলাইন এন্ডপয়েন্টের জন্য বাধ্যতামূলক)*
   - `Microsoft.ContainerRegistry`
   *(কোনোটির পাশে `NotRegistered` থাকলে ক্লিক করে ওপরে **Register** চাপুন, ১ মিনিটে রেজিস্টার হয়ে যাবে)*।

---

# পর্ব ৩: Azure ML Workspace ও Compute Instance তৈরি

### ১. Workspace তৈরি করা
1. Azure Portal-এ সার্চ বারে লিখুন: **`Azure Machine Learning`** এবং ক্লিক করুন।
2. **`+ Create ➔ New workspace`**-এ ক্লিক করুন:
   - **Subscription:** আপনার সাবস্ক্রিপশন
   - **Resource group:** `Create new` ক্লিক করে লিখুন: **`rg-fraud-mlops-fahd40`**
   - **Workspace name:** লিখুন: **`aml-fraud-workspace-fahd40`**
   - **Region:** সিলেক্ট করুন: **`East US`**
   - বাকি অপশন ডিফল্ট রেখে নিচে **`Review + create ➔ Create`** বাটনে চাপ দিন (২ মিনিট সময় লাগবে)।
3. ডিপ্লয় হলে পেজের মাঝখানে নীল রঙের **`Launch studio`** বাটনে ক্লিক করুন (অথবা ব্রাউজারে [ml.azure.com](https://ml.azure.com)-এ যান)।

### ২. Compute Instance (ক্লাউড ওয়ার্কস্টেশন) তৈরি করা
1. **Azure ML Studio**-এর বাম পাশের মেনুতে **`Compute`** ট্যাবে যান।
2. **`Compute instances`** ট্যাবে ওপরে **`+ New`** চাপুন:
   - **Compute name:** লিখুন: **`ci-dev-fahd40`**
   - **Virtual machine type:** `CPU`
   - **Size:** `Standard_DS11_v2` বা `Standard_DS2_v3` (সাশ্রয়ী ২-কোর CPU)
   - 💰 **টাকা বাঁচানোর সোনালী নিয়ম:** `Enable idle shutdown`-এ টিক দিয়ে **`15 minutes`** দিন (কাজ শেষে ব্রাউজার কেটে দিলে ১৫ মিনিট পর মেশিন নিজে থেকেই বন্ধ হয়ে যাবে, কোনো ক্রেডিট অপচয় হবে না)।
3. নিচে **`Create`** চাপুন (২-৩ মিনিটে স্ট্যাটাস `Running` হয়ে যাবে)।

---

# পর্ব ৪: ডেটাসেট সরাসরি Azure-এ আপলোড করা (Data Asset)

*(এই ধাপে আপনার কম্পিউটার থেকে ডেটাসেটটি সরাসরি Azure Cloud-এ যাবে, গিটহাবে নয়)*

1. **Azure ML Studio**-এর বাম পাশের মেনুতে **Assets** সেকশনের নিচে **`Data`** ট্যাবে ক্লিক করুন।
2. ওপরে **`+ Create`** বাটনে ক্লিক করুন:
   - **Name:** লিখুন: **`fraud_transactions_data_fahd40`**
   - **Type:** সিলেক্ট করুন **`Table (mltable)`** অথবা **`File (uri_file)`** (CSV ফাইলের জন্য `File` বা `Table` উভয়ই প্রযোজ্য)।
   - **Description:** `Production fraud transaction dataset for model training`
   - **Next** চাপুন।
3. **Data source:** সিলেক্ট করুন **`From local files`** ➔ **Next** চাপুন।
4. **Destination datastore:** ডিফল্ট **`workspaceblobstore`** সিলেক্ট থাকবে ➔ **Next** চাপুন।
5. **File upload:** আপনার কম্পিউটারে থাকা ডেটাসেট CSV ফাইলটি (যেমন: `transactions_10k.csv` বা আপনার কাস্টম ডেটাসেট) ড্র্যাগ & ড্রপ করুন বা ব্রাউজ করে ধরিয়ে দিন ➔ **Next** চাপুন।
6. **Review + Create:** রিভিউ করে নিচে **`Create`** চাপুন।

✅ **ফলাফল:** ডেটাসেটটি এখন স্থায়ীভাবে আপনার Azure ক্লাউড স্টোরেজে (`workspaceblobstore`)-এ সংরক্ষিত হয়ে গেল। গিটহাবে এক বাইট ডেটাও যায়নি!

---

# পর্ব ৫: ক্লাউডে কোডবেস আনা, Data Asset কানেক্ট করা ও মডেল ট্রেইন

1. Azure ML Studio-র বাম পাশের মেনু থেকে **`Notebooks`**-এ যান।
2. ওপরের টুলবারে থাকা কালো রঙের **`Terminal`** আইকনে (`>_`) ক্লিক করে উবুন্টু ক্লাউড টার্মিনাল খুলুন।
3. টার্মিনালে নিচের কমান্ডগুলো দিয়ে আপনার লাইটওয়েট রিপোজিটরি ক্লোন ও কনডা এনভায়রনমেন্ট তৈরি করুন:
   ```bash
   # ১. গিট রিপোজিটরি ক্লোন (ডেটাসেট ছাড়া সম্পূর্ণ ক্লিন কোড)
   git clone https://github.com/abubinfahd/realtime-fraud-detection.git
   cd realtime-fraud-detection

   # ২. পাইথন ৩.১১ কনডা এনভায়রনমেন্ট তৈরি ও একটিভ
   conda create -y -n fraud_env -c conda-forge python=3.11
   conda activate fraud_env

   # ৩. প্রজেক্ট প্যাকেজ ইনস্টল
   pip install -e .
   ```

4. **Azure Data Asset থেকে ডেটা কানেক্ট করে ট্রেইনিং রান করা:**
   
   **বিকল্প ক (সরাসরি ডেটা পাথ বা আপলোড করা ফাইল দিয়ে):**
   ```bash
   python -m fraud_detection.ml.train --data-path data/raw/transactions_10k.csv
   ```
   *(যদি ডেটাসেট ফাইল না থাকে বা সিন্থেটিক ডেটা দিয়ে টেস্ট করতে চান, তাহলে কোনো আর্গুমেন্ট ছাড়া শুধু `python -m fraud_detection.ml.train` দিলেও সিস্টেম নিজে থেকেই হাই-ফিডেলিটি ১০,০০০ ট্রানজ্যাকশন তৈরি করে ট্রেইনিং সম্পন্ন করবে)*।

   **বিকল্প খ (Azure ML Data Asset SDK দিয়ে সরাসরি ডেটা রিড করা):**
   আপনি টার্মিনালে পাইথন ওয়ান-লাইনার দিয়ে Azure Data Asset-এর ক্লাউড পাথ দেখে নিতে পারেন:
   ```bash
   python -c "from azure.ai.ml import MLClient; from azure.identity import DefaultAzureCredential; ml = MLClient.from_config(DefaultAzureCredential()); data = ml.data.get('fraud_transactions_data_fahd40', version='1'); print('Data Asset Cloud URI:', data.path)"
   ```

5. **ট্রেইনিং সম্পন্নের আউটপুট:**
   টার্মিনালে দেখতে পাবেন:
   ```text
   ======================================================================
   Stage 3: Offline ML Model Training & Serialization Pipeline
   ======================================================================
   [*] Loading transaction dataset...
   [*] Class imbalance ratio: 99.0:1. Setting scale_pos_weight=99.0
   [*] Training Supervised LightGBM classifier...
   [*] Training Unsupervised Isolation Forest (Anomaly Detector)...
   [*] PR-AUC: 0.9410 | ROC-AUC: 0.9850 | Optimal F1 Threshold: 0.4200
   [*] Serializing trained artifact to artifacts/fraud_model.joblib...
   [+] Artifact serialized successfully (850.4 KB).
   [*] CPU Inference Latency Benchmark: P95 = 0.85 ms (< 3.0 ms budget)
   ======================================================================
   ```
   ✅ ট্রেইন হওয়া সম্পূর্ণ মডেলটি ক্লাউড মেশিনের ভেতরের ডিস্কে **`artifacts/fraud_model.joblib`** ফাইলে সেভ হয়েছে।

---

# পর্ব ৬: ক্লাউড থেকেই সরাসরি Model Registry-তে মডেল রেজিস্টার (নো লোকাল পিসি!)

> [!TIP]
> **এখানে কোনো ফাইল আপনার লোকাল পিসিতে ডাউনলোড করতে হবে না!**  
> যেহেতু মডেলটি ইতোমধ্যে ক্লাউডের ভেতরেই সেভ হয়েছে, আমরা ক্লাউড টু ক্লাউড সরাসরি রেজিস্টার করব।

### পদ্ধতি ১: ক্লাউড টার্মিনালে ১টি মাত্র কমান্ড (সবচেয়ে দ্রুত ও সহজ ⚡)
আপনি যে টার্মিনালে ট্রেইন করেছেন, সেখানেই লিখুন:
```bash
python scripts/register_model.py --model-name fraud_hybrid_model_fahd40
```
**আউটপুট:**
```text
Connecting to Azure ML Workspace 'aml-fraud-workspace-fahd40'...
Registering model 'fraud_hybrid_model_fahd40' in Azure ML Model Registry...
=================================================================
  [+] SUCCESS: Model Registered in Azure ML Model Registry!
  Name:    fraud_hybrid_model_fahd40
  Version: 1
=================================================================
```
*(বিকল্পভাবে Azure CLI দিয়েও রেজিস্টার করতে পারেন:)*
```bash
az ml model create --name fraud_hybrid_model_fahd40 --version 1 --path artifacts/fraud_model.joblib --type custom_model
```

### পদ্ধতি ২: Azure ML Studio Web UI থেকে রেজিস্টার করা (UI পছন্দকারীদের জন্য)
যদি টার্মিনাল ছাড়া Studio ব্রাউজার ইন্টারফেস থেকে রেজিস্টার করতে চান:
1. Studio-র বাম পাশের মেনুতে **Assets ➔ `Models`** ট্যাবে যান।
2. ওপরে **`+ Register`** বাটনে ড্রপডাউনে ক্লিক করুন ➔ সিলেক্ট করুন **`From datastore`** (অথবা Job রান থাকলে `From job output`):
   - **Datastore:** সিলেক্ট করুন `workspaceblobstore`
   - **Path:** ব্রাউজ করে ক্লাউডে থাকা `artifacts/fraud_model.joblib` সিলেক্ট করুন।
   - **Model type:** `Custom model`
   - **Name:** আমাদের ইউনিক নাম দিন: **`fraud_hybrid_model_fahd40`**
   - **Version:** `1`
3. নিচে **`Register`** বাটনে চাপ দিন। মডেলটি সাথে সাথে রেজিস্ট্রিতে যুক্ত হয়ে যাবে!

---

# পর্ব ৭: Custom Environment তৈরি করা (Studio UI)

*(কারণ ডিফল্ট sklearn-এ LightGBM থাকে না, তাই আমাদের কাস্টম কনডা এনভায়রনমেন্ট লাগবে)*

1. Studio-র বাম পাশের মেনুতে **Assets ➔ `Environments`** ট্যাবে যান।
2. ওপরে **`+ Create`** বাটনে চাপ দিন:
   - **Name:** ইউনিক নাম দিন: **`fraud-inference-env-fahd40`**
   - **Environment type:** `Use existing docker image with conda file` (ডিফল্ট)।
   - **Base image:** ডিফল্ট যা আছে তাই থাকবে (`mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04:latest`)।
   - **Conda settings:** `Upload file` সিলেক্ট করে আপনার কম্পিউটারে বা ক্লাউড থেকে রিপোজিটরির **[`artifacts/conda.yaml`](file:///e:/CODE/SC/real-time-fraud-detection/artifacts/conda.yaml)** ফাইলটি সিলেক্ট করে দিন।
3. নিচে **`Next ➔ Create`** বাটনে ক্লিক করুন! (এনভায়রনমেন্টটি তৈরি হয়ে যাবে)।

---

# পর্ব ৮: Managed Online Endpoint তৈরি করা (Studio UI)

*(DNS সংঘর্ষ ও কনকারেন্সি এরর এড়াতে Endpoint আগে তৈরি করা সবচেয়ে নিরাপদ)*

1. Studio-র বাম পাশের মেনুতে **Assets ➔ `Endpoints`** ট্যাবে যান।
2. ওপরে থাকা **`+ Create`** বাটনে চাপ দিন:
   - **Endpoint name:** আপনার গ্লোবালি ইউনিক নাম দিন:  
     👉 **`fraud-api-fahd40`**
   - **Authentication type:** `Key`
3. নিচে **`Create`** চাপুন। (১০ সেকেন্ডে তৈরি হয়ে স্ট্যাটাস **`Succeeded`** দেখাবে)।

---

# পর্ব ৯: Deployment যোগ করা ও ট্রাফিক ১০০% করা (Studio UI)

1. আপনার তৈরি হওয়া **`fraud-api-fahd40`** এন্ডপয়েন্টের নামের ওপর ক্লিক করে ভেতরে প্রবেশ করুন।
2. ওপরে থাকা **`+ Add deployment`** বাটনে চাপ দিন:
   - **Deployment name:** লিখুন: **`blue-v1`**
   - **Model:** রেজিস্ট্রিতে থাকা মডেলটি সিলেক্ট করুন: `fraud_hybrid_model_fahd40:1`
   - **Scoring script:** রিপোজিটরির **[`artifacts/score.py`](file:///e:/CODE/SC/real-time-fraud-detection/artifacts/score.py)** ফাইলটি আপলোড করুন।
   - **Environment:** **Custom environments** ট্যাবে গিয়ে সিলেক্ট করুন **`fraud-inference-env-fahd40`**।
   - **Compute:** `Standard_DS2_v2` (বা `Standard_D2s_v3`), **Instance count:** `1`
   - **Traffic allocation:** `100%`
3. নিচে **`Create`** বাটনে ক্লিক করুন!  
   *(৫ থেকে ৭ মিনিট সময় নেবে ক্লাউড কন্টেইনার বুট হতে, এরপর স্ট্যাটাস **সবুজ টিক (Healthy)** দেখাবে)*।

---

# পর্ব ১০: লাইভ ব্রাউজার থেকে টেস্ট করা (Studio Test Tab)

১. এন্ডপয়েন্টের ভেতর থাকা **`Test`** ট্যাবে ক্লিক করুন।
২. ইনপুট এডিটর বক্সে নিচের টেস্ট ফ্রড ট্রানজ্যাকশনটি পেস্ট করুন:
   ```json
   {
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
         "high_risk_mcc": 1
       }
     ]
   }
   ```
৩. নিচে নীল রঙের **`Test`** বাটনে ক্লিক করুন!
৪. **প্রত্যাশিত আউটপুট:** সাথে সাথে সাব-মিলিসেকেন্ডে রেজাল্ট দেখতে পাবেন:
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

# পর্ব ১১: ক্লাউড ক্রেডিট সুরক্ষা ও খরচ নিয়ন্ত্রণ (Cost Management)

আপনার কাজ বা ডেমো প্রেজেন্টেশন শেষ হলে অপ্রয়োজনীয় ক্লাউড বিল বন্ধ রাখার ৩টি সহজ পদক্ষেপ:

১. **Compute Instance বন্ধ রাখা:**  
   Studio ➔ **`Compute`** ➔ `ci-dev-fahd40`-এর পাশে **`Stop`** বাটনে চাপ দিন (অথবা আমাদের দেওয়া ১৫ মিনিটের অটো-শাটডাউনে এটি নিজে থেকেই বন্ধ হয়ে যাবে)।
২. **অনলাইন এন্ডপয়েন্ট ডিলিট করা (প্রধান খরচ):**  
   Studio ➔ **`Endpoints`** ➔ `fraud-api-fahd40` সিলেক্ট করে ওপরে থাকা **`Delete`** বাটনে চাপ দিন। (এতে সার্ভারলেস কন্টেইনার ডিলিট হয়ে যাবে এবং প্রতি ঘণ্টার বিলিং সাথে সাথে শূন্য হয়ে যাবে)।
৩. **সব রিসোর্স গ্রুপ একবারে সম্পূর্ণ মুছে ফেলা (Cloud Shell):**  
   ```bash
   az group delete --name "rg-fraud-mlops-fahd40" --yes --no-wait
   ```
