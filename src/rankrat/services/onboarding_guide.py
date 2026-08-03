"""Read-only guidance for the onboarding steps Rankrat cannot perform itself.

Onboarding creates provider resources; it cannot prove to a provider that the
operator owns the site. Verification is a human action taken in the provider's
own console, and the token to deploy is issued by that console. Rankrat holds no
credential that can read it, so nothing here invents one: each method names the
artifact and says where the real value comes from.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rankrat.models.boundaries import Provider
from rankrat.policy.boundaries import BoundaryPolicy

_SEARCH_CONSOLE_DOMAIN_PREFIX = "sc-domain:"

_SUMMARY = (
    "Rankrat can create the GA4 property, the Search Console property and the Bing site. "
    "It cannot verify site ownership or deploy a tag. Those are operator actions, and "
    "until they are done the created properties return no data."
)

_RANKRAT_PERFORMS = (
    "Creates one GA4 property and web data stream, returning its Measurement ID.",
    "Adds the site to Google Search Console as an unverified property.",
    "Adds the site to Bing Webmaster Tools as an unverified site.",
    "Records the created resource IDs in the boundary file so later reads are allowed.",
)

_RANKRAT_CANNOT_PERFORM = (
    "Prove site ownership to any provider. Verification tokens are issued by the "
    "provider's own console and Rankrat holds no credential that can read them.",
    "Deploy a tag, an HTML file, a meta tag or a DNS record to the site.",
    "Report whether verification has since succeeded. An unverified Search Console "
    "property answers reads with a siteUnverifiedUser permission level, not data.",
)

_TELL_THE_USER = (
    "Onboarding reporting success does not mean the site is verified. It means the "
    "three create calls were accepted.",
    "Deploy the GA4 Measurement ID first. It is the one artifact Rankrat hands over "
    "directly, and on a URL-prefix property it also satisfies Search Console "
    "verification through the Google Analytics method.",
    "Search Console and Bing each show the exact token, filename or record value on "
    "their own verification screen. Read it there; Rankrat cannot supply it.",
    "A sc-domain: property accepts DNS TXT and nothing else. If DNS is not editable, "
    "onboard the https:// URL-prefix form instead.",
    "Provider data is not retroactive. Collection starts at verification, so the first "
    "useful reads are days away.",
)

_HTML_FILE_METHOD = "html_file"
_META_TAG_METHOD = "meta_tag"
_DNS_TXT_METHOD = "dns_txt"
_DNS_CNAME_METHOD = "dns_cname"
_GOOGLE_ANALYTICS_METHOD = "google_analytics"
_XML_FILE_METHOD = "xml_file"
_IMPORT_FROM_SEARCH_CONSOLE_METHOD = "import_from_search_console"


class SearchConsolePropertyType(StrEnum):
    """Which Search Console property form a configured site URL denotes."""

    DOMAIN = "domain"
    URL_PREFIX = "url_prefix"


class GuideActor(StrEnum):
    """Who performs a step. Nothing marked operator can be done by an agent."""

    RANKRAT = "rankrat"
    OPERATOR = "operator"


@dataclass(frozen=True, slots=True)
class OnboardingGuideRequest:
    """Optionally narrow the guidance to one site URL."""

    site_url: str | None = None


@dataclass(frozen=True, slots=True)
class GuideStep:
    """One ordered step, attributed to whoever can actually perform it."""

    order: int
    actor: GuideActor
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class VerificationMethod:
    """One ownership-proof method, with the real source of its value named."""

    method: str
    label: str
    deploy: str
    value_source: str


@dataclass(frozen=True, slots=True)
class SiteGuidance:
    """Verification options for one site, narrowed by its property form."""

    site_url: str
    configured: bool
    search_console_property_type: SearchConsolePropertyType
    search_console_verification: tuple[VerificationMethod, ...]
    bing_verification: tuple[VerificationMethod, ...]
    configured_ga4_property_ids: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnboardingGuide:
    """The operator procedure plus this runtime's onboarding posture."""

    summary: str
    writes_enabled: bool
    agent_onboarding_enabled: bool
    rankrat_performs: tuple[str, ...]
    rankrat_cannot_perform: tuple[str, ...]
    recommended_order: tuple[GuideStep, ...]
    tell_the_user: tuple[str, ...]
    sites: tuple[SiteGuidance, ...]


_DNS_TXT_VERIFICATION = VerificationMethod(
    method=_DNS_TXT_METHOD,
    label="DNS TXT record",
    deploy="Add the TXT record to the domain's DNS zone, then confirm in Search Console.",
    value_source="Search Console shows the record value on its verification screen.",
)

_URL_PREFIX_VERIFICATION = (
    VerificationMethod(
        method=_GOOGLE_ANALYTICS_METHOD,
        label="Google Analytics tag",
        deploy=(
            "Deploy the GA4 Measurement ID from the onboarding receipt in the site's "
            "public <head>. No second artifact is needed."
        ),
        value_source="The Measurement ID is in the onboarding receipt.",
    ),
    VerificationMethod(
        method=_HTML_FILE_METHOD,
        label="HTML verification file",
        deploy="Serve the issued file at the site root over HTTPS with no redirect.",
        value_source=(
            "Search Console issues the filename and its contents on the verification "
            "screen; both are account-specific."
        ),
    ),
    VerificationMethod(
        method=_META_TAG_METHOD,
        label="HTML meta tag",
        deploy="Place the meta tag in the site's public <head>.",
        value_source="Search Console shows the full tag on its verification screen.",
    ),
    _DNS_TXT_VERIFICATION,
)

_BING_VERIFICATION = (
    VerificationMethod(
        method=_IMPORT_FROM_SEARCH_CONSOLE_METHOD,
        label="Import from Google Search Console",
        deploy=(
            "Once the Search Console property is verified, import it in Bing Webmaster "
            "Tools to carry that verification across."
        ),
        value_source="No artifact to deploy; needs the Search Console property verified first.",
    ),
    VerificationMethod(
        method=_XML_FILE_METHOD,
        label="XML verification file",
        deploy="Serve the issued XML file at the site root over HTTPS.",
        value_source="Bing issues the file on its verification screen; it carries the account ID.",
    ),
    VerificationMethod(
        method=_META_TAG_METHOD,
        label="HTML meta tag",
        deploy="Place the meta tag in the site's public <head>.",
        value_source="Bing shows the full tag on its verification screen.",
    ),
    VerificationMethod(
        method=_DNS_CNAME_METHOD,
        label="DNS CNAME record",
        deploy="Add the CNAME record to the domain's DNS zone.",
        value_source="Bing shows the record on its verification screen.",
    ),
)

_DOMAIN_PROPERTY_NOTE = (
    "This is a Search Console Domain property. DNS TXT is the only method it accepts, "
    "and the Google Analytics shortcut does not apply."
)
_UNCONFIGURED_SITE_NOTE = (
    "Not present in the boundary file. Reads for it are refused until onboarding records "
    "it or it is added by hand."
)


def _search_console_property_type(site_url: str) -> SearchConsolePropertyType:
    if site_url.startswith(_SEARCH_CONSOLE_DOMAIN_PREFIX):
        return SearchConsolePropertyType.DOMAIN
    return SearchConsolePropertyType.URL_PREFIX


def _search_console_verification(
    property_type: SearchConsolePropertyType,
) -> tuple[VerificationMethod, ...]:
    if property_type is SearchConsolePropertyType.DOMAIN:
        return (_DNS_TXT_VERIFICATION,)
    return _URL_PREFIX_VERIFICATION


def _recommended_order(agent_onboarding_enabled: bool) -> tuple[GuideStep, ...]:
    create_detail = (
        "Call site_onboarding_submit, or run the operator command rankrat onboard-site."
        if agent_onboarding_enabled
        else (
            "Agent onboarding is disabled on this server, so no tool performs this step. "
            "The operator runs rankrat onboard-site themselves."
        )
    )
    return (
        GuideStep(
            order=1,
            actor=GuideActor.RANKRAT,
            title="Create the three provider resources",
            detail=create_detail,
        ),
        GuideStep(
            order=2,
            actor=GuideActor.OPERATOR,
            title="Deploy the GA4 Measurement ID",
            detail=(
                "Put the returned G- Measurement ID in the site's public <head>. Until it "
                "is live GA4 collects nothing, and on a URL-prefix property it is also the "
                "cheapest route to Search Console verification."
            ),
        ),
        GuideStep(
            order=3,
            actor=GuideActor.OPERATOR,
            title="Verify the Search Console property",
            detail=(
                "Pick a method the property form allows and deploy its artifact. Until this "
                "succeeds every Search Console read for the site returns no data."
            ),
        ),
        GuideStep(
            order=4,
            actor=GuideActor.OPERATOR,
            title="Verify the Bing site",
            detail=(
                "Importing the now-verified Search Console property is the least work. The "
                "file, meta tag and CNAME methods are equivalent alternatives."
            ),
        ),
        GuideStep(
            order=5,
            actor=GuideActor.OPERATOR,
            title="Publish the IndexNow key, only when submitting URLs",
            detail=(
                "Generated by the repository's init-indexnow tooling and published at the "
                "target host root. Skip entirely when IndexNow is unused."
            ),
        ),
    )


class OnboardingGuideService:
    """Renders the operator procedure, narrowed by the configured boundaries."""

    def __init__(self, policy: BoundaryPolicy) -> None:
        self._policy = policy

    # The posture is passed in rather than held: the caller already owns those two
    # flags, and a second copy here can disagree with the surface actually exposed.
    def render(
        self,
        request: OnboardingGuideRequest,
        *,
        writes_enabled: bool,
        agent_onboarding_enabled: bool,
    ) -> OnboardingGuide:
        """Return the procedure, detailed for the requested or the configured sites."""

        return OnboardingGuide(
            summary=_SUMMARY,
            writes_enabled=writes_enabled,
            agent_onboarding_enabled=agent_onboarding_enabled,
            rankrat_performs=_RANKRAT_PERFORMS,
            rankrat_cannot_perform=_RANKRAT_CANNOT_PERFORM,
            recommended_order=_recommended_order(agent_onboarding_enabled),
            tell_the_user=_TELL_THE_USER,
            sites=self._site_guidance(request.site_url),
        )

    def _site_guidance(self, site_url: str | None) -> tuple[SiteGuidance, ...]:
        configured = self._configured_site_urls()
        if site_url is not None:
            return (self._guidance_for(site_url, configured),)
        return tuple(self._guidance_for(known, configured) for known in configured)

    def _configured_site_urls(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for account in self._policy.accounts():
            for known in (*account.search_console_sites, *account.bing_sites):
                seen.setdefault(known, None)
        return tuple(seen)

    def _guidance_for(self, site_url: str, configured: tuple[str, ...]) -> SiteGuidance:
        property_type = _search_console_property_type(site_url)
        notes: list[str] = []
        if property_type is SearchConsolePropertyType.DOMAIN:
            notes.append(_DOMAIN_PROPERTY_NOTE)
        if site_url not in configured:
            notes.append(_UNCONFIGURED_SITE_NOTE)
        return SiteGuidance(
            site_url=site_url,
            configured=site_url in configured,
            search_console_property_type=property_type,
            search_console_verification=_search_console_verification(property_type),
            bing_verification=_BING_VERIFICATION,
            configured_ga4_property_ids=self._ga4_property_ids(),
            notes=tuple(notes),
        )

    def _ga4_property_ids(self) -> tuple[str, ...]:
        return tuple(
            property_id
            for account in self._policy.accounts()
            if account.provider == Provider.GOOGLE
            for property_id in account.ga4_properties
        )
