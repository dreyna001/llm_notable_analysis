from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
AZURE = ROOT / "deploy" / "azure"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_storage_is_private_keyless_and_has_required_queues() -> None:
    storage = _read(AZURE / "modules" / "storage.bicep")
    assert "publicNetworkAccess: 'Disabled'" in storage
    assert "allowSharedKeyAccess: false" in storage
    assert "defaultToOAuthAuthentication: true" in storage
    assert "'notable-analysis-jobs'" in storage
    assert "'case-embed-invocations'" in storage


def test_private_endpoint_contract_covers_trigger_and_host_services() -> None:
    network = _read(AZURE / "modules" / "network.bicep")
    for endpoint in (
        "input-blob",
        "input-queue",
        "output-blob",
        "output-queue",
        "host-blob",
        "host-queue",
        "host-table",
    ):
        assert endpoint in network
    assert "Microsoft.Web/serverFarms" in network
    assert "private-endpoints" in network


def test_function_apps_have_no_secret_fallback_settings() -> None:
    functions = "\n".join(
        _read(AZURE / "modules" / name)
        for name in (
            "functions-analyzer.bicep",
            "functions-embed.bicep",
            "functions-portal.bicep",
        )
    )
    for forbidden in (
        "DOCKER_REGISTRY_SERVER_USERNAME",
        "DOCKER_REGISTRY_SERVER_PASSWORD",
        "WEBSITE_CONTENTAZUREFILECONNECTIONSTRING",
        "WEBSITE_CONTENTSHARE",
        "AZURE_OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        assert forbidden not in functions
    assert "AzureWebJobsStorage__credential" in functions
    assert "acrUseManagedIdentityCreds: true" in functions
    assert "WEBSITES_ENABLE_APP_SERVICE_STORAGE" in functions


def test_four_identities_receive_acr_and_host_storage_contracts() -> None:
    main = _read(AZURE / "main.bicep")
    identities = _read(AZURE / "modules" / "identities.bicep")
    for identity in ("analyzer", "embed", "disposition", "portal"):
        assert f"resource {identity} " in identities
        assert f"identities.outputs.{identity}.principalId" in main
    assert "host-storage-access.bicep" in main
    assert "container-registry-access.bicep" in main


def test_analyzer_has_foundry_and_polling_blob_trigger_rbac() -> None:
    main = _read(AZURE / "main.bicep")
    analyzer = _read(AZURE / "modules" / "functions-analyzer.bicep")
    foundry = _read(AZURE / "modules" / "foundry-access.bicep")
    assert "foundry-access.bicep" in main
    assert "a97b65f3-24c7-4388-baec-2e87135dc908" in foundry
    assert "blobOwnerRoleId" in analyzer
    assert "queueContributorRoleId" in analyzer
    assert "InputStorage__blobServiceUri" in analyzer
    assert "InputStorage__queueServiceUri" in analyzer


def test_single_digest_image_and_wrapper_isolation_are_explicit() -> None:
    main = _read(AZURE / "main.bicep")
    analyzer = _read(AZURE / "modules" / "functions-analyzer.bicep")
    embed = _read(AZURE / "modules" / "functions-embed.bicep")
    portal = _read(AZURE / "modules" / "functions-portal.bicep")
    assert main.count("containerImageUri: ContainerImageUri") == 3
    assert "@sha256" in main
    expected_wrappers = {
        "intake_blob": {"analyzer": "false", "embed": "true", "portal": "true"},
        "analyzer_queue": {"analyzer": "false", "embed": "true", "portal": "true"},
        "case_embed_queue": {"analyzer": "true", "embed": "false", "portal": "true"},
        "disposition_sync_timer": {"analyzer": "true", "embed": "true", "portal": "true"},
        "portal_http": {"analyzer": "true", "embed": "true", "portal": "false"},
    }
    modules = {"analyzer": analyzer, "embed": embed, "portal": portal}
    for wrapper, expected_by_app in expected_wrappers.items():
        for app_name, expected_value in expected_by_app.items():
            setting = f"AzureWebJobs.{wrapper}.Disabled', value: '{expected_value}'"
            assert modules[app_name].count(setting) == 1
    assert "functionAppScaleLimit" in analyzer
    assert "functionAppScaleLimit" in embed


def test_portal_storage_function_and_identity_contracts_are_private_and_keyless() -> None:
    storage = _read(AZURE / "modules" / "storage.bicep")
    portal = _read(AZURE / "modules" / "functions-portal.bicep")
    openai = _read(AZURE / "modules" / "openai-access.bicep")
    search = _read(AZURE / "modules" / "search-access.bicep")
    assert "staticWebsite" in storage
    assert "indexDocument: 'index.html'" in storage
    assert "errorDocument404Path: 'index.html'" in storage
    assert "portalUiDeployerBlobContributor" in storage
    assert "publicNetworkAccess: 'Disabled'" in portal
    assert "groupIds: ['sites']" in portal
    assert "AzureFunctionsJobHost__functionTimeout', value: '00:03:45'" in portal
    assert "PORTAL_CHAT_TIMEOUT_SEC" in portal
    assert "AzureWebJobs.portal_http.Disabled', value: 'false'" in portal
    assert "outputBlobReader" in portal
    assert "portalOpenAiAccess" in openai
    assert "1407120a-92aa-4202-b7e9-c0e197c71c8f" in search


def test_apim_is_standard_v2_authenticated_and_staged_for_private_only_access() -> None:
    main = _read(AZURE / "main.bicep")
    apim = _read(AZURE / "modules" / "apim-portal.bicep")
    assert "@allowed(['StandardV2'])" in main
    assert "publicNetworkAccess: 'Enabled'" in apim
    assert "virtualNetworkConfiguration" in apim
    assert "format: 'openapi+json'" in apim
    assert "validate-jwt" in apim
    assert "openid-config" in apim
    assert "require-scheme=\"Bearer\"" in apim
    assert "require-expiration-time=\"true\"" in apim
    assert "<claim name=\"sub\"" in apim
    assert "<claim name=\"roles\"" in apim
    assert "forward-request timeout=\"30\"" in apim


def test_frontdoor_routes_private_origins_without_single_origin_probes_or_api_cache() -> None:
    frontdoor = _read(AZURE / "modules" / "frontdoor-portal.bicep")
    assert "Premium_AzureFrontDoor" in frontdoor
    assert "originResponseTimeoutSeconds: 240" in frontdoor
    assert frontdoor.index("resource chatRoute") < frontdoor.index("resource apiRoute")
    assert "patternsToMatch: ['/api/chat']" in frontdoor
    assert "patternsToMatch: ['/api/*']" in frontdoor
    assert "patternsToMatch: ['/health']" in frontdoor
    assert "patternsToMatch: ['/ready']" in frontdoor
    assert "patternsToMatch: ['/', '/index.html']" in frontdoor
    for group_id in ("'web'", "'Gateway'", "'sites'"):
        assert f"groupId: {group_id}" in frontdoor
    assert "healthProbeSettings:" not in frontdoor
    api_prefix = frontdoor[: frontdoor.index("resource uiRoute")]
    assert "cacheConfiguration:" not in api_prefix


def test_portal_deploy_flow_approves_every_origin_before_disabling_apim() -> None:
    for name in ("setup-and-deploy.sh", "setup-and-deploy.ps1"):
        script = _read(ROOT / "scripts" / name)
        assert "portal-function" in script
        assert "portal-apim" in script
        assert "portal-web" in script
        assert "private-endpoint-connection approve" in script
        assert "sharedPrivateLinkResource.status" in script
        assert "properties.publicNetworkAccess=Disabled" in script
        assert script.index("sharedPrivateLinkResource.status") < script.index(
            "properties.publicNetworkAccess=Disabled"
        )
        assert "PORTAL_VALIDATION_BEARER_TOKEN" in script
        assert (
            "PORTAL_ENTRA_REQUIRED_APP_ROLE is required when PORTAL_AUTH_MODE=iam."
            in script
        )
        assert "Authorization" in script
        assert "storage blob upload-batch" in script
        assert "--auth-mode login" in script
        assert "VITE_PORTAL_API_BASE_URL" in script


def test_deployment_scripts_gate_on_host_identity_storage_and_exact_functions() -> None:
    scripts = [
        _read(ROOT / "scripts" / "setup-and-deploy.sh"),
        _read(ROOT / "scripts" / "setup-and-deploy.ps1"),
    ]
    for script in scripts:
        assert "hostruntime/admin/host/status?api-version=2022-03-01" in script
        assert "functionapp function list" in script
        assert "acrUseManagedIdentityCreds" in script
        assert "acrUserManagedIdentityID" in script
        assert "AzureWebJobsStorage__credential" in script
        assert "AzureWebJobsStorage__clientId" in script
        for service in ("blob", "queue", "table"):
            assert f"AzureWebJobsStorage__${{service}}ServiceUri" in script
        for function_name in ("intake_blob", "analyzer_queue", "case_embed_queue"):
            assert function_name in script
    assert "Assert-AzSucceeded" in scripts[1]


def test_deployment_script_setting_denylist_is_complete_and_name_only() -> None:
    forbidden_names = (
        "AzureWebJobsStorage",
        "AzureWebJobsDashboard",
        "WEBSITE_CONTENTAZUREFILECONNECTIONSTRING",
        "WEBSITE_CONTENTSHARE",
        "DOCKER_REGISTRY_SERVER_USERNAME",
        "DOCKER_REGISTRY_SERVER_PASSWORD",
        "ACR_TOKEN",
        "CONTAINER_REGISTRY_CREDENTIAL",
        "STORAGE_KEY",
        "STORAGE_ACCOUNT_KEY",
        "AZURE_STORAGE_CONNECTION_STRING",
        "AZURE_FILES_CONNECTION_STRING",
        "AZURE_AI_FOUNDRY_API_KEY",
        "ANTHROPIC_SECRET",
        "AZURE_OPENAI_API_KEY",
        "SEARCH_API_KEY",
        "AZURE_SEARCH_ADMIN_KEY",
        "COSMOS_KEY",
        "COSMOS_CONNECTION_STRING",
    )
    allowed_identity_settings = (
        "AzureWebJobsStorage__credential",
        "AzureWebJobsStorage__clientId",
        "AzureWebJobsStorage__blobServiceUri",
        "AzureWebJobsStorage__queueServiceUri",
        "AzureWebJobsStorage__tableServiceUri",
        "AZURE_AI_FOUNDRY_RESOURCE_ID",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_SEARCH_ENDPOINT",
        "COSMOS_ACCOUNT_NAME",
    )

    for name in ("setup-and-deploy.sh", "setup-and-deploy.ps1"):
        script = _read(ROOT / "scripts" / name)
        match = re.search(
            r"forbidden(?:_setting_pattern|SettingPattern)\s*=\s*'([^']+)'",
            script,
        )
        assert match is not None
        denylist = re.compile(match.group(1))
        assert all(denylist.search(setting.upper()) for setting in forbidden_names)
        assert not any(
            denylist.search(setting.upper()) for setting in allowed_identity_settings
        )
        assert "--query '[].name'" in script


def test_cosmos_is_single_region_serverless_strong_and_keyless() -> None:
    cosmos = _read(AZURE / "modules" / "cosmos.bicep")
    assert "{ name: 'EnableServerless' }" in cosmos
    assert "defaultConsistencyLevel: 'Strong'" in cosmos
    assert cosmos.count("locationName: location") == 1
    assert "enableAutomaticFailover: false" in cosmos
    assert "disableLocalAuth: true" in cosmos
    assert "disableKeyBasedMetadataWriteAccess: true" in cosmos
    assert not re.search(r"\b(?:throughput|autoscaleSettings)\s*:", cosmos)


def test_cosmos_container_partition_and_ttl_contracts_are_exact() -> None:
    cosmos = _read(AZURE / "modules" / "cosmos.bicep")
    expected_partition_keys = {
        "sideEffectIdempotency": "/id",
        "caseIndex": "/case_id",
        "disposition": "/snow_sys_id",
        "dispositionSyncState": "/job_name",
        "chatSessions": "/user_id",
        "chatMessages": "/session_id",
    }
    resource_starts = list(
        re.finditer(
            r"resource\s+(\w+)\s+'Microsoft\.DocumentDB/databaseAccounts/"
            r"sqlDatabases/containers@[^']+'",
            cosmos,
        )
    )
    resource_bodies: dict[str, str] = {}
    for index, match in enumerate(resource_starts):
        end = (
            resource_starts[index + 1].start()
            if index + 1 < len(resource_starts)
            else cosmos.find("resource analyzerSideEffectContributor", match.end())
        )
        resource_bodies[match.group(1)] = cosmos[match.start() : end]

    assert set(expected_partition_keys) <= set(resource_bodies)
    for resource_name, partition_key in expected_partition_keys.items():
        assert f"paths: ['{partition_key}']" in resource_bodies[resource_name]
        assert "version: 2" in resource_bodies[resource_name]

    ttl_resources = {
        "sideEffectIdempotency",
        "caseIndex",
        "disposition",
        "chatSessions",
        "chatMessages",
    }
    for resource_name in ttl_resources:
        assert "defaultTtl: -1" in resource_bodies[resource_name]
    assert "defaultTtl" not in resource_bodies["dispositionSyncState"]


def test_cosmos_composite_indexes_cover_bounded_ordered_queries() -> None:
    cosmos = _read(AZURE / "modules" / "cosmos.bicep")
    required_composite_paths = (
        "{ path: '/processed_at', order: 'descending' }",
        "{ path: '/case_id', order: 'descending' }",
        "{ path: '/correlation_id', order: 'ascending' }",
        "{ path: '/sys_updated_on', order: 'descending' }",
        "{ path: '/status', order: 'ascending' }",
        "{ path: '/user_id', order: 'ascending' }",
        "{ path: '/updated_at', order: 'descending' }",
        "{ path: '/session_id', order: 'descending' }",
        "{ path: '/created_at', order: 'ascending' }",
        "{ path: '/message_id', order: 'ascending' }",
    )
    assert all(path in cosmos for path in required_composite_paths)
    assert "indexingMode: 'consistent'" in cosmos
    assert "path: '/*'" in cosmos
    assert "path: '/\"_etag\"/?'" in cosmos


def test_cosmos_sql_rbac_is_container_scoped_and_capability_gated() -> None:
    cosmos = _read(AZURE / "modules" / "cosmos.bicep")
    main = _read(AZURE / "main.bicep")
    assert "00000000-0000-0000-0000-000000000001" in cosmos
    assert "00000000-0000-0000-0000-000000000002" in cosmos
    for aggregate_scope in (
        "sideEffectIdempotency.id",
        "caseIndex.id",
        "disposition.id",
        "dispositionSyncState.id",
        "chatSessions.id",
        "chatMessages.id",
    ):
        assert f"scope: {aggregate_scope}" in cosmos
    for identity in ("analyzer", "embed", "disposition", "portal"):
        assert f"{identity}PrincipalId" in cosmos
        assert f"identities.outputs.{identity}.principalId" in main

    side_effect_declaration = re.search(
        r"resource sideEffectIdempotency '[^']+'\s*=\s*([^\n{]*){",
        cosmos,
    )
    assert side_effect_declaration is not None
    assert "if" not in side_effect_declaration.group(1)
    assert "deployCaseIndex: hasAnalystPortalProfile" in main
    assert "deployDispositionContainers: ServiceNowDispositionSyncEnabled" in main
    assert "deployChatHistoryContainers: deployChatHistoryContainers" in main


def test_cosmos_app_settings_use_endpoint_and_scoped_container_names_only() -> None:
    main = _read(AZURE / "main.bicep")
    analyzer = _read(AZURE / "modules" / "functions-analyzer.bicep")
    embed = _read(AZURE / "modules" / "functions-embed.bicep")
    assert "module cosmos 'modules/cosmos.bicep'" in main
    for setting in (
        "COSMOS_ENDPOINT",
        "COSMOS_DATABASE_NAME",
        "SIDE_EFFECT_IDEMPOTENCY_CONTAINER",
        "CASE_INDEX_CONTAINER",
    ):
        assert setting in analyzer
    for setting in ("COSMOS_ENDPOINT", "COSMOS_DATABASE_NAME", "CASE_INDEX_CONTAINER"):
        assert setting in embed
    for forbidden in ("COSMOS_KEY", "COSMOS_CONNECTION_STRING", "listKeys"):
        assert forbidden not in "\n".join((main, analyzer, embed, _read(AZURE / "modules" / "cosmos.bicep")))


def test_deployment_scripts_pass_required_cosmos_and_capability_contracts() -> None:
    for name in ("setup-and-deploy.sh", "setup-and-deploy.ps1"):
        script = _read(ROOT / "scripts" / name)
        for setting in (
            "COSMOS_ACCOUNT_NAME",
            "COSMOS_DATABASE_NAME",
            "CosmosAccountName",
            "CosmosDatabaseName",
            "CapabilityProfiles",
            "ServiceNowDispositionSyncEnabled",
            "CaseQaChatHistoryEnabled",
        ):
            assert setting in script
