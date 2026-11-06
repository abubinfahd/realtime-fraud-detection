"""
Automated Azure Machine Learning (SDK v2) Deployment Script.

Registers the hybrid fraud model and custom Conda environment, creates or updates
a Managed Online Endpoint, provisions the deployment, and routes 100% live traffic.
"""

import argparse
import logging
import os
from pathlib import Path

from azure.ai.ml import MLClient
from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import (
    CodeConfiguration,
    Environment,
    ManagedOnlineDeployment,
    ManagedOnlineEndpoint,
    Model,
)
from azure.identity import DefaultAzureCredential

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy Hybrid Fraud Model to Azure ML")
    parser.add_argument(
        "--subscription-id",
        default=os.getenv("AZURE_SUBSCRIPTION_ID"),
        help="Azure Subscription ID",
    )
    parser.add_argument(
        "--resource-group",
        default=os.getenv("AZURE_RESOURCE_GROUP", "rg-fraud-ml"),
        help="Azure Resource Group name",
    )
    parser.add_argument(
        "--workspace-name",
        default=os.getenv("AZURE_WORKSPACE_NAME", "aml-fraud-prod"),
        help="Azure ML Workspace name",
    )
    parser.add_argument(
        "--endpoint-name",
        default=os.getenv("AZUREML_ENDPOINT_NAME", "fraud-live-fahd40"),
        help="Globally unique Managed Online Endpoint name",
    )
    parser.add_argument(
        "--deployment-name",
        default=os.getenv("AZUREML_DEPLOYMENT_NAME", "real-time-fraud-v1"),
        help="Deployment slot name",
    )
    parser.add_argument(
        "--instance-type",
        default=os.getenv("AZUREML_INSTANCE_TYPE", "Standard_DS2_v2"),
        help="Azure VM SKU for inference container",
    )
    parser.add_argument(
        "--instance-count",
        type=int,
        default=int(os.getenv("AZUREML_INSTANCE_COUNT", "1")),
        help="Number of inference instances",
    )
    return parser.parse_args()


def get_ml_client(args: argparse.Namespace) -> MLClient:
    """Connect to Azure ML Workspace via DefaultAzureCredential or config.json."""
    credential = DefaultAzureCredential()
    if args.subscription_id:
        logger.info(
            "Connecting to Azure ML Workspace '%s' in resource group '%s'...",
            args.workspace_name,
            args.resource_group,
        )
        return MLClient(
            credential=credential,
            subscription_id=args.subscription_id,
            resource_group_name=args.resource_group,
            workspace_name=args.workspace_name,
        )
    logger.info("Connecting to Azure ML Workspace using local config.json...")
    return MLClient.from_config(credential=credential)


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    artifacts_dir = project_root / "artifacts"
    model_path = artifacts_dir / "fraud_model.joblib"
    conda_path = artifacts_dir / "conda.yaml"

    if not model_path.exists():
        raise FileNotFoundError(
            f"Model file not found at {model_path}. Run 'python -m fraud_detection.ml.train' first."
        )

    ml_client = get_ml_client(args)

    # 1. Register Model in Azure ML Model Registry
    logger.info("Registering model 'fraud_hybrid_model' from %s...", model_path)
    model = Model(
        path=str(model_path),
        name="fraud_hybrid_model",
        description="Hybrid Fraud Detection Model (LightGBM + Isolation Forest)",
        type=AssetTypes.CUSTOM_MODEL,
    )
    registered_model = ml_client.models.create_or_update(model)
    logger.info(
        "Model registered: %s (version %s)", registered_model.name, registered_model.version
    )

    # 2. Register Custom Inference Environment
    logger.info("Registering custom environment 'fraud-inference-env'...")
    env = Environment(
        name="fraud-inference-env",
        description="Custom CPU environment with LightGBM and Scikit-Learn",
        image="mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04:latest",
        conda_file=str(conda_path),
    )
    registered_env = ml_client.environments.create_or_update(env)
    logger.info(
        "Environment registered: %s (version %s)", registered_env.name, registered_env.version
    )

    # 3. Create or Update Managed Online Endpoint
    logger.info("Provisioning Managed Online Endpoint '%s'...", args.endpoint_name)
    endpoint = ManagedOnlineEndpoint(
        name=args.endpoint_name,
        description="Real-time Hybrid Fraud Detection Online Endpoint",
        auth_mode="key",
    )
    ml_client.online_endpoints.begin_create_or_update(endpoint).result()
    logger.info("Endpoint '%s' is ready.", args.endpoint_name)

    # 4. Create or Update Managed Online Deployment
    logger.info(
        "Deploying '%s' on '%s' (%s x%d)...",
        args.deployment_name,
        args.endpoint_name,
        args.instance_type,
        args.instance_count,
    )
    deployment = ManagedOnlineDeployment(
        name=args.deployment_name,
        endpoint_name=args.endpoint_name,
        model=registered_model,
        environment=registered_env,
        code_configuration=CodeConfiguration(
            code=str(artifacts_dir),
            scoring_script="score.py",
        ),
        instance_type=args.instance_type,
        instance_count=args.instance_count,
    )
    ml_client.online_deployments.begin_create_or_update(deployment).result()

    # 5. Route 100% Live Traffic to New Deployment
    logger.info("Routing 100%% live traffic to deployment '%s'...", args.deployment_name)
    endpoint.traffic = {args.deployment_name: 100}
    ml_client.online_endpoints.begin_create_or_update(endpoint).result()

    scoring_uri = ml_client.online_endpoints.get(name=args.endpoint_name).scoring_uri
    logger.info("=" * 65)
    logger.info("Deployment Succeeded!")
    logger.info("Scoring URI: %s", scoring_uri)
    logger.info("=" * 65)


if __name__ == "__main__":
    main()

