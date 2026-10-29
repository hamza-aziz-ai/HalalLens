# Changelog

## [0.6.3](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.6.2...v0.6.3) (2026-10-29)


### Bug Fixes

* **crawler:** fetch every page of a company's BSE announcements ([#159](https://github.com/hamza-aziz-ai/HalalLens/issues/159)) ([0d881a6](https://github.com/hamza-aziz-ai/HalalLens/commit/0d881a68c3acb256b9221d1e4d53f5744dd4d345))
* **market-data:** stop caching Indian Stock API failures for the life of the process ([#156](https://github.com/hamza-aziz-ai/HalalLens/issues/156)) ([ad60ede](https://github.com/hamza-aziz-ai/HalalLens/commit/ad60ede5ff868fed82d5cb36272778aa5dc7c893))

## [0.6.2](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.6.1...v0.6.2) (2026-10-29)


### Bug Fixes

* **etl:** detect amount scale from whole unit words, not substrings ([#158](https://github.com/hamza-aziz-ai/HalalLens/issues/158)) ([db0c6c0](https://github.com/hamza-aziz-ai/HalalLens/commit/db0c6c08f56ba02edc8ba224e16f50c1e23807df))

## [0.6.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.6.0...v0.6.1) (2026-10-29)


### Bug Fixes

* **ui:** manual analysis no longer fails for free users on the paid /narrate call ([#155](https://github.com/hamza-aziz-ai/HalalLens/issues/155)) ([08bebb3](https://github.com/hamza-aziz-ai/HalalLens/commit/08bebb30761c7c34c95bd018e6f0fac982f683b2))

## [0.6.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.5.3...v0.6.0) (2026-10-29)


### Features

* **ops:** nightly PostgreSQL backups to the object store with 14-day retention ([#152](https://github.com/hamza-aziz-ai/HalalLens/issues/152)) ([a17e2fd](https://github.com/hamza-aziz-ai/HalalLens/commit/a17e2fd34e0dd192de91549a6c66915783a8a31d))

## [0.5.3](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.5.2...v0.5.3) (2026-10-29)


### Bug Fixes

* **market-data:** read the current BSE and NSE bhavcopy files ([#150](https://github.com/hamza-aziz-ai/HalalLens/issues/150)) ([9522273](https://github.com/hamza-aziz-ai/HalalLens/commit/95222736ab6835d48fba351d68a4e54a951602b7))

## [0.5.2](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.5.1...v0.5.2) (2026-10-28)


### Bug Fixes

* **ui:** serve the dashboard image as static files, without Next.js or Node.js at runtime ([#147](https://github.com/hamza-aziz-ai/HalalLens/issues/147)) ([fe2c29b](https://github.com/hamza-aziz-ai/HalalLens/commit/fe2c29b3b871cdbdd32f3f4f647975d57e427f12))

## [0.5.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.5.0...v0.5.1) (2026-10-28)


### Bug Fixes

* **market-data:** cap Indian Stock API calls per month and stop sending the key in URLs ([#145](https://github.com/hamza-aziz-ai/HalalLens/issues/145)) ([0b36511](https://github.com/hamza-aziz-ai/HalalLens/commit/0b3651104dee02c56d17f96812c488d87821231e))

## [0.5.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.4.0...v0.5.0) (2026-10-28)


### Features

* **deploy:** add a Cloudflare Tunnel mode beside Caddy's own TLS ([#134](https://github.com/hamza-aziz-ai/HalalLens/issues/134)) ([0194ee3](https://github.com/hamza-aziz-ai/HalalLens/commit/0194ee3d4e7ad51801ffeb4a576c0a2a0f105b64))

## [0.4.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.3.0...v0.4.0) (2026-10-28)


### Features

* **storage:** store filing PDFs in Cloudflare R2; drop the unavailable MinIO image ([#131](https://github.com/hamza-aziz-ai/HalalLens/issues/131)) ([e2a3a99](https://github.com/hamza-aziz-ai/HalalLens/commit/e2a3a99a0875e5b0fd6c8529b9fc54dcb5dd0347))

## [0.3.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.2.2...v0.3.0) (2026-10-28)


### Features

* **deploy:** serve the dashboard and the API on one origin behind Caddy ([#128](https://github.com/hamza-aziz-ai/HalalLens/issues/128)) ([fda9a99](https://github.com/hamza-aziz-ai/HalalLens/commit/fda9a9986abe67ae6a8713984645d8d0b4f74342))


### Bug Fixes

* **config:** replace the developer LAN address defaults with portable ones ([#127](https://github.com/hamza-aziz-ai/HalalLens/issues/127)) ([1270ee9](https://github.com/hamza-aziz-ai/HalalLens/commit/1270ee9bac4f5fd706e69aeb7c5422ff73ccc234))

## [0.2.2](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.2.1...v0.2.2) (2026-10-28)


### Bug Fixes

* **ui:** drop the unwired GitHub Pages deployment and the LAN-address API fallback ([#123](https://github.com/hamza-aziz-ai/HalalLens/issues/123)) ([7ae29b7](https://github.com/hamza-aziz-ai/HalalLens/commit/7ae29b73f441107afb5b3334d43e4663fa813ec8))

## [0.2.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.2.0...v0.2.1) (2026-10-28)


### Bug Fixes

* **api:** take /alerts/check verdicts from stored evaluations and scope them to the caller ([#115](https://github.com/hamza-aziz-ai/HalalLens/issues/115)) ([6bee561](https://github.com/hamza-aziz-ai/HalalLens/commit/6bee561782d420f402a9529bbe6ecd8229a33d82))

## [0.2.0](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.1.1...v0.2.0) (2026-10-28)


### Features

* **jobs:** recompute stored evaluations from current stored inputs, dry run by default ([#91](https://github.com/hamza-aziz-ai/HalalLens/issues/91)) ([9d304ee](https://github.com/hamza-aziz-ai/HalalLens/commit/9d304eeec3b9dfc1764f6f02d2f78aade9a06069))

## [0.1.1](https://github.com/hamza-aziz-ai/HalalLens/compare/v0.1.0...v0.1.1) (2026-10-28)


### Bug Fixes

* **narrator:** restore the optional LLM mode behind a best-effort consistency guard ([8c9dda2](https://github.com/hamza-aziz-ai/HalalLens/commit/8c9dda2d7a173c16a2cc9ef5e5f1a710171dc4bb))
* **ratio-engine:** stop partial data from passing the Shariah screen ([d048ca2](https://github.com/hamza-aziz-ai/HalalLens/commit/d048ca2e937f0d8efe321d21a28d8357f1a7c1a0))
* **ratio-engine:** stop partial data from passing the Shariah screen ([c359149](https://github.com/hamza-aziz-ai/HalalLens/commit/c359149ec5b3d65f6de29b0deb4b57ca79907e71))
