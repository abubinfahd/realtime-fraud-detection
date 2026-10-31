#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Stage 13: Automated Microsoft Azure Deployment & Lifecycle Manager
# Supports: --deploy (default), --hibernate, --start, --teardown
# ==============================================================================

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-fraud-streaming-prod}"
LOCATION="${LOCATION:-eastus}"
VM_NAME="${VM_NAME:-vm-fraud-engine}"
VM_SIZE="${VM_SIZE:-Standard_B4ms}"
NSG_NAME="${NSG_NAME:-nsg-fraud}"
VNET_NAME="${VNET_NAME:-vnet-fraud}"
SUBNET_NAME="${SUBNET_NAME:-snet-compute}"
PIP_NAME="${PIP_NAME:-pip-fraud-prod}"
DNS_LABEL="${DNS_LABEL:-fraud-stream-demo-${RANDOM}}"
ADMIN_USER="${ADMIN_USER:-azureuser}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ACTION="${1:---deploy}"

case "${ACTION}" in
  --hibernate)
    echo "[*] Deallocating VM '${VM_NAME}' to pause compute billing..."
    az vm deallocate --resource-group "${RESOURCE_GROUP}" --name "${VM_NAME}"
    echo "[+] VM deallocated. Compute billing stopped."
    exit 0
    ;;
  --start)
    echo "[*] Starting VM '${VM_NAME}'..."
    az vm start --resource-group "${RESOURCE_GROUP}" --name "${VM_NAME}"
    echo "[+] VM started. Docker Compose stack will resume automatically."
    exit 0
    ;;
  --teardown)
    echo "[!] Deleting entire Resource Group '${RESOURCE_GROUP}'..."
    az group delete --name "${RESOURCE_GROUP}" --yes --no-wait
    echo "[+] Resource group teardown initiated. All billing will stop."
    exit 0
    ;;
esac

echo "============================================================"
echo "  Stage 13: Provisioning Azure Production Infrastructure"
echo "  Resource Group: ${RESOURCE_GROUP} (${LOCATION})"
echo "  VM SKU:         ${VM_SIZE}"
echo "============================================================"

# 1. Create Resource Group
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --tags Environment=Production Project=RealTimeFraudDetection

# 2. Create Virtual Network & Subnet
az network vnet create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VNET_NAME}" \
  --address-prefix 10.0.0.0/16 \
  --subnet-name "${SUBNET_NAME}" \
  --subnet-prefix 10.0.1.0/24

# 3. Create Network Security Group & Inbound Rules (22, 80, 8000, 443)
az network nsg create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${NSG_NAME}"

az network nsg rule create \
  --resource-group "${RESOURCE_GROUP}" \
  --nsg-name "${NSG_NAME}" \
  --name Allow-SSH \
  --priority 100 \
  --destination-port-ranges 22 \
  --access Allow \
  --protocol Tcp

az network nsg rule create \
  --resource-group "${RESOURCE_GROUP}" \
  --nsg-name "${NSG_NAME}" \
  --name Allow-Dashboard-WebSockets \
  --priority 110 \
  --destination-port-ranges 80 8000 443 \
  --access Allow \
  --protocol Tcp

# 4. Create Static Public IP with DNS Label
az network public-ip create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${PIP_NAME}" \
  --sku Standard \
  --allocation-method Static \
  --dns-name "${DNS_LABEL}"

# 5. Provision Ubuntu 22.04 LTS VM with cloud-init bootstrap
az vm create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VM_NAME}" \
  --image Ubuntu2204 \
  --size "${VM_SIZE}" \
  --admin-username "${ADMIN_USER}" \
  --generate-ssh-keys \
  --vnet-name "${VNET_NAME}" \
  --subnet "${SUBNET_NAME}" \
  --nsg "${NSG_NAME}" \
  --public-ip-address "${PIP_NAME}" \
  --os-disk-size-gb 64 \
  --storage-sku Premium_LRS \
  --custom-data "${SCRIPT_DIR}/cloud-init.txt"

PUBLIC_IP="$(az vm show -d -g "${RESOURCE_GROUP}" -n "${VM_NAME}" --query publicIps -o tsv)"
FQDN="$(az network public-ip show -g "${RESOURCE_GROUP}" -n "${PIP_NAME}" --query dnsSettings.fqdn -o tsv)"

echo "============================================================"
echo "  [+] Azure VM Provisioned Successfully!"
echo "  Public IP:    ${PUBLIC_IP}"
echo "  Public FQDN:  ${FQDN}"
echo "  Dashboard:    http://${PUBLIC_IP}:8000/dashboard/"
echo "============================================================"
