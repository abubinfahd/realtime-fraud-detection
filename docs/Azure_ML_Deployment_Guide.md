# Azure Machine Learning Deployment Guide (Studio UI & Cloud MLOps)

এই গাইডে আমাদের সম্পূর্ণ রিয়েল-টাইম ফ্রড ডিটেকশন কোডবেস **Azure Machine Learning (Azure ML)**-এ হাতে-কলমে (UI ভিত্তিক) চালানোর ধাপগুলো দেওয়া হলো।

> [!IMPORTANT]
> **সেফটি গ্যারান্টি:** `git push origin master` করলে ক্লাউডে কোনো ডেপ্লয়মেন্ট স্বয়ংক্রিয়ভাবে চলবে না এবং কোনো অপ্রত্যাশিত বিল আসবে না। পুশ করলে শুধুমাত্র GitHub-এর ভেতরেই **CI (Linter, Unit Tests)** চলবে। বাকি সমস্ত কাজ আপনি নিজে **Azure ML Studio UI**-তে ধাপে ধাপে নিজের সুবিধাজনক সময়ে করবেন।

---

## 🏷️ ম্যান্ডেটরি ইউনিক নেমিং চার্ট (Unique Naming Convention)

Azure-এ কাজ করার সময় সবচেয়ে বড় ভুল হলো জেনেরিক নাম দেওয়া। Managed Online Endpoint-এর পাবলিক DNS URL হলো `https://<endpoint_name>.eastus.inference.ml.azure.com/score` — যা সমগ্র বিশ্বে সকল Azure ইউজারের জন্য সম্পূর্ণ ইউনিক হতে হয়। কমন নাম দিলে সাথে সাথে `400 BadRequest: ValidationFailure` এরর আসে।

আপনার জন্য নির্ধারিত **ইউনিক নামসমূহ** নিচে দেওয়া হলো (সাফিক্স `fahd40` ব্যবহার করে):

| রিসোর্স টাইপ | নির্ধারিত ইউনিক নাম | কেন ইউনিক হওয়া বাধ্যতামূলক? |
| :--- | :--- | :--- |
| **Resource Group** | **`rg-fraud-mlops-fahd40`** | সাবস্ক্রিপশনে প্রজেক্টের সমস্ত ফাইল একত্রিত রাখার জন্য |
| **Workspace Name** | **`aml-fraud-workspace-fahd40`** | সেন্ট্রাল MLOps ক্লাউড হাব আইডেন্টিফিকেশন |
| **Compute Instance** | **`ci-dev-fahd40`** | ক্লাউডে কোডবেস চালানো ও জুপিটার ল্যাব ওয়ার্কস্টেশন |
| **Model Registry Name** | **`fraud_hybrid_model_fahd40`** | ক্লাউড মডেল রেজিস্ট্রিতে ভার্সনিং ও ট্র্যাকিং |
| **Custom Environment** | **`fraud-inference-env-fahd40`** | LightGBM সহ কাস্টম ডকার/কনডা এনভায়রনমেন্ট |
| **Managed Online Endpoint** | **`fraud-api-fahd40`** | **গ্লোবালি ইউনিক পাবলিক DNS URL (East US)** |
| **Deployment Name** | **`blue-v1`** | জিরো-ডাউনটাইম ট্রাফিক স্লট (১০০% লাইভ ট্রাফিক) |

---

## প্রয়োজনীয় লোকাল ফাইলসমূহ

| ফাইল | কাজের বিবরণ |
| :--- | :--- |
| [`artifacts/conda.yaml`](../artifacts/conda.yaml) | ক্লাউড কন্টেইনারের ডিপেনডেন্সি (`lightgbm`, `scikit-learn`, `joblib`, `azureml-inference-server-http`) |
| [`artifacts/score.py`](../artifacts/score.py) | ইনফারেন্স স্ক্রিপ্ট (`init` মডেল লোড করে, `run` লাইভ ট্রানজ্যাকশন প্রেডিকশন করে) |
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | `git push` করলে কোড কোয়ালিটি, ফরম্যাটিং ও Pytest রান করে |
| [`.github/workflows/cd-azureml.yml`](../.github/workflows/cd-azureml.yml) | ম্যানুয়াল ট্রিগারে ক্লাউড ট্রেইনিং ও ডেপ্লয়মেন্ট ওয়ার্কফ্লো (অটো-রান বন্ধ) |

---

# পর্ব ১: গিট পুশ ও CI টেস্ট (GitHub)

১. আপনার লোকাল কম্পিউটারে কোডে কোনো পরিবর্তন আনলে টার্মিনালে লিখুন:
   ```bash
   git add .
   git commit -m "update fraud detection logic"
   git push origin master
   ```
২. গিটহাবে আপনার রিপোজিটরির **`Actions`** ট্যাবে যান:
   - দেখতে পাবেন শুধু **`CI — Lint & Tests`** ওয়ার্কফ্লোটি রান হচ্ছে।
   - কোড কোয়ালিটি এবং Pytest পাস করলে সবুজ টিক (✅) দেখতে পাবেন।
   - **Azure ক্লাউডে কোনো রিসোর্স তৈরি হবে না এবং কোনো বিল কাটবে না!**

---

# পর্ব ২: Azure ML Studio UI-তে সম্পূর্ণ কোডবেস রান ও ডেপ্লয়মেন্ট (হাতে-কলমে)

এখন আমরা ব্রাউজার থেকে Azure ML Studio ([ml.azure.com](https://ml.azure.com))-এ ধাপে ধাপে পুরো সিস্টেমটি তৈরি করব:

```
[ধাপ ১: Subscriptions & Providers] ──► [ধাপ ২: Unique Workspace তৈরি] ──► [ধাপ ৩: Compute Instance]
                                                                                     │
[ধাপ ৬: Custom Environment] ◄── [ধাপ ৫: Model Register] ◄── [ধাপ ৪: ক্লাউডে কোডবেস ও মডেল ট্রেইন]
        │
        ▼
[ধাপ ৭: Unique Endpoint] ──► [ধাপ ৮: Deployment ও ১০০% ট্রাফিক] ──► [ধাপ ৯: লাইভ টেস্ট (Test Tab)]
```

---

### ধাপ ১: Subscriptions ও Resource Providers নিশ্চিত করা

1. ব্রাউজারে [portal.azure.com](https://portal.azure.com)-এ গিয়ে ওপরের সার্চ বারে লিখুন: **`Subscriptions`** এবং ক্লিক করুন।
2. আপনার $২০০ ক্রেডিটের সাবস্ক্রিপশনটিতে ক্লিক করুন।
3. বাম পাশের মেনুতে স্ক্রল করে **Settings ➔ Resource providers**-এ যান।
4. ফিল্টার বক্সে নিচের ৩টি প্রোভাইডার চেক করে নিন যে স্ট্যাটাস **`Registered`** আছে কি না:
   - `Microsoft.MachineLearningServices`
   - `Microsoft.ContainerService` *(অনলাইন এন্ডপয়েন্টের জন্য বাধ্যতামূলক)*
   - `Microsoft.ContainerRegistry`

*(কোনোটির পাশে `NotRegistered` থাকলে ক্লিক করে ওপরে **Register** চাপুন, ১ মিনিটে রেজিস্টার হয়ে যাবে)*।

---

### ধাপ ২: ইউনিক Workspace ও Resource Group তৈরি করা

1. Azure Portal-এর ওপরে সার্চ বারে লিখুন: **`Azure Machine Learning`** এবং ক্লিক করুন।
2. **`+ Create ➔ New workspace`**-এ ক্লিক করুন:
   - **Subscription:** আপনার $২০০ ক্রেডিটের সাবস্ক্রিপশন
   - **Resource group:** `Create new` ক্লিক করে লিখুন: **`rg-fraud-mlops-fahd40`**
   - **Workspace name:** লিখুন: **`aml-fraud-workspace-fahd40`**
   - **Region:** সিলেক্ট করুন: **`East US`**
   - **Storage account, Key vault, Application insights:** ডিফল্ট যা আছে তাই থাকবে।
   - **Container registry:** `(None)` থাকবে।
3. নিচে **`Review + create ➔ Create`** বাটনে চাপ দিন (২ মিনিট সময় নেবে)।
4. ডিপ্লয় হলে পেজের মাঝখানে নীল রঙের **`Launch studio`** বাটনে ক্লিক করুন (অথবা নতুন ট্যাবে [ml.azure.com](https://ml.azure.com)-এ প্রবেশ করুন)।

---

### ধাপ ৩: ক্লাউড ওয়ার্কস্টেশন তৈরি করা (Compute Instance)

1. **Azure ML Studio**-এর বাম পাশের মেনুতে **`Compute`** ট্যাবে যান।
2. **`Compute instances`** ট্যাবে থেকে ওপরে **`+ New`** বাটনে চাপ দিন:
   - **Compute name:** লিখুন: **`ci-dev-fahd40`**
   - **Virtual machine type:** `CPU`
   - **Size:** `Standard_DS11_v2` বা `Standard_DS2_v3` (সাশ্রয়ী ২-কোর CPU)
   - 💰 **টাকা বাঁচানোর সোনালী নিয়ম:** `Enable idle shutdown`-এ টিক দিয়ে **`15 minutes`** দিন (কাজ শেষে ব্রাউজার কেটে দিলে ১৫ মিনিট পর মেশিন নিজে থেকেই বন্ধ হয়ে যাবে, ফলে কোনো ক্রেডিট অপচয় হবে না)।
3. নিচে **`Create`** চাপুন (২-৩ মিনিটে স্ট্যাটাস `Running` হয়ে যাবে)।

---

### ধাপ ৪: ক্লাউডে কোডবেস আনা ও সম্পূর্ণ ট্রেইনিং রান করা

1. বাম পাশের মেনু থেকে **`Notebooks`**-এ যান।
2. ওপরের টুলবারে থাকা কালো রঙের **`Terminal`** আইকনে (`>_`) ক্লিক করে উবুন্টু ক্লাউড টার্মিনাল খুলুন।
3. টার্মিনালে নিচের কমান্ডগুলো দিয়ে আপনার রিপোজিটরি ক্লোন ও সেটআপ করুন:
   ```bash
   git clone https://github.com/abubinfahd/realtime-fraud-detection.git
   cd realtime-fraud-detection
   conda create -y -n fraud_env -c conda-forge python=3.11
   conda activate fraud_env
   pip install -e .
   ```
4. এবার পুরো কোডবেস ক্লাউড মেশিনে রান করে মডেল ট্রেইন করুন:
   ```bash
   python -m fraud_detection.ml.train
   ```
5. **ফলাফল:** লাইভ টার্মিনালে দেখতে পাবেন:
   - ১০,০০০ সিন্থেটিক ট্রানজ্যাকশন জেনারেট হচ্ছে
   - LightGBM (Supervised) এবং Fast Isolation Forest (Unsupervised) ট্রেইন হচ্ছে
   - PR-AUC, ROC-AUC ও সাব-মিলিসেকেন্ড ইনফারেন্স ল্যাটেন্সি প্রিন্ট হচ্ছে
   - এবং ট্রেইন হওয়া মডেলটি **`artifacts/fraud_model.joblib`** ফাইলে সেভ হয়েছে!

---

### ধাপ ৫: Model Registry-তে মডেল রেজিস্টার করা (Studio UI)

1. Studio-র বাম পাশের মেনুতে **Assets** সেকশনের নিচে **`Models`** ট্যাবে ক্লিক করুন।
2. ওপরে **`+ Register ➔ From local files`** সিলেক্ট করুন:
   - **Model type:** `Custom model`
   - **Browse file:** আপনার পিসির `artifacts/fraud_model.joblib` ফাইলটি ধরিয়ে দিন।
   - **Name:** আমাদের ইউনিক নাম দিন: **`fraud_hybrid_model_fahd40`**
   - **Version:** `1`
   - **Description:** `Hybrid Fraud Detection Model (LightGBM + Isolation Forest)`
3. নিচে **`Next ➔ Register`** বাটনে ক্লিক করুন! (মডেলটি ক্লাউড রেজিস্ট্রিতে সেভ হয়ে গেল)।

---

### ধাপ ৬: Custom Environment তৈরি করা (Studio UI)

*(কারণ ডিফল্ট sklearn-এ LightGBM থাকে না, তাই আমাদের কাস্টম কনডা লাগবে)*

1. Studio-র বাম পাশের মেনুতে **Assets ➔ `Environments`** ট্যাবে যান।
2. ওপরে **`+ Create`** বাটনে চাপ দিন:
   - **Name:** আমাদের ইউনিক নাম দিন: **`fraud-inference-env-fahd40`**
   - **Environment type:** `Use existing docker image with conda file` (ডিফল্ট)।
   - **Base image:** ডিফল্ট যা আছে তাই থাকবে (`mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04:latest`)।
   - **Conda settings:** `Upload file` সিলেক্ট করে আপনার পিসির **[`artifacts/conda.yaml`](file:///e:/CODE/SC/real-time-fraud-detection/artifacts/conda.yaml)** ফাইলটি সিলেক্ট করে দিন।
3. নিচে **`Next ➔ Create`** বাটনে ক্লিক করুন!

---

### ধাপ ৭: Managed Online Endpoint তৈরি করা (Studio UI)

*(মনে রাখবেন, DNS সংঘর্ষ এড়াতে Endpoint আগে তৈরি করা সবচেয়ে নিরাপদ)*

1. Studio-র বাম পাশের মেনুতে **Assets ➔ `Endpoints`** ট্যাবে যান।
2. ওপরে থাকা **`+ Create`** বাটনে চাপ দিন:
   - **Endpoint name:** আপনার গ্লোবালি ইউনিক নাম দিন:  
     👉 **`fraud-api-fahd40`**
   - **Authentication type:** `Key`
3. নিচে **`Create`** চাপুন। (১০ সেকেন্ডে তৈরি হয়ে স্ট্যাটাস **`Succeeded`** দেখাবে)।

---

### ধাপ ৮: Deployment যোগ করা ও ট্রাফিক ১০০% করা (Studio UI)

1. আপনার তৈরি হওয়া **`fraud-api-fahd40`** এন্ডপয়েন্টের নামের ওপর ক্লিক করে ভেতরে যান।
2. ওপরে থাকা **`+ Add deployment`** বাটনে চাপ দিন:
   - **Deployment name:** লিখুন: **`blue-v1`**
   - **Model:** সিলেক্ট করুন `fraud_hybrid_model_fahd40:1`
   - **Scoring script:** পিসির **[`artifacts/score.py`](file:///e:/CODE/SC/real-time-fraud-detection/artifacts/score.py)** ফাইলটি আপলোড করুন।
   - **Environment:** **Custom environments** ট্যাবে গিয়ে সিলেক্ট করুন **`fraud-inference-env-fahd40`**।
   - **Compute:** `Standard_DS2_v2` (বা `Standard_D2s_v3`), **Instance count:** `1`
   - **Traffic allocation:** `100%`
3. নিচে **`Create`** বাটনে ক্লিক করুন!  
   *(৫ থেকে ৭ মিনিট সময় নেবে কন্টেইনার বুট হতে, এরপর স্ট্যাটাস **সবুজ টিক (Healthy)** দেখাবে)*।

---

### ধাপ ৯: লাইভ ব্রাউজার থেকে টেস্ট করা (Test Tab)

1. এন্ডপয়েন্টের ভেতর থাকা **`Test`** ট্যাবে ক্লিক করুন।
2. ইনপুট এডিটর বক্সে নিচের টেস্ট ট্রানজ্যাকশনটি পেস্ট করুন:
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
3. নিচে নীল রঙের **`Test`** বাটনে ক্লিক করুন!
4. **প্রত্যাশিত আউটপুট:** সাথে সাথে দেখতে পাবেন:
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

# পর্ব ৩: ট্রাবলশুটিং ও এরর গাইড

| এরর কোড | আসল কারণ | সমাধান |
| :--- | :--- | :--- |
| `SubscriptionNotRegistered: Resource provider [N/A]` | নতুন সাবস্ক্রিপশনে `ContainerService` আনরেজিস্টার্ড অথবা Student সাবস্ক্রিপশন লিমিট। | ধাপ ১ অনুযায়ী প্রোভাইডার রেজিস্টার করুন; $২০০ ক্রেডিটের Free Trial ব্যবহার করুন। |
| `Specified endpoint [...] has not been created successfully` | এন্ডপয়েন্টের নাম গ্লোবালি ইউনিক নয় (DNS সংঘর্ষ) বা আগের ফেইল্ড অবজেক্ট রয়ে গেছে। | ইউনিক নাম দিন (যেমন: `fraud-api-fahd40`); এন্ডপয়েন্ট আগে আলাদাভাবে তৈরি করুন। |
| `User container has crashed (ModuleNotFoundError: lightgbm)` | ডিফল্ট কিউরেটেড এনভায়রনমেন্টে LightGBM নেই। | `artifacts/conda.yaml` ব্যবহার করে কাস্টম এনভায়রনমেন্ট (`fraud-inference-env-fahd40`) তৈরি করুন। |
| `403 Forbidden: key_auth_bad_header_forbidden` | ব্রাউজার অ্যাড্রেস বারে সরাসরি URL খোলা হয়েছে বা হেডারে `Bearer ` প্রিফিক্স নেই। | HTTP POST রিকোয়েস্টের হেডারে `"Authorization": "Bearer <KEY>"` ব্যবহার করুন। |

---

# পর্ব ৪: ক্লাউড ক্রেডিট সুরক্ষা ও রিসোর্স ক্লিনআপ (Cost Management)

আপনার প্র্যাকটিস বা ডেমো প্রেজেন্টেশন শেষ হলে অপ্রয়োজনীয় বিলিং বন্ধ রাখার সহজ নিয়ম:

1. **Compute Instance বন্ধ রাখা:**  
   Studio ➔ **`Compute`** ➔ `ci-dev-fahd40`-এর পাশে **`Stop`** বাটনে চাপ দিন (অথবা আমাদের দেওয়া ১৫ মিনিটের অটো-শাটডাউনে এটি নিজে থেকেই বন্ধ হয়ে যাবে)।
2. **এন্ডপয়েন্ট ডিলিট করা (প্রধান খরচ):**  
   Studio ➔ **`Endpoints`** ➔ `fraud-api-fahd40` সিলেক্ট করে ওপরে থাকা **`Delete`** বাটনে চাপ দিন। (এতে সার্ভারলেস কন্টেইনার ডিলিট হয়ে যাবে এবং প্রতি ঘণ্টার বিলিং সাথে সাথে শূন্য হয়ে যাবে)।
3. **সব রিসোর্স গ্রুপ একবারে সম্পূর্ণ মুছে ফেলা (Cloud Shell):**  
   ```bash
   az group delete --name "rg-fraud-mlops-fahd40" --yes --no-wait
   ```
