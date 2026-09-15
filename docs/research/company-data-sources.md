# Free company data sources

Research date: 2026-09-12. Official documentation reviewed. GLEIF, Wikidata and optional US SEC adapters are now implemented, with AI as the final fallback. Companies House and OpenCorporates remain future additions. See the root README for setup and limits.

## Recommendation for this project

Use records from identifiable sources first, retaining the existing AI autocomplete as the last-resort fallback when the configured sources produce no usable candidates or are unavailable. Label AI-only suggestions as unverified. Start with GLEIF for global legal-entity identity, use Wikidata for discovery and aliases, and add national registry or filing adapters where useful. These sources do not establish a complete worldwide company directory.

User clarification: country means where the headquarters is incorporated. Working interpretation: the incorporation jurisdiction of the headquarters legal entity; keep the physical headquarters address separate. Do not infer the parent or headquarters entity from a subsidiary's name alone.

Initial setup can use GLEIF and Wikidata without new API keys, plus SEC public data APIs where relevant. Retain the existing OpenRouter key for AI fallback. Companies House requires a developer account and API key; OpenCorporates requires a key and eligible access terms. GLEIF explicitly documents free access without registration. [GLEIF access](https://www.gleif.org/en/newsroom/blog/lei-look-up-api-gleif-answers-financial-industry-calls-to-enable-faster-customized-and-automated-access-to-the-legal-entity-identifier-data-pool), [Wikidata access](https://www.wikidata.org/wiki/Wikidata:Data_access). See provider sections below for other access requirements.

The implementation separates discovery candidates from legal-entity source records, retains identifiers and provenance, passes the selected identity through the financial-report pipeline, caches searches and distinguishes provider failures from empty results. A manual-entry option remains a possible future addition. A missing match does not establish that a company does not exist; finding its identity does not establish that public financial statements are available.

## GLEIF: global legal entities with LEIs

GLEIF makes its LEI data free of charge under CC0. Its API supports filtering, full-text search, fuzzy name/address matching, ownership relationships and mapped identifiers. This makes it a useful first global identity source. Coverage is current and historical LEI records, so it must not be described as all companies worldwide. [Data terms](https://www.gleif.org/en/meta/lei-data-terms-of-use), [API overview](https://www.gleif.org/en/lei-data/gleif-api), [services](https://www.gleif.org/services/).

Keep legal jurisdiction, legal-address country and headquarters-address country separate. GLEIF's dictionary defines jurisdiction as legal formation and permits country or subdivision codes. Do not substitute an address country for legal jurisdiction. [Data dictionary](https://www.gleif.org/lei-data/access-and-use-lei-data/gleif-data-dictionary/2023-11-07_gleif-data-dictionary_v1.0_final.pdf).

For a larger local index, Golden Copy files are published three times daily with delta files. [Downloads](https://www.gleif.org/en/lei-data/gleif-golden-copy/download-the-golden-copy).

Integration findings: live unauthenticated GLEIF requests succeeded after enabling network access for the checks. Country-filtered name lookup is combined with fulltext autocomplete when necessary. Autocomplete ignores country filters and only returns a small global candidate set; suggested LEIs must be resolved and checked locally. Name filters match words, so short prefixes may need another provider. Wikidata returned HTTP 403 from the development environment during Python checks; the application treats that as provider unavailability and advances to AI. Automated adapter tests use mocked HTTP responses.

## Wikidata: global discovery and enrichment

Structured Wikidata data is CC0, including commercial reuse. Wikidata describes itself as a collaborative secondary knowledge base; its editors and bots maintain statements and source references. Useful fields include multilingual labels, aliases and stable Q identifiers. Treat a Wikidata result as a discovery candidate, not proof of legal registration. [Introduction](https://www.wikidata.org/wiki/Wikidata:Introduction).

The company modeling guide distinguishes country of incorporation (`P17`) from headquarters location (`P159`). Its coverage table shows unequal coverage and missing properties. Validate the actual statements and any temporal qualifiers; do not assume every company item has complete or consistent country data. [Company properties and coverage](https://www.wikidata.org/wiki/Wikidata:WikiProject_Companies/Properties).

For autocomplete, use the text-search interfaces and retrieve identified entities. The documentation explicitly discourages SPARQL regex/fuzzy text search and recommends narrowly scoped SPARQL queries for relational filtering. Observe User-Agent guidance and HTTP 429 backoff. A cached discovery index may be preferable once usage grows. [Data access](https://www.wikidata.org/wiki/Wikidata:Data_access).

## OpenCorporates: broad aggregation, conditional free API

OpenCorporates aggregates primary public data and includes source provenance. Its API site advertises more than 200 million companies. [API overview](https://api.opencorporates.com/).

An API key is required. Documentation says free accounts are for open-data projects/products whose incorporated product or database is released under share-alike attribution conditions. Paid accounts remove the OpenCorporates share-alike restrictions. Default documented limits are 200 requests/month and 50/day, varying by plan. Consequently, do not assume a private application has a suitable free production API. Confirm account eligibility and licensing before selecting this provider. [Current API reference, accounts and limits](https://api.opencorporates.com/documentation/API-Reference).

## Companies House: free UK registry supplement

The official public-data API is free and supplies registry information such as company status, registered-office details and filings. This is a direct registry source for entities within Companies House's scope, not every business operating in the UK. [Free data guidance](https://www.gov.uk/guidance/searching-the-companies-house-register), [API scope](https://developer.company-information.service.gov.uk/).

The API has company-search endpoints, requires API authentication, and permits 600 requests per five-minute window. Use company numbers as identities and retrieve the selected profile to confirm recorded registration details. [Search endpoints](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/search), [authentication](https://developer.company-information.service.gov.uk/get-started), [rate limits](https://developer-specs.company-information.service.gov.uk/guides/rateLimiting).

## SEC EDGAR: free filings supplement

SEC's public `data.sec.gov` APIs require no authentication or API key. They expose submissions by CIK and XBRL financial data, update throughout the day, and provide nightly bulk ZIP files. Submission metadata includes current/former names and public-company ticker/exchange information. This is an especially useful identity-to-financial-filings link. [Public API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

SEC also publishes company-name/CIK/ticker/exchange association files. Coverage is SEC filers, including foreign issuers; it is not a directory of all US companies and an SEC match alone must not establish US incorporation. Automated requests must follow SEC fair-access requirements. [Accessing EDGAR data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data), [public data service](https://data.sec.gov/).
