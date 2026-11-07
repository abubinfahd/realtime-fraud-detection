"""
Register Trained Model in Azure ML Model Registry (In-Cloud / Zero Local Download).

This script runs directly inside Azure (e.g. on Azure ML Compute Instance or Cloud Shell)
and registers the local artifact `artifacts/fraud_model.joblib` directly to the
Azure ML Model Registry without downloading or uploading from a local PC.
"""

import argparse
import logging
import os
from pathlib import Path

from azure.ai.ml import MLClient
from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import Model
from azure.identity import DefaultAzureCredential

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("register_model")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register Fraud Model directly in Azure ML Registry")
    parser.add_argument(
        "--model-path",
        default="artifacts/fraud_model.joblib",
        help="Path to the trained model artifact (defaults to artifacts/fraud_model.joblib)",
    )
    parser.add_argument(
        "--model-name",
        default=os.getenv("AZUREML_MODEL_NAME", "fraud_hybrid_model_fahd40"),
        help="Name of the model in Azure ML Model Registry (defaults to fraud_hybrid_model_fahd40)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Model version string (defaults to auto-increment in Azure ML)",
    )
    parser.add_argument(
        "--description",
        default="Hybrid Fraud Model (LightGBM + Fast Isolation Forest) trained in Azure ML",
        help="Model description in Azure ML registry",
    )
    parser.add_argument(
        "--subscription-id",
        default=os.getenv("AZURE_SUBSCRIPTION_ID"),
        help="Azure Subscription ID",
    )
    parser.add_argument(
        "--resource-group",
        default=os.getenv("AZURE_RESOURCE_GROUP", "rg-fraud-mlops-fahd40"),
        help="Azure Resource Group name",
    )
    parser.add_argument(
        "--workspace-name",
        default=os.getenv("AZURE_WORKSPACE_NAME", "aml-fraud-workspace-fahd40"),
        help="Azure ML Workspace name",
    )
    return parser.parse_args()


def get_ml_client(args: argparse.Namespace) -> MLClient:
    credential = DefaultAzureCredential()
    if args.subscription_id:
        logger.info(
            "Connecting to Azure ML Workspace '%s' in '%s' (Subscription: %s)...",
            args.workspace_name,
            args.resource_group,
            args.subscription_id,
        )
        return MLClient(
            credential=credential,
            subscription_id=args.subscription_id,
            resource_group_name=args.resource_group,
            workspace_name=args.workspace_name,
        )

    # Compute Instances have Azure ML workspace context configured automatically
    try:
        logger.info("Attempting connection via Azure ML workspace configuration...")
        return MLClient.from_config(credential=credential)
    except Exception:
        logger.info(
            "Connecting with explicit resource group '%s' and workspace '%s'...",
            args.resource_group,
            args.workspace_name,
        )
        return MLClient(
            credential=credential,
            resource_group_name=args.resource_group,
            workspace_name=args.workspace_name,
        )


def main() -> None:
    args = parse_args()
    model_file = Path(args.model_path).resolve()

    if not model_file.exists():
        raise FileNotFoundError(
            f"Model artifact not found at '{model_file}'. "
            "Please run 'python -m fraud_detection.ml.train' inside Azure first!"
        )

    file_size_kb = os.path.getsize(model_file) / 1024
    logger.info("Found model artifact: %s (%.1f KB)", model_file, file_size_kb)

    ml_client = get_ml_client(args)

    logger.info("Registering model '%s' in Azure ML Model Registry...", args.model_name)
    model = Model(
        path=str(model_file),
        name=args.model_name,
        version=args.version,
        description=args.description,
        type=AssetTypes.CUSTOM_MODEL,
    )

    registered_model = ml_client.models.create_or_update(model)
    logger.info("=" * 65)
    logger.info("  [+] SUCCESS: Model Registered in Azure ML Model Registry!")
    logger.info("  Name:    %s", registered_model.name)
    logger.info("  Version: %s", registered_model.version)
    logger.info("  ID:      %s", registered_model.id)
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
