#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Stage 13: Azure Cost Management Hard Budget Alert ($150 Ceiling)
# ==============================================================================

BUDGET_NAME="${BUDGET_NAME:-FraudDetection-Monthly-Budget}"
BUDGET_AMOUNT="${BUDGET_AMOUNT:-150}"
START_DATE="$(date -u +%Y-%m-01)"
END_DATE="$(date -u -d "+1 year" +%Y-%m-01 2>/dev/null || echo "2027-10-01")"

echo "============================================================"
echo "  Configuring Azure Cost Management Budget Guardrail"
echo "  Budget Name:    ${BUDGET_NAME}"
echo "  Monthly Limit:  $${BUDGET_AMOUNT}.00 USD (75% Warning @ $112.50)"
echo "============================================================"

az consumption budget create \
  --budget-name "${BUDGET_NAME}" \
  --amount "${BUDGET_AMOUNT}" \
  --category "Cost" \
  --time-grain "Monthly" \
  --start-date "${START_DATE}" \
  --end-date "${END_DATE}"

echo "[+] Budget '${BUDGET_NAME}' ($${BUDGET_AMOUNT}/mo) configured successfully."
