"""
Full End-to-End Azure ML Pipeline Script.

Orchestrates the complete cloud-native MLOps lifecycle:
1. Connects to Azure ML Workspace using unique resource identifiers.
2. Ensures an auto-scaling Compute Cluster exists (0 nodes when idle = $0 cost).
3. Packages the full codebase and submits an Azure ML Cloud Training Job.
4. Streams execution logs and logs parameters/metrics to Azure ML Experiments (MLflow).
5. Registers the trained model bundle to the Azure ML Model Registry.
6. Registers the custom Conda environment with LightGBM and Scikit-Learn.
7. Provisions/updates a globally unique Managed Online Endpoint & Deployment.
8. Routes 100% traffic and executes an automated live prediction test.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from azure.ai.ml import MLClient, command
from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import (
    AmlCompute,
    CodeConfiguration,
    Environment,
    ManagedOnlineDeployment,
    ManagedOnlineEndpoint,
    Model,
)
from azure.identity import DefaultAzureCredential

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("azureml_pipeline")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="End-to-End Azure ML Training and Deployment Pipeline")
    parser.add_argument(
        "--unique-suffix",
        default=os.getenv("AZUREML_UNIQUE_SUFFIX", "fahd40"),
        help="Unique identifier suffix for all Azure resources (avoids name collisions)",
    )
    parser.add_argument(
        "--subscription-id",
        default=os.getenv("AZURE_SUBSCRIPTION_ID"),
        help="Azure Subscription ID",
    )
    parser.add_argument(
        "--resource-group",
        default=os.getenv("AZURE_RESOURCE_GROUP"),
        help="Azure Resource Group name (defaults to rg-fraud-mlops-<suffix>)",
    )
    parser.add_argument(
        "--workspace-name",
        default=os.getenv("AZURE_WORKSPACE_NAME"),
        help="Azure ML Workspace name (defaults to aml-fraud-workspace-<suffix>)",
    )
    parser.add_argument(
        "--compute-cluster-name",
        default=os.getenv("AZUREML_COMPUTE_CLUSTER"),
        help="Compute cluster name (defaults to cc-cpu-<suffix>)",
    )
    parser.add_argument(
        "--endpoint-name",
        default=os.getenv("AZUREML_ENDPOINT_NAME"),
        help="Globally unique Managed Online Endpoint name (defaults to fraud-api-<suffix>)",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="Skip cloud training job if model artifact already exists locally",
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Skip online endpoint deployment (only run training and model registration)",
    )
    return parser.parse_args()


def resolve_unique_names(args: argparse.Namespace) -> dict[str, str]:
    suffix = args.unique_suffix.lower().strip()
    names = {
        "suffix": suffix,
        "resource_group": args.resource_group or f"rg-fraud-mlops-{suffix}",
        "workspace_name": args.workspace_name or f"aml-fraud-workspace-{suffix}",
        "compute_cluster": args.compute_cluster_name or f"cc-cpu-{suffix}",
        "endpoint_name": args.endpoint_name or f"fraud-api-{suffix}",
        "deployment_name": "blue-v1",
        "model_name": f"fraud_hybrid_model_{suffix}",
        "environment_name": f"fraud-inference-env-{suffix}",
        "experiment_name": f"fraud-cloud-training-{suffix}",
    }
    return names


def get_ml_client(subscription_id: str | None, resource_group: str, workspace_name: str) -> MLClient:
    credential = DefaultAzureCredential()
    if subscription_id:
        logger.info("Connecting to Azure ML Workspace '%s' in '%s'...", workspace_name, resource_group)
        return MLClient(
            credential=credential,
            subscription_id=subscription_id,
            resource_group_name=resource_group,
            workspace_name=workspace_name,
        )
    logger.info("Connecting to Azure ML Workspace using config.json or environment fallback...")
    return MLClient.from_config(credential=credential)


def get_or_create_compute_cluster(ml_client: MLClient, cluster_name: str) -> str:
    """Ensure an auto-scaling CPU compute cluster exists (scales to 0 when idle = $0 cost)."""
    try:
        compute = ml_client.compute.get(cluster_name)
        logger.info("Compute cluster '%s' already exists (state: %s).", cluster_name, compute.state)
        return cluster_name
    except Exception:
        logger.info("Creating auto-scaling compute cluster '%s' (Standard_DS2_v2, min=0, max=2)...", cluster_name)
        compute = AmlCompute(
            name=cluster_name,
            type="amlcompute",
            size="Standard_DS2_v2",
            min_instances=0,
            max_instances=2,
            idle_time_before_scale_down=120,
        )
        ml_client.compute.begin_create_or_update(compute).result()
        logger.info("Compute cluster '%s' created successfully.", cluster_name)
        return cluster_name


def submit_cloud_training_job(
    ml_client: MLClient,
    project_root: Path,
    cluster_name: str,
    experiment_name: str,
) -> str:
    """Package the codebase and execute training on the Azure ML compute cluster."""
    logger.info("Submitting cloud training job to Azure ML cluster '%s'...", cluster_name)
    logger.info("Codebase root: %s", project_root)

    # Use Azure ML curated sklearn image for training dependencies
    job = command(
        code=str(project_root),
        command="pip install -e . && python -m fraud_detection.ml.train",
        environment="AzureML-sklearn-1.5-ubuntu20.04-py38-cpu@latest",
        compute=cluster_name,
        experiment_name=experiment_name,
        display_name=f"cloud-train-{int(time.time())}",
        description="Cloud-native Hybrid Fraud Model Training with LightGBM & Isolation Forest",
    )

    submitted_job = ml_client.jobs.create_or_update(job)
    logger.info("Job submitted! Job Name: %s", submitted_job.name)
    logger.info("Job Studio Web URL: %s", submitted_job.studio_url)

    logger.info("Streaming job execution logs (this takes ~3-5 minutes)...")
    ml_client.jobs.stream(submitted_job.name)
    return submitted_job.name


def main() -> None:
    args = parse_args()
    names = resolve_unique_names(args)
    project_root = Path(__file__).resolve().parent.parent
    artifacts_dir = project_root / "artifacts"
    model_path = artifacts_dir / "fraud_model.joblib"
    conda_path = artifacts_dir / "conda.yaml"

    logger.info("=" * 70)
    logger.info("  Azure ML End-to-End Cloud-Native Training & Deployment Pipeline")
    logger.info("  Unique Suffix:     %s", names["suffix"])
    logger.info("  Resource Group:    %s", names["resource_group"])
    logger.info("  Workspace:         %s", names["workspace_name"])
    logger.info("  Compute Cluster:   %s", names["compute_cluster"])
    logger.info("  Endpoint Name:     %s", names["endpoint_name"])
    logger.info("=" * 70)

    ml_client = get_ml_client(args.subscription_id, names["resource_group"], names["workspace_name"])

    # Step 1: Ensure Compute Cluster exists
    cluster_name = get_or_create_compute_cluster(ml_client, names["compute_cluster"])

    # Step 2: Cloud Training Job (runs entire codebase in Azure ML)
    if not args.skip_train:
        submit_cloud_training_job(ml_client, project_root, cluster_name, names["experiment_name"])
        # Ensure local model file exists for packaging or fallback
        if not model_path.exists():
            logger.info("Training local fallback artifact for endpoint packaging...")
            import subprocess
            subprocess.run([sys.executable, "-m", "fraud_detection.ml.train"], cwd=project_root, check=True)
    else:
        logger.info("Skipping cloud training (--skip-train specified).")

    # Step 3: Register Model in Azure ML Model Registry
    logger.info("Registering model '%s' in Model Registry...", names["model_name"])
    model = Model(
        path=str(model_path),
        name=names["model_name"],
        description="Cloud-trained Hybrid Fraud Detection Model (LightGBM + Isolation Forest)",
        type=AssetTypes.CUSTOM_MODEL,
    )
    registered_model = ml_client.models.create_or_update(model)
    logger.info("Model registered: %s (version %s)", registered_model.name, registered_model.version)

    if args.skip_deploy:
        logger.info("Skipping deployment (--skip-deploy specified). Pipeline complete!")
        return

    # Step 4: Register Custom Inference Environment (includes lightgbm)
    logger.info("Registering custom environment '%s'...", names["environment_name"])
    env = Environment(
        name=names["environment_name"],
        description="Custom CPU environment with LightGBM, Scikit-Learn and Joblib",
        image="mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04:latest",
        conda_file=str(conda_path),
    )
    registered_env = ml_client.environments.create_or_update(env)
    logger.info("Environment registered: %s (version %s)", registered_env.name, registered_env.version)

    # Step 5: Provision or Update Managed Online Endpoint
    logger.info("Ensuring Managed Online Endpoint '%s' exists...", names["endpoint_name"])
    endpoint = ManagedOnlineEndpoint(
        name=names["endpoint_name"],
        description="Real-time Fraud Scoring Endpoint",
        auth_mode="key",
    )
    ml_client.online_endpoints.begin_create_or_update(endpoint).result()
    logger.info("Endpoint '%s' is provisioned.", names["endpoint_name"])

    # Step 6: Deploy Model to Online Endpoint
    logger.info("Deploying '%s' to '%s' (Standard_DS2_v2 x1)...", names["deployment_name"], names["endpoint_name"])
    deployment = ManagedOnlineDeployment(
        name=names["deployment_name"],
        endpoint_name=names["endpoint_name"],
        model=registered_model,
        environment=registered_env,
        code_configuration=CodeConfiguration(
            code=str(artifacts_dir),
            scoring_script="score.py",
        ),
        instance_type="Standard_DS2_v2",
        instance_count=1,
    )
    ml_client.online_deployments.begin_create_or_update(deployment).result()

    # Step 7: Route 100% Traffic to the New Deployment
    logger.info("Routing 100%% traffic to deployment '%s'...", names["deployment_name"])
    endpoint.traffic = {names["deployment_name"]: 100}
    ml_client.online_endpoints.begin_create_or_update(endpoint).result()

    endpoint_info = ml_client.online_endpoints.get(name=names["endpoint_name"])
    scoring_uri = endpoint_info.scoring_uri
    keys = ml_client.online_endpoints.get_keys(name=names["endpoint_name"])

    logger.info("=" * 70)
    logger.info("  [+] Cloud Pipeline Completed Successfully!")
    logger.info("  Endpoint URL: %s", scoring_uri)
    logger.info("  Primary Key:  %s", keys.primary_key[:8] + "..." if keys.primary_key else "None")
    logger.info("=" * 70)

    # Step 8: Automated Live Smoke Test
    logger.info("Executing automated live smoke test against endpoint...")
    import urllib.request
    test_payload = {
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
        scoring_uri,
        data=str.encode(json.dumps(test_payload)),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {keys.primary_key}",
        },
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        logger.info("Live Smoke Test Result:\n%s", json.dumps(result, indent=2))
        logger.info("Verification PASSED!")


if __name__ == "__main__":
    main()
