from __future__ import annotations

import json
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
            "functions-disposition.bicep",
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


def test_analyzer_has_azure_openai_and_polling_blob_trigger_rbac() -> None:
    main = _read(AZURE / "main.bicep")
    analyzer = _read(AZURE / "modules" / "functions-analyzer.bicep")
    openai = _read(AZURE / "modules" / "openai-access.bicep")
    search = _read(AZURE / "modules" / "search-access.bicep")
    assert "openai-access.bicep" in main
    assert "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd" in openai
    assert "analyzerPrincipalId: identities.outputs.analyzer.principalId" in main
    assert "resource analyzerOpenAiAccess" in openai
    assert "analyzerPrincipalId: identities.outputs.analyzer.principalId" in main
    assert "searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'" in search
    assert "resource analyzerIndexContributor" in search
    assert "resource portalIndexReader" in search
    assert "principalIds array" not in search
    assert "content_vector must be 1024 dimensions" in main
    assert "RAG_INGEST_QUEUE_NAME" in analyzer
    assert "rag-ingest-invocations" in _read(AZURE / "modules" / "storage.bicep")
    assert "ragIngestPoisonQueue" in _read(AZURE / "modules" / "storage.bicep")
    assert "ragSourceBlobReader" in analyzer
    assert "AZURE_OPENAI_ANALYSIS_DEPLOYMENT" in analyzer
    assert "AZURE_AI_FOUNDRY" not in analyzer
    assert "blobOwnerRoleId" in analyzer
    assert "queueContributorRoleId" in analyzer
    assert "InputStorage__blobServiceUri" in analyzer
    assert "InputStorage__queueServiceUri" in analyzer


def test_single_digest_image_and_wrapper_isolation_are_explicit() -> None:
    main = _read(AZURE / "main.bicep")
    analyzer = _read(AZURE / "modules" / "functions-analyzer.bicep")
    embed = _read(AZURE / "modules" / "functions-embed.bicep")
    disposition = _read(AZURE / "modules" / "functions-disposition.bicep")
    portal = _read(AZURE / "modules" / "functions-portal.bicep")
    assert main.count("containerImageUri: validatedContainerImageUri") == 4
    assert "usgovvirginia" in main
    assert "AzureUSGovernment" in main
    assert "@sha256:" in main
    assert "@sha256" in main
    expected_wrappers = {
        "intake_blob": {"analyzer": "false", "embed": "true", "disposition": "true", "portal": "true"},
        "analyzer_queue": {"analyzer": "false", "embed": "true", "disposition": "true", "portal": "true"},
        "case_embed_queue": {"analyzer": "true", "embed": "false", "disposition": "true", "portal": "true"},
        "disposition_sync_timer": {"analyzer": "true", "embed": "true", "portal": "true"},
        "closed_ticket_sync_timer": {"analyzer": "true", "embed": "true", "portal": "true"},
        "closed_ticket_embed_timer": {"analyzer": "true", "embed": "true", "portal": "true"},
        "operations_monitor_timer": {"analyzer": "true", "embed": "true", "disposition": "false", "portal": "true"},
        "portal_http": {"analyzer": "true", "embed": "true", "disposition": "true", "portal": "false"},
    }
    modules = {
        "analyzer": analyzer,
        "embed": embed,
        "disposition": disposition,
        "portal": portal,
    }
    for wrapper, expected_by_app in expected_wrappers.items():
        for app_name, expected_value in expected_by_app.items():
            setting = f"AzureWebJobs.{wrapper}.Disabled', value: '{expected_value}'"
            assert modules[app_name].count(setting) == 1
    assert "AzureWebJobs.disposition_sync_timer.Disabled', value: string(!serviceNowDispositionSyncEnabled)" in disposition
    assert "AzureWebJobs.closed_ticket_sync_timer.Disabled', value: string(!serviceNowClosedTicketSyncEnabled)" in disposition
    assert "AzureWebJobs.closed_ticket_embed_timer.Disabled', value: string(!closedTicketRagEnabled)" in disposition
    assert "AzureWebJobs.rag_ingest_queue.Disabled', value: 'true'" in disposition
    expected_disabled_counts = {
        "analyzer": 8,
        "embed": 9,
        "disposition": 9,
        "portal": 9,
    }
    for app_name, module in modules.items():
        assert module.count("AzureWebJobs.") == expected_disabled_counts[app_name], app_name
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


def test_portal_edge_uses_frontdoor_private_link_directly_to_function() -> None:
    main = _read(AZURE / "main.bicep")
    frontdoor = _read(AZURE / "modules" / "frontdoor-portal.bicep")
    assert "ApiManagement" not in main
    assert "portalFunctionId" in frontdoor
    assert "portalFunctionHostName" in frontdoor
    assert "groupId: 'sites'" in frontdoor
    assert "Front Door private portal Function origin" in frontdoor


def test_frontdoor_routes_private_origins_without_single_origin_probes_or_api_cache() -> None:
    frontdoor = _read(AZURE / "modules" / "frontdoor-portal.bicep")
    assert "Premium_AzureFrontDoor" in frontdoor
    assert "originResponseTimeoutSeconds: 240" in frontdoor
    assert "patternsToMatch: ['/api/*']" in frontdoor
    assert "patternsToMatch: ['/health']" in frontdoor
    assert "patternsToMatch: ['/ready']" in frontdoor
    assert "patternsToMatch: ['/', '/index.html']" in frontdoor
    for group_id in ("'web'", "'sites'"):
        assert f"groupId: {group_id}" in frontdoor
    assert "resource chatOrigin" not in frontdoor
    assert "resource chatRoute" not in frontdoor
    assert "Front Door private chat origin" not in frontdoor
    assert "healthProbeSettings:" not in frontdoor
    api_prefix = frontdoor[: frontdoor.index("resource uiRoute")]
    assert "cacheConfiguration:" not in api_prefix


def test_portal_deploy_flow_approves_every_private_origin() -> None:
    for name in ("setup-and-deploy.sh", "setup-and-deploy.ps1"):
        script = _read(ROOT / "scripts" / name)
        assert "portal-function" in script
        assert "portal-web" in script
        assert "private-endpoint-connection approve" in script
        assert "sharedPrivateLinkResource.status" in script
        assert "publicNetworkAccess" in script
        assert "PORTAL_VALIDATION_BEARER_TOKEN" in script
        assert (
            "PORTAL_ENTRA_REQUIRED_APP_ROLE is required when the analyst portal is enabled."
            in script
        )
        assert (
            "PORTAL_ENTRA_REQUIRED_APP_ROLE must match the final segment of "
            "PORTAL_OIDC_API_SCOPE" in script
        )
        assert "Authorization" in script
        assert "storage blob upload-batch" in script
        assert "--auth-mode login" in script
        assert "VITE_PORTAL_API_BASE_URL" in script
        assert "functionapp show" in script
        assert "AZURE_DEPLOYMENT_PREFIX" in script
        for oidc_setting in (
            "PORTAL_OIDC_CLIENT_ID",
            "PORTAL_OIDC_AUTHORITY",
            "PORTAL_OIDC_API_SCOPE",
        ):
            assert oidc_setting in script
        assert "privateLinkServiceConnectionState.description" in script
        assert "Front Door private static website origin" in script
        assert "Front Door private portal Function origin" in script
        assert "Front Door private chat origin" not in script


def test_deployment_preflights_run_before_azure_mutation() -> None:
    for name in ("setup-and-deploy.sh", "setup-and-deploy.ps1"):
        script = _read(ROOT / "scripts" / name)
        mutation = script.index("az group create")
        for gate in (
            "-m pytest tests -q",
            "-m pytest tests/test_portal_openapi_contract.py -q",
            "bicep build --file deploy/azure/main.bicep",
            "docker build --platform linux/amd64",
            "npm --prefix frontend/analyst-portal test",
            "npm --prefix frontend/analyst-portal run build",
        ):
            assert script.index(gate) < mutation
        assert "Front Door private portal Function origin" in script


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
        for function_name in (
            "intake_blob",
            "analyzer_queue",
            "case_embed_queue",
            "disposition_sync_timer",
            "operations_monitor_timer",
        ):
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


def test_cosmos_is_single_region_serverless_strong_keyless_and_resilience_parameterized() -> None:
    cosmos = _read(AZURE / "modules" / "cosmos.bicep")
    assert "{ name: 'EnableServerless' }" in cosmos
    assert "defaultConsistencyLevel: 'Strong'" in cosmos
    assert cosmos.count("locationName: location") == 1
    assert "enableAutomaticFailover: false" in cosmos
    assert "isZoneRedundant: zoneRedundant" in cosmos
    assert "continuousBackupEnabled" in cosmos
    assert "type: 'Continuous'" in cosmos
    assert "tier: 'Continuous7Days'" in cosmos
    assert "disableLocalAuth: true" in cosmos
    assert "disableKeyBasedMetadataWriteAccess: true" in cosmos
    assert not re.search(r"\b(?:throughput|autoscaleSettings)\s*:", cosmos)


def test_storage_and_functions_resilience_are_guarded_and_per_app_host_capable() -> None:
    main = _read(AZURE / "main.bicep")
    storage = _read(AZURE / "modules" / "storage.bicep")
    network = _read(AZURE / "modules" / "network.bicep")
    assert "IsolateFunctionsHostStorage bool = false" in main
    for app in ("Analyzer", "Embed", "Disposition", "Portal"):
        assert f"{app}HostStorageAccountName" in main
        assert f"{app.lower()}HostStorageAccountName" in storage
        assert f"{app.lower()}HostBlobServiceUri" in storage
    assert "functionsHostStorageAccountNames" in network
    assert "hostEndpointSpecs = flatten" in network
    assert "StorageSkuName string = 'Standard_LRS'" in main
    assert "@allowed(['Standard_LRS', 'Standard_ZRS'])" in main
    assert "var validatedBlobDataProtection = BlobDataProtectionEnabled" in main
    assert "var validatedCosmosContinuousBackup = CosmosContinuousBackupEnabled" in main
    assert "isVersioningEnabled: blobDataProtectionEnabled" in storage
    assert "containerDeleteRetentionPolicy" in storage
    assert "previousVersionRetentionDays" in storage
    assert "zoneRedundant: FunctionPlanZoneRedundant" in main
    assert "capacity: FunctionPlanZoneRedundant ? 3 : 1" in main
    assert "StorageSkuName must be Standard_ZRS when FunctionPlanZoneRedundant=true." in main
    for module_name in (
        "functions-analyzer.bicep",
        "functions-embed.bicep",
        "functions-disposition.bicep",
        "functions-portal.bicep",
    ):
        function_module = _read(AZURE / "modules" / module_name)
        assert "param zoneRedundant bool = false" in function_module
        assert "minimumElasticInstanceCount: zoneRedundant ? 2 : 1" in function_module


def test_portal_edge_does_not_provision_an_unused_apim_subnet() -> None:
    network = _read(AZURE / "modules" / "network.bicep")
    assert "apim" not in network.lower()
    assert "serviceName: 'Microsoft.Web/serverFarms'" in network
    assert "private-endpoints" in network


def test_deployment_scripts_pass_and_preflight_production_resilience_contracts() -> None:
    for name in ("setup-and-deploy.sh", "setup-and-deploy.ps1"):
        script = _read(ROOT / "scripts" / name)
        for setting in (
            "ISOLATE_FUNCTIONS_HOST_STORAGE",
            "ANALYZER_HOST_STORAGE_ACCOUNT_NAME",
            "EMBED_HOST_STORAGE_ACCOUNT_NAME",
            "DISPOSITION_HOST_STORAGE_ACCOUNT_NAME",
            "PORTAL_HOST_STORAGE_ACCOUNT_NAME",
            "STORAGE_SKU_NAME",
            "BLOB_DATA_PROTECTION_ENABLED",
            "COSMOS_CONTINUOUS_BACKUP_ENABLED",
            "COSMOS_CONTINUOUS_BACKUP_MIGRATION_ACKNOWLEDGED",
            "FUNCTION_PLAN_ZONE_REDUNDANT",
            "COSMOS_ZONE_REDUNDANT",
        ):
            assert setting in script
        assert "BLOB_DATA_PROTECTION_ENABLED=true is required for production." not in script
        assert "COSMOS_CONTINUOUS_BACKUP_ENABLED=true is required for production." not in script
        assert "FUNCTION_PLAN_ZONE_REDUNDANT=true requires STORAGE_SKU_NAME=Standard_ZRS." in script
        assert "backupPolicy.type" in script
        assert "existing Periodic Cosmos account is one-way" in script
        assert "cannot be enabled in place on an existing non-zonal serverless account" in script


def test_deployment_scripts_require_an_exact_immutable_sha256_digest() -> None:
    bash = _read(ROOT / "scripts" / "setup-and-deploy.sh")
    powershell = _read(ROOT / "scripts" / "setup-and-deploy.ps1")
    assert "^.+@sha256:[0-9a-fA-F]{64}$" in bash
    assert "@sha256:[0-9a-fA-F]{64}$" in powershell


def test_cosmos_container_partition_and_ttl_contracts_are_exact() -> None:
    cosmos = _read(AZURE / "modules" / "cosmos.bicep")
    expected_partition_keys = {
        "sideEffectIdempotency": "/id",
        "caseIndex": "/case_id",
        "disposition": "/snow_sys_id",
        "dispositionSyncState": "/job_name",
        "closedTicket": "/ticket_id",
        "closedTicketSyncState": "/job_name",
        "chatSessions": "/user_id",
        "chatMessages": "/session_id",
        "chatQuota": "/user_id",
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
        "closedTicket",
        "chatSessions",
        "chatMessages",
        "chatQuota",
    }
    for resource_name in ttl_resources:
        assert "defaultTtl: -1" in resource_bodies[resource_name]
    assert "defaultTtl" not in resource_bodies["dispositionSyncState"]
    assert "defaultTtl" not in resource_bodies["closedTicketSyncState"]


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
        "{ path: '/index_status', order: 'ascending' }",
        "{ path: '/source_updated_at', order: 'ascending' }",
        "{ path: '/ticket_id', order: 'ascending' }",
        "{ path: '/expires_at_epoch', order: 'ascending' }",
        "{ path: '/active', order: 'ascending' }",
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
    for scope_variable, container_name in (
        ("sideEffectIdempotencyScope", "sideEffectIdempotencyContainerName"),
        ("caseIndexScope", "caseIndexContainerName"),
        ("dispositionScope", "dispositionContainerName"),
        ("dispositionSyncStateScope", "dispositionSyncStateContainerName"),
        ("chatSessionsScope", "chatSessionsContainerName"),
        ("chatMessagesScope", "chatMessagesContainerName"),
        ("chatQuotaScope", "chatQuotaContainerName"),
        ("closedTicketScope", "closedTicketContainerName"),
        ("closedTicketSyncStateScope", "closedTicketSyncStateContainerName"),
    ):
        assert (
            f"var {scope_variable} = "
            f"'${{account.id}}/dbs/${{databaseName}}/colls/${{{container_name}}}'"
        ) in cosmos
        assert f"scope: {scope_variable}" in cosmos
    for container_resource in (
        "sideEffectIdempotency",
        "caseIndex",
        "disposition",
        "dispositionSyncState",
        "chatSessions",
        "chatMessages",
        "chatQuota",
        "closedTicket",
        "closedTicketSyncState",
    ):
        # The role-assignment GUID references the container ARM ID, preserving an
        # implicit deployment dependency while its scope uses the Cosmos data path.
        assert f"guid({container_resource}.id," in cosmos
    assert not re.search(r"\bscope:\s+\w+\.id\b", cosmos)
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
    assert "deployClosedTicketContainers: deployClosedTicketContainers" in main
    assert "deployChatHistoryContainers: deployChatHistoryContainers" in main
    assert "deployChatQuota: deployPortal && PortalChatDistributedQuotaEnabled" in main


def test_distributed_chat_quota_is_configurable_and_least_privilege() -> None:
    main = _read(AZURE / "main.bicep")
    portal = _read(AZURE / "modules" / "functions-portal.bicep")
    cosmos = _read(AZURE / "modules" / "cosmos.bicep")
    assert "ChatQuotaContainerName string" in main
    assert "chatQuotaContainerName: cosmos.outputs.chatQuotaContainerName" in main
    assert "PORTAL_CHAT_QUOTA_CONTAINER" in portal
    assert "PORTAL_CHAT_DISTRIBUTED_QUOTA_ENABLED" in portal
    assert "can retain at most 4096 recent request IDs" in main
    assert "resource portalChatQuotaContributor" in cosmos
    assert "scope: chatQuotaScope" in cosmos
    for name in ("setup-and-deploy.sh", "setup-and-deploy.ps1"):
        script = _read(ROOT / "scripts" / name)
        for setting in (
            "PORTAL_CHAT_DISTRIBUTED_QUOTA_ENABLED",
            "PORTAL_CHAT_QUOTA_CONTAINER",
            "PORTAL_CHAT_PER_USER_MAX_CONCURRENCY",
            "PORTAL_CHAT_QUOTA_WINDOW_SECONDS",
            "PORTAL_CHAT_MAX_REQUESTS_PER_WINDOW",
            "PORTAL_CHAT_MAX_BUDGET_UNITS_PER_WINDOW",
            "PORTAL_CHAT_BUDGET_UNITS_PER_REQUEST",
            "PORTAL_CHAT_LEASE_SECONDS",
            "PORTAL_CHAT_REQUEST_DEDUPE_SECONDS",
        ):
            assert setting in script


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


def test_analyzer_threads_compressed_input_limit_into_runtime_settings() -> None:
    main = _read(AZURE / "main.bicep")
    analyzer = _read(AZURE / "modules" / "functions-analyzer.bicep")
    assert "param MaxCompressedInputBytes int = 1048576" in main
    assert "maxCompressedInputBytes: MaxCompressedInputBytes" in main
    assert "param maxCompressedInputBytes int = 1048576" in analyzer
    assert "MAX_COMPRESSED_INPUT_BYTES" in analyzer
    for name in ("setup-and-deploy.sh", "setup-and-deploy.ps1"):
        assert "MaxCompressedInputBytes" in _read(ROOT / "scripts" / name)


def test_disposition_app_is_always_deployed_keyless_and_least_privilege() -> None:
    main = _read(AZURE / "main.bicep")
    disposition = _read(AZURE / "modules" / "functions-disposition.bicep")
    assert "module dispositionFunction 'modules/functions-disposition.bicep' = {" in main
    assert "AzureFunctionsJobHost__functionTimeout', value: '00:15:00'" in disposition
    assert "DISPOSITION_SYNC_SCHEDULE', value: '0 0 0 * * *'" in disposition
    assert "OPERATIONS_MONITOR_SCHEDULE', value: '0 */5 * * * *'" in disposition
    assert "INPUT_QUEUE_SERVICE_URI" in disposition
    assert "OUTPUT_QUEUE_SERVICE_URI" in disposition
    assert "queueReaderRoleId = '19e7f393-937e-4f77-808e-94535e297925'" in disposition
    assert "resource outputBlobReader" in disposition
    assert "if (serviceNowDispositionSyncEnabled)" in disposition
    assert "if (serviceNowClosedTicketSyncEnabled || closedTicketRagEnabled)" in disposition
    assert "SERVICENOW_CLOSED_TICKET_SYNC_ENABLED" in disposition
    assert "CLOSED_TICKET_RAG_ENABLED" in disposition
    assert "dispositionOpenAiAccess" in _read(AZURE / "modules" / "openai-access.bicep")
    assert "dispositionIndexContributor" in _read(AZURE / "modules" / "search-access.bicep")
    assert "IMAGE_INGEST_ENABLED" in _read(AZURE / "modules" / "functions-analyzer.bicep")
    assert "RAG_RERANK_ENABLED" in _read(AZURE / "modules" / "functions-analyzer.bicep")
    assert "CASE_QA_CLOSED_TICKET_ENABLED" in _read(AZURE / "modules" / "functions-portal.bicep")
    assert "CASE_QA_CHAT_IMAGES_ENABLED" in _read(AZURE / "modules" / "functions-portal.bicep")
    assert "acrUseManagedIdentityCreds: true" in disposition
    assert "AzureWebJobsStorage__credential" in disposition
    for forbidden in (
        "AzureWebJobsStorage',",
        "DOCKER_REGISTRY_SERVER_PASSWORD",
        "SERVICENOW_DISPOSITION_SYNC_TOKEN=",
        "COSMOS_KEY",
        "STORAGE_ACCOUNT_KEY",
    ):
        assert forbidden not in disposition


def test_monitoring_alerts_are_conditional_complete_and_action_group_only() -> None:
    main = _read(AZURE / "main.bicep")
    monitoring = _read(AZURE / "modules" / "observability.bicep")
    assert "DeploymentEnvironment string = 'development'" in main
    assert "AlertActionGroupResourceId is required when DeploymentEnvironment=production." in main
    assert "createAlerts = deployAlertRules && !empty(alertActionGroupResourceId)" in monitoring
    assert "Microsoft.Insights/actionGroups" not in monitoring
    for queue_name in (
        "webjobs-blobtrigger-poison",
        "notable-analysis-jobs-poison",
        "case-embed-invocations-poison",
        "notable-analysis-jobs",
        "case-embed-invocations",
    ):
        assert queue_name in monitoring
    assert "var queueDepthTracePrefix = 'notable.queue.depth.v1 '" in main
    assert "param queueDepthTracePrefix string" in monitoring
    assert "parse_json" in monitoring
    assert "queueTelemetryMaxAgeMinutes" in monitoring
    assert "Oldest <= ago(14m)" in monitoring
    assert "MinimumDepth" in monitoring
    assert "windowSize: 'PT15M'" in monitoring
    for alert_signal in (
        "function-failures",
        "function-timeouts",
        "AzureOpenAIRequests",
        "TotalRequests",
        "Percentage5XX",
        "AppAvailabilityResults",
        "disposition-completion-missed",
    ):
        assert alert_signal in monitoring
    assert "actionGroups: [alertActionGroupResourceId]" in monitoring


def test_deployment_scripts_enforce_production_monitoring_and_validate_fourth_app() -> None:
    for name in ("setup-and-deploy.sh", "setup-and-deploy.ps1"):
        script = _read(ROOT / "scripts" / name)
        for contract in (
            "DEPLOYMENT_ENVIRONMENT",
            "ALERT_ACTION_GROUP_RESOURCE_ID",
            "PORTAL_SYNTHETIC_CHECK_NAME",
            "ServiceNowDispositionSyncTokenSecretName",
            "DispositionFunctionAppName",
            "MonitoringAlertRuleNames",
            "operations_monitor_timer",
            "Microsoft.Insights/actionGroups",
            "AppAvailabilityResults",
            "fresh successful",
        ):
            assert contract in script
