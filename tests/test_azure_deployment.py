"""Automated verification tests for Stage 13 Azure Cloud Deployment artifacts."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestProductionDockerCompose:
    """Validate docker-compose.prod.yml defines the complete 6-service stack."""

    def test_prod_compose_all_six_services_and_limits(self) -> None:
        """Verify docker-compose.prod.yml configures kafka, postgres, redis, producer, consumer, and api."""
        compose_path = PROJECT_ROOT / "docker-compose.prod.yml"
        assert compose_path.exists(), "docker-compose.prod.yml is missing"

        content = compose_path.read_text(encoding="utf-8")
        for service_container in [
            "fraud-kafka",
            "fraud-postgres",
            "fraud-redis",
            "fraud-producer",
            "fraud-consumer",
            "fraud-api",
        ]:
            assert service_container in content, f"{service_container} missing in prod compose"

        assert "mem_limit:" in content
        assert "restart: always" in content
        assert "8000:8000" in content
        assert "80:8000" in content
        assert "ghcr.io/abubinfahd/realtime-fraud-detection" in content


class TestAzureInfrastructureScripts:
    """Validate Azure cloud-init, CLI deployment, and Cost Management budget scripts."""

    def test_cloud_init_bootstrap_configuration(self) -> None:
        """Verify cloud-init.txt configures 4G swap, kernel sysctl, and Docker Engine."""
        cloud_init_path = PROJECT_ROOT / "infra" / "azure" / "cloud-init.txt"
        assert cloud_init_path.exists(), "infra/azure/cloud-init.txt is missing"

        content = cloud_init_path.read_text(encoding="utf-8")
        assert "/swapfile" in content
        assert "vm.max_map_count=262144" in content
        assert "docker-ce" in content
        assert "docker-compose-plugin" in content

    def test_budget_alert_script(self) -> None:
        """Verify budget_alert.sh enforces the $150 monthly budget ceiling."""
        budget_path = PROJECT_ROOT / "infra" / "azure" / "budget_alert.sh"
        assert budget_path.exists(), "infra/azure/budget_alert.sh is missing"

        content = budget_path.read_text(encoding="utf-8")
        assert "az consumption budget create" in content
        assert "150" in content

    def test_deploy_azure_script_lifecycle_modes(self) -> None:
        """Verify deploy_azure.sh supports provisioning, hibernation, and teardown."""
        deploy_path = PROJECT_ROOT / "infra" / "azure" / "deploy_azure.sh"
        assert deploy_path.exists(), "infra/azure/deploy_azure.sh is missing"

        content = deploy_path.read_text(encoding="utf-8")
        assert "Standard_B4ms" in content
        assert "--hibernate" in content
        assert "--teardown" in content
        assert "az vm deallocate" in content
        assert "az group delete" in content
        assert "Allow-Dashboard-WebSockets" in content


class TestAzureCDWorkflow:
    """Validate GitHub Actions continuous deployment workflow for Azure VM."""

    def test_cd_azure_workflow_exists_and_deploys_prod_compose(self) -> None:
        """Verify .github/workflows/cd-azure.yml references docker-compose.prod.yml."""
        cd_path = PROJECT_ROOT / ".github" / "workflows" / "cd-azure.yml"
        assert cd_path.exists(), ".github/workflows/cd-azure.yml is missing"

        content = cd_path.read_text(encoding="utf-8")
        assert "docker-compose.prod.yml" in content
        assert "workflow_dispatch" in content
