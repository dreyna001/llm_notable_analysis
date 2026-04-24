"""Default customer and context bundle mappings."""

from __future__ import annotations

from ..core.config_models import CustomerBundle
from ..core.context import ContextBundle


DEFAULT_CUSTOMER_BUNDLES: dict[str, CustomerBundle] = {
    "acme_default": CustomerBundle(
        prompt_pack_name="soc_standard_v1",
        context_bundle_name="soc_context_default",
        query_policy_bundle_name="spl_readonly_default",
        sink_bundle_name="local_reports_default",
        input_mapping_bundle_name="splunk_notable_default",
    ),
    "acme_executive": CustomerBundle(
        prompt_pack_name="soc_executive_v1",
        context_bundle_name="soc_context_default",
        query_policy_bundle_name="spl_readonly_default",
        sink_bundle_name="local_reports_default",
        input_mapping_bundle_name="splunk_notable_default",
    ),
}


DEFAULT_CONTEXT_BUNDLES: dict[str, ContextBundle] = {
    "soc_context_default": ContextBundle(
        bundle_name="soc_context_default",
        enabled_context_sources=("soc_sops", "splunk_field_dictionary"),
        vector_backend="sqlite_faiss",
        index_names=("soc_sops", "splunk_dictionary"),
        retrieval_limit=8,
        context_budget_chars=5000,
        provenance_required=True,
    ),
}

