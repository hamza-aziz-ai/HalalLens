# HalalLens dashboard

Web dashboard of **HalalLens**: Shariah (AAOIFI-inspired) screening of BSE-listed Indian equities. A Next.js static export served by Caddy, with ratio tables, Explain-Why narration, filing history, watchlists and alerts, and a learning hub on riba and the AAOIFI screens.

Source, docs and issues: [github.com/hamza-aziz-ai/HalalLens](https://github.com/hamza-aziz-ai/HalalLens)

## Tags

- `vX.Y.Z`: a release, for `linux/amd64` and `linux/arm64`. A published version tag is never overwritten.
- `latest`: the newest release.
- `vX.Y.Z-amd64`, `vX.Y.Z-arm64`: the single-architecture images behind each release.

The same images are on GitHub Container Registry as `ghcr.io/hamza-aziz-ai/halallens-ui`.

## What is inside

- Static files only, served by Caddy on port 3000; no Node.js and no Next.js server at runtime; about 25 MB; runs as UID 10001.
- Every release is built and published by CI only after the tests pass. Before it is pushed, each image passes a smoke test and a Trivy scan that fails on fixable critical vulnerabilities. Releases carry an SBOM and build provenance.

## Running it

The dashboard calls the API on the same origin under `/api`, which the front Caddy in the repository's production Docker Compose file provides (with TLS or a Cloudflare Tunnel). Run the stack from that file; see `README_ops.md` in the repository.

## Licence

MIT. Screening results are informational, not a fatwa or investment advice.
