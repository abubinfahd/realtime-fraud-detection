# Azure VM Deployment Guide (Full-Stack Streaming)

এই গাইডে পুরো রিয়েল-টাইম ফ্রড ডিটেকশন স্ট্যাক (৬টি কন্টেইনার) একটি **Azure Linux VM**-এ ডেপ্লয় করার ধাপগুলো দেওয়া আছে।

```
git push ──► CI (ci.yml) ──► Docker Publish (GHCR) ──► CD (cd-azure.yml) ──► Azure VM (docker compose)
```

| কন্টেইনার | কাজ | পোর্ট |
| :--- | :--- | :--- |
| `fraud-kafka` | ইভেন্ট স্ট্রিমিং (KRaft) | ইন্টারনাল |
| `fraud-redis` | ফিচার স্টোর ও অ্যালার্ট ব্রোকার | ইন্টারনাল |
| `fraud-postgres` | অডিট ডাটাবেস | ইন্টারনাল |
| `fraud-producer` | সিন্থেটিক ট্রানজ্যাকশন জেনারেটর | — |
| `fraud-consumer` | হাইব্রিড ML + রুল ইঞ্জিন | — |
| `fraud-api` | FastAPI + লাইভ ড্যাশবোর্ড | `80`, `8000` |

---

## প্রয়োজনীয় ফাইল

| ফাইল | কাজ |
| :--- | :--- |
| [`docker-compose.prod.yml`](../docker-compose.prod.yml) | প্রোডাকশন ৬-কন্টেইনার স্ট্যাক |
| [`Dockerfile.api`, `Dockerfile.consumer`, `Dockerfile.producer`](../) | মাল্টি-স্টেজ ডকার ইমেজ |
| [`infra/azure/deploy_azure.sh`](../infra/azure/deploy_azure.sh) | CLI দিয়ে VM, VNet, NSG, Public IP তৈরি + `--hibernate`, `--start`, `--teardown` |
| [`infra/azure/cloud-init.txt`](../infra/azure/cloud-init.txt) | VM বুটের সময় Docker অটো-ইনস্টল |
| [`infra/azure/budget_alert.sh`](../infra/azure/budget_alert.sh) | বাজেট অ্যালার্ট সেটআপ |
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Lint + Test |
| [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml) | ইমেজ বিল্ড, Trivy স্ক্যান, GHCR-এ পুশ |
| [`.github/workflows/cd-azure.yml`](../.github/workflows/cd-azure.yml) | SSH দিয়ে VM-এ রোলআউট |

---

## ধাপ ১: Azure Portal থেকে VM তৈরি

1. [portal.azure.com](https://portal.azure.com) ➔ **Virtual machines** ➔ **+ Create ➔ Azure virtual machine**
2. **Basics ট্যাব:**
   - **Resource group:** `rg-fraud-streaming-prod` (Create new)
   - **VM name:** `vm-fraud-engine`
   - **Region:** `East US`
   - **Image:** `Ubuntu Server 24.04 LTS - x64 Gen2`
   - **Size:** `Standard_D2s_v3` (২ vCPU, ৮ GB RAM) — Kafka-র জন্য কমপক্ষে ৮ GB লাগবে
   - **Authentication:** `SSH public key`, **Username:** `azureuser`
   - **Key pair name:** `fraud-vm-key` (Generate new key pair)
   - **Inbound ports:** `SSH (22)`, `HTTP (80)`, `HTTPS (443)`
3. **Review + create ➔ Create** ➔ **Download private key and create resource** (`fraud-vm-key.pem` সেভ করুন)

> [!TIP]
> CLI দিয়ে একবারে করতে চাইলে Azure Cloud Shell-এ: `bash infra/azure/deploy_azure.sh`

---

## ধাপ ২: পোর্ট 8000 খোলা

VM ➔ **Networking ➔ Network settings ➔ + Create port rule ➔ Inbound port rule**

| ফিল্ড | মান |
| :--- | :--- |
| Destination port ranges | `8000` |
| Protocol | `TCP` |
| Action | `Allow` |
| Name | `Allow-FastAPI-8000` |

---

## ধাপ ৩: Windows থেকে SSH কানেকশন

```powershell
# Fix private key permissions (OpenSSH rejects keys readable by other users)
icacls "$HOME\Downloads\fraud-vm-key.pem" /reset
icacls "$HOME\Downloads\fraud-vm-key.pem" /inheritance:r /grant:r "$($env:USERNAME):R"

# Connect to the VM
ssh -i "$HOME\Downloads\fraud-vm-key.pem" azureuser@<VM_PUBLIC_IP>
```

---

## ধাপ ৪: VM-এ Docker ইনস্টল

```bash
# Install Docker Engine and Compose plugin
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow running docker without sudo (log out and back in afterwards)
sudo usermod -aG docker $USER
```

---

## ধাপ ৫: প্রজেক্ট রান করা

**অপশন A — সোর্স থেকে বিল্ড (প্রথমবারের জন্য সহজ):**

```bash
git clone https://github.com/abubinfahd/realtime-fraud-detection.git ~/app
cd ~/app
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

**অপশন B — GHCR থেকে প্রি-বিল্ট ইমেজ পুল (CD যেভাবে করে):**

```bash
cd ~/app
export IMAGE_TAG=latest
docker compose -f docker-compose.prod.yml pull producer consumer api
docker compose -f docker-compose.prod.yml up -d
```

> [!NOTE]
> GHCR প্যাকেজ প্রাইভেট হলে আগে লগইন করুন: `echo <GITHUB_PAT> | docker login ghcr.io -u abubinfahd --password-stdin`

---

## ধাপ ৬: যাচাই করা

| URL | কী দেখাবে |
| :--- | :--- |
| `http://<VM_PUBLIC_IP>:8000/dashboard/` | লাইভ ট্রানজ্যাকশন ড্যাশবোর্ড |
| `http://<VM_PUBLIC_IP>:8000/mlops` | MLOps গভর্ন্যান্স ড্যাশবোর্ড |
| `http://<VM_PUBLIC_IP>:8000/docs` | Swagger API |

ডাটাবেস থেকে ডিসিশন ডিস্ট্রিবিউশন চেক:

```bash
docker exec -it fraud-postgres psql -U postgres -d fraud_detection \
  -c "SELECT status, count(*) FROM transactions GROUP BY status;"
```

প্রত্যাশিত: APPROVED > ৯৫%, FLAGGED ২–৪%, REJECTED ১–২%।

---

## ধাপ ৭: CI/CD অটোমেশন (git push ➔ VM)

### ৭.১ GitHub Secrets যোগ করা

Repository ➔ **Settings ➔ Secrets and variables ➔ Actions ➔ New repository secret**

| Secret | মান |
| :--- | :--- |
| `AZURE_VM_HOST` | VM-এর পাবলিক IP |
| `AZURE_VM_USER` | `azureuser` |
| `AZURE_VM_SSH_KEY` | `fraud-vm-key.pem` ফাইলের পুরো কনটেন্ট |

### ৭.২ পাইপলাইন ফ্লো

1. `git push origin master` ➔ **`ci.yml`** (Ruff, Pytest) রান হয়
2. **`docker-publish.yml`** ➔ ৩টি ইমেজ বিল্ড, Trivy স্ক্যান, `ghcr.io/abubinfahd/realtime-fraud-detection/*` এ পুশ
3. GitHub-এ **Release publish** করলে (বা Actions থেকে ম্যানুয়ালি রান করলে) **`cd-azure.yml`**:
   - `docker-compose.prod.yml` ও `database/` VM-এ `scp` করে
   - `docker compose pull` + `up -d` দিয়ে নতুন ইমেজে রোলআউট করে

---

## ট্রাবলশুটিং

| সমস্যা | কারণ | সমাধান |
| :--- | :--- | :--- |
| `UNPROTECTED PRIVATE KEY FILE` | Windows-এ `.pem` ফাইলের পারমিশন বেশি খোলা | ধাপ ৩-এর `icacls` কমান্ড |
| `OSError: libgomp.so.1` | slim ইমেজে OpenMP নেই | Dockerfile-এ `apt-get install -y libgomp1` |
| ড্যাশবোর্ডে ১০০% REJECTED | ইউজার পুল ছোট হওয়ায় velocity rule ট্রিগার | প্রডিউসারের ইউজার পুল ২৫০০-এ বাড়ানো হয়েছে |
| `/mlops` 500 error | কন্টেইনারে ফাইল লেখার পারমিশন | ইন-মেমোরি `dashboard_renderer.py` ব্যবহার |
| ব্রাউজারে সাইট খোলে না | পোর্ট 8000 বন্ধ | ধাপ ২ |

---

## খরচ নিয়ন্ত্রণ

```bash
bash infra/azure/deploy_azure.sh --hibernate   # VM deallocate: compute billing বন্ধ
bash infra/azure/deploy_azure.sh --start       # আবার চালু
bash infra/azure/deploy_azure.sh --teardown    # পুরো resource group মুছে ফেলা
```

অথবা Portal ➔ VM ➔ **Stop**। পুরোপুরি মুছতে: `az group delete --name rg-fraud-streaming-prod --yes --no-wait`

