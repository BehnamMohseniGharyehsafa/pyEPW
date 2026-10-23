# Publishing and using pyEPW

This page records the published source conditions checked on 23 October 2026.
It is general information, not a legal opinion or a guarantee for every country,
business model or international station record. Recheck provider terms for a
new deployment or newly added dataset.

## Code, data and access are separate

1. **Code:** pyEPW is MIT-licensed. Keep the copyright and permission notice when
   distributing it. The independent HTTP client does not incorporate Open-Meteo's
   AGPL server implementation.
2. **Data:** Open-Meteo/Copernicus and GeoNames components use CC BY 4.0; the other
   products retain their source-specific terms. See [DATA_SOURCES.md](../DATA_SOURCES.md).
   Redistribution must preserve attribution, licence information and modifications.
3. **Hosted access:** Open-Meteo's public free API is non-commercial and
   rate-limited. An open-source library or a service free to its users can still
   be used commercially. Advertising, subscriptions and promotional use are
   commercial examples in its [terms](https://open-meteo.com/en/terms).

The current upstream free limits are below 10,000 weighted calls/day, 5,000/hour
and 600/minute. Long date ranges and many variables count as multiple calls;
limits are not simply your Python constructor count. Use caching and control
aggregate traffic across your users. The library performs bounded retries and
caching; it does not coordinate a multi-process hosted service's quota.

## A public API built on this library

A non-commercial service appears compatible with the published Open-Meteo terms
when it respects access limits and attribution. A commercial service needs an
appropriate upstream access agreement. Current [pricing](https://open-meteo.com/en/pricing)
places commercial historical-API access on Professional or higher. Changing
the wrapper's name, caching responses or making the wrapper open source does
not remove the upstream service conditions.

You may use licensed open datasets on your own infrastructure, subject to their
terms. Self-hosting involves compute/storage/transfer costs and does not grant
unrestricted access to anyone else's hosted data servers. Reusing or modifying
the Open-Meteo server itself invokes its [AGPLv3 licence](https://github.com/open-meteo/open-meteo/blob/main/LICENSE),
including corresponding-source obligations for modified network services.

This repository supplies a Python library and CLI. It does not deploy a public
weather server, enroll a billing account, or grant commercial rights to a hosted
upstream service.

## Publishing exports and figures

- Preserve the matching metadata sidecar and the source-specific credits.
- Link Open-Meteo beside displayed results; link CC BY 4.0 where applicable.
- Explain resampling, derived models and changes. Do not label reanalysis as
  exact site measurements or typical-year weather.
- Respect existing downstream reuse rights in CC BY data. Your own API access
  controls do not change the licence on the underlying licensed material.
- For NOAA's international observations, verify dataset and originating-provider
  restrictions for the proposed redistribution. Public availability alone is not
  a blanket legal clearance.

NASA requests publication/redistribution notifications in its referencing guide.
These are requests, not emails automatically sent by this project. No provider
or third party is contacted on a user's behalf by the library.
