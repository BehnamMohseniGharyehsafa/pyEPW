# Security policy

Supported public release line: 0.4.x. Update to the latest patch in that line.
Older local snapshots are retained for reproducibility, not maintained as
separate security branches.

Report vulnerabilities through the repository's **Security → Report a
vulnerability** channel when available. If private reporting is unavailable,
open a minimal issue asking for a private reporting channel without exploit
details, credentials, private addresses or weather data tied to a private site.
Ordinary reproducible conversion bugs belong in the issue tracker.

The package downloads public data without API keys. Never put credentials in
bug reports, metadata attachments or examples. Review caches and output metadata
before sharing them: they include requested location and source URLs. Cache
contents are data, not executable code. Install packages only from the repository's
verified releases or a package index entry linked by this repository.

CI uses offline synthetic fixtures. Live examples and the large validation
study are opt-in; upstream requests are not made on every pull request.
